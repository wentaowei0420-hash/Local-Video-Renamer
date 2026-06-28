import os
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from threading import Lock

from app.core.backend_protocol import BACKEND_API_REVISION, BACKEND_PROCESS_CODE_FINGERPRINT
from app.core.combo_enrichment import get_combo_label, normalize_combo_key
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, VIDEO_LIBRARY_TARGET
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_ENTITY_ACTOR,
)
from app.core.project_paths import DATABASE_FILE, PROJECT_ROOT
from app.data.database_handler import VideoDatabase
from app.scraper.avfan_scraper import reset_avfan_browser_profile
from app.services.auth import AutoLoginService
from app.services.detail import ActorDetailLibrary, CodePrefixDetailLibrary, resolve_update_status
from app.services.enrichment import (
    ComboEnrichmentService,
    ComboProgressService,
    ComboTaskLogger,
    EnrichmentProgressService,
    EnrichmentTaskState,
    LibraryEnrichmentService,
    TaskTraceLogger,
)
from app.services.identity import split_actor_names
from app.services.ladder import LadderBoardService, VideoLadderTagService
from app.services.library import (
    ActorLibrarySyncService,
    CanglanggeCandidateService,
    CodePrefixLibrary,
    CodePrefixVideoCategoryBulkService,
    DataCenterService,
    LibraryAdminService,
    LibraryStatusSyncService,
    PathLibrary,
    summarize_paths,
)
from app.services.local_video import LocalVideoLibraryService
from app.services.video import VideoFilterService


class BackendService:
    def __init__(self, base_dir=None, instance_token=''):
        self.base_dir = Path(base_dir or PROJECT_ROOT)
        self.instance_token = str(instance_token or '').strip()
        self.process_id = os.getpid()
        self.db = VideoDatabase(DATABASE_FILE)
        self.video_filter_service = VideoFilterService()
        self.video_ladder_tag_service = VideoLadderTagService(self.db)
        self.local_video_library = LocalVideoLibraryService(self.db)
        self.actor_detail_library = ActorDetailLibrary(self.db, self.video_ladder_tag_service, self.video_filter_service)
        self.actor_library_sync_service = ActorLibrarySyncService(self.db)
        self.code_prefix_detail_library = CodePrefixDetailLibrary(
            self.db,
            self.video_ladder_tag_service,
            self.video_filter_service,
        )
        self.code_prefix_library = CodePrefixLibrary(self.db, self.video_filter_service)
        self.code_prefix_video_category_bulk_service = CodePrefixVideoCategoryBulkService(self.db)
        self.canglangge_candidate_service = CanglanggeCandidateService(self.db)
        self.data_center_service = DataCenterService(self.db, self.video_filter_service)
        self.library_admin_service = LibraryAdminService(self.db)
        self.library_status_sync_service = LibraryStatusSyncService(self.db)
        self.ladder_board_service = LadderBoardService(self.db)
        self.path_library = PathLibrary()
        self.enrichment_progress = EnrichmentProgressService()
        self.combo_progress = ComboProgressService()
        self.enrichment_task_state = EnrichmentTaskState()
        self._snapshot_lock = Lock()
        self._ladder_board_snapshots = {}
        self._path_library_snapshot = None
        self._canglangge_snapshot = None
        self.database_loaded = False

    def load_database(self):
        self.actor_library_sync_service.sync_from_video_library()
        self.db.sanitize_ineligible_javtxt_state()
        self.database_loaded = True
        return {
            'count': self.db.get_video_count(),
            'actor_count': self.db.get_actor_count(),
            'db_path': str(self.db.db_path),
        }

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'backend_instance_token': self.instance_token,
            'backend_process_id': self.process_id,
            'project_root': str(self.base_dir),
            'database_loaded': self.database_loaded,
            'db_path': str(self.db.db_path),
            'enrichment_running': self.enrichment_task_state.is_running,
            'active_task_kind': self.enrichment_task_state.active_kind,
        }

    def scan(self, folder_path):
        self.ensure_database_loaded()
        return self.local_video_library.scan_folder(folder_path)

    def rename(self, plans_data):
        return self.local_video_library.execute_renames(plans_data)

    def import_videos(self, plans_data):
        self.ensure_database_loaded()
        return {'success_count': self.local_video_library.import_videos(plans_data)}

    def list_videos(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_search = str(search_text or '').strip()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_video_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)

        medal_maps = None
        expanded_rows = []
        if normalized_search:
            medal_maps = self.video_ladder_tag_service.load_medal_maps()
            expanded_rows = self._expand_video_search_candidates_by_ladder_tags(normalized_search, medal_maps=medal_maps)

        if expanded_rows:
            rows_by_code = {
                str((row or {}).get('code', '') or '').strip(): dict(row or {})
                for row in self._list_videos_query(
                    normalized_search,
                    sort_field=normalized_sort_field,
                    sort_order=normalized_sort_order,
                )
                if str((row or {}).get('code', '') or '').strip()
            }
            for row in expanded_rows:
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})

            visible_rows = self.video_filter_service.filter_video_rows(list(rows_by_code.values()))
            enriched_rows = self.video_ladder_tag_service.enrich_video_rows(visible_rows, medal_maps=medal_maps)
            filtered_rows = self.video_ladder_tag_service.filter_video_rows(enriched_rows, normalized_search)
            sorted_rows = self._sort_video_rows_for_listing(filtered_rows, normalized_sort_field, normalized_sort_order)
            paged_rows = self._slice_rows(sorted_rows, normalized_limit, normalized_offset)
            return {
                'videos': paged_rows,
                'total_count': len(sorted_rows),
                'offset': normalized_offset,
                'limit': normalized_limit,
            }

        rows = self._list_videos_query(
            normalized_search,
            sort_field=normalized_sort_field,
            sort_order=normalized_sort_order,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return {
            'videos': self.video_filter_service.filter_video_rows(rows),
            'total_count': self._count_videos_for_listing(normalized_search, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def get_video_enrichment_summary(self):
        return {'summary': self.db.get_video_enrichment_summary()}

    def get_data_center_summary(self, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_summary_snapshot(force_refresh=force_refresh)

    def get_actor_metric_analysis(self, metric_key, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_actor_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)

    def get_code_prefix_metric_analysis(self, metric_key, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_code_prefix_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)

    def get_metric_analysis(self, analysis_type, metric_key, force_refresh=False):
        normalized_type = str(analysis_type or 'actor').strip().lower() or 'actor'
        if normalized_type == 'actor':
            return self.get_actor_metric_analysis(metric_key, force_refresh=force_refresh)
        if normalized_type == 'code_prefix':
            return self.get_code_prefix_metric_analysis(metric_key, force_refresh=force_refresh)
        raise ValueError(f'Unknown analysis type: {normalized_type}')

    def get_enrichment_progress(self):
        if self.enrichment_task_state.active_kind == 'combo':
            return {'progress': self.combo_progress.snapshot()}
        combo_snapshot = self.combo_progress.snapshot()
        if (
            combo_snapshot.get('task_kind') == 'combo'
            and (
                combo_snapshot.get('is_running')
                or combo_snapshot.get('total_count', 0)
                or combo_snapshot.get('message')
            )
        ):
            return {'progress': combo_snapshot}
        return {'progress': self.enrichment_progress.snapshot()}

    def reset_video_enrichments(self, codes, source_key=None):
        self.ensure_database_loaded()
        return {'reset_count': self.db.reset_video_enrichments(codes, source_key=source_key)}

    def list_videos_requiring_manual_category(self):
        self.ensure_database_loaded()
        overview = self.db.list_videos_requiring_manual_category()
        return {
            **dict(overview or {}),
            'videos': self.video_filter_service.filter_video_rows((overview or {}).get('videos', []) or []),
        }

    def stage_video_category(self, code, category):
        self.ensure_database_loaded()
        return self.db.stage_video_category(code, category)

    def stage_video_categories(self, entries):
        self.ensure_database_loaded()
        return self.db.stage_video_categories(entries)

    def sync_staged_video_categories(self):
        self.ensure_database_loaded()
        return self.db.sync_staged_video_categories()

    def update_video_category(self, code, category):
        self.ensure_database_loaded()
        return {'updated_count': self.db.update_video_category(code, category)}

    def list_actors(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_actor_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        rows = list(
            self._list_actors_query(
                search_text,
                sort_field=normalized_sort_field,
                sort_order=normalized_sort_order,
                limit=normalized_limit,
                offset=normalized_offset,
            )
        )
        self._attach_actor_ladder_tiers(rows)
        self._attach_actor_update_status(rows)
        return {
            'actors': rows,
            'total_count': self._count_actors_for_listing(search_text, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def get_actor_detail(self, actor_name):
        self.ensure_database_loaded()
        return {'actor': self.actor_detail_library.get_actor_detail(actor_name)}

    def add_actor(self, actor_name, birthday='', age=''):
        self.ensure_database_loaded()
        return {'created_count': self.library_admin_service.add_actor(actor_name, birthday=birthday, age=age)}

    def list_canglangge_candidates(self, force_refresh=False):
        self.ensure_database_loaded()
        return self._get_canglangge_snapshot(force_refresh=force_refresh)

    def admit_canglangge_candidates(self, actor_names):
        self.ensure_database_loaded()
        admitted_count = 0
        for actor_name in actor_names or []:
            admitted_count += int(self.library_admin_service.add_actor(actor_name, birthday='', age='') or 0)
        self._remove_from_canglangge_snapshot(actor_names)
        return {
            'admitted_count': admitted_count,
            'refreshed_at': self._snapshot_refreshed_at(getattr(self, '_canglangge_snapshot', None)),
        }

    def delete_canglangge_candidates(self, actor_names):
        self.ensure_database_loaded()
        deleted_count = 0
        for actor_name in actor_names or []:
            deleted_count += int(self.db.hide_actor(actor_name) or 0)
        self._remove_from_canglangge_snapshot(actor_names)
        return {
            'deleted_count': deleted_count,
            'refreshed_at': self._snapshot_refreshed_at(getattr(self, '_canglangge_snapshot', None)),
        }

    def reset_actor_enrichments(self, actor_names, source_key=None):
        self.ensure_database_loaded()
        return {'reset_count': self.db.reset_actor_enrichments(actor_names, source_key=source_key)}

    def rename_actor(self, old_name, new_name, birthday='', age=''):
        return {'updated_count': self.library_admin_service.rename_actor(old_name, new_name, birthday=birthday, age=age)}

    def delete_actor(self, actor_name):
        return {'deleted_count': self.library_admin_service.delete_actor(actor_name)}

    def list_code_prefixes(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_code_prefix_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        rows = list(
            self._list_code_prefix_query(
                search_text,
                sort_field=normalized_sort_field,
                sort_order=normalized_sort_order,
                limit=normalized_limit,
                offset=normalized_offset,
            )
        )
        return {
            'prefixes': rows,
            'total_count': self._count_code_prefixes_for_listing(search_text, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def get_code_prefix_detail(self, prefix):
        self.ensure_database_loaded()
        return {'prefix_detail': self.code_prefix_detail_library.get_prefix_detail(prefix)}

    def add_code_prefix(self, prefix):
        self.ensure_database_loaded()
        return {'created_count': self.library_admin_service.add_code_prefix(prefix)}

    def update_code_prefix_uncategorized_video_category(self, prefix, category):
        self.ensure_database_loaded()
        return self.code_prefix_video_category_bulk_service.update_uncategorized_videos(prefix, category)

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        self.ensure_database_loaded()
        return {'reset_count': self.db.reset_code_prefix_enrichments(prefixes, source_key=source_key)}

    def rename_code_prefix(self, old_prefix, new_prefix):
        return {'updated_count': self.library_admin_service.rename_code_prefix(old_prefix, new_prefix)}

    def delete_code_prefix(self, prefix):
        return {'deleted_count': self.library_admin_service.delete_code_prefix(prefix)}

    def get_ladder_board(self, board_key, force_refresh=False):
        self.ensure_database_loaded()
        return self._get_ladder_board_snapshot(board_key, force_refresh=force_refresh)

    def admit_ladder_entry(self, board_key, entity_name, tier):
        self.ensure_database_loaded()
        board = self.ladder_board_service.admit_entry(board_key, entity_name, tier)
        return self._store_ladder_board_snapshot(board_key, board)

    def update_ladder_entry_medal(self, board_key, entity_name, medal):
        self.ensure_database_loaded()
        board = self.ladder_board_service.update_medal(board_key, entity_name, medal)
        return self._store_ladder_board_snapshot(board_key, board)

    def _expand_video_search_candidates_by_ladder_tags(self, search_text, medal_maps=None):
        normalized_search = str(search_text or '').strip().lower()
        if not normalized_search:
            return []

        active_medal_maps = dict(medal_maps or self.video_ladder_tag_service.load_medal_maps())
        actor_names = [
            actor_name
            for actor_name, medals in (active_medal_maps.get('actor_medal_map', {}) or {}).items()
            if any(normalized_search in str(medal or '').strip().lower() for medal in medals or [])
        ]
        prefixes = [
            prefix
            for prefix, medals in (active_medal_maps.get('prefix_medal_map', {}) or {}).items()
            if any(normalized_search in str(medal or '').strip().lower() for medal in medals or [])
        ]

        rows_by_code = {}
        if actor_names and hasattr(self.db, 'list_local_videos_by_actor_names'):
            for row in self.db.list_local_videos_by_actor_names(actor_names):
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})
        if prefixes and hasattr(self.db, 'list_local_videos_by_prefixes'):
            for row in self.db.list_local_videos_by_prefixes(prefixes):
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})
        return list(rows_by_code.values())

    @staticmethod
    def _normalize_sort_order(sort_order):
        return 'desc' if str(sort_order or '').strip().lower() == 'desc' else 'asc'

    @staticmethod
    def _normalize_video_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return normalized if normalized in ('code', 'video_category', 'duration', 'size', 'release_date') else 'code'

    @staticmethod
    def _normalize_actor_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return normalized if normalized in ('name', 'birthday', 'age') else 'name'

    @staticmethod
    def _normalize_code_prefix_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return (
            normalized
            if normalized in ('prefix', 'video_count', 'avfan_total_videos', 'earliest_release_date', 'latest_release_date')
            else 'prefix'
        )

    @staticmethod
    def _normalize_list_limit(limit):
        if limit is None:
            return None
        normalized_limit = int(limit or 0)
        return normalized_limit if normalized_limit > 0 else None

    @staticmethod
    def _normalize_list_offset(offset):
        return max(int(offset or 0), 0)

    @staticmethod
    def _slice_rows(rows, limit=None, offset=0):
        normalized_rows = list(rows or [])
        normalized_offset = max(int(offset or 0), 0)
        if limit is None:
            return normalized_rows[normalized_offset:]
        normalized_limit = max(int(limit or 0), 0)
        return normalized_rows[normalized_offset: normalized_offset + normalized_limit]

    def _list_videos_query(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        try:
            return self.db.list_videos(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.db.list_videos(search_text)

    def _list_actors_query(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        try:
            return self.db.list_actors(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.db.list_actors(search_text)

    def _list_code_prefix_query(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        try:
            return self.code_prefix_library.list_prefixes(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.code_prefix_library.list_prefixes(search_text)

    def _sort_video_rows_for_listing(self, rows, sort_field, sort_order):
        reverse = self._normalize_sort_order(sort_order) == 'desc'

        def _video_sort_key(row):
            current_row = dict(row or {})
            if sort_field == 'release_date':
                return (str(current_row.get('release_date', '') or ''), str(current_row.get('code', '') or ''))
            if sort_field == 'video_category':
                return (str(current_row.get('video_category', '') or ''), str(current_row.get('code', '') or ''))
            if sort_field == 'size':
                return (self._safe_float(current_row.get('size', '')), str(current_row.get('code', '') or ''))
            if sort_field == 'duration':
                return (self._duration_to_seconds(current_row.get('duration', '')), str(current_row.get('code', '') or ''))
            return self._natural_code_key(current_row.get('code', ''))

        return sorted(list(rows or []), key=_video_sort_key, reverse=reverse)

    def _count_videos_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.db, 'count_videos'):
            return int(self.db.count_videos(search_text) or 0)
        return len(list(fallback_rows or []))

    def _count_actors_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.db, 'count_actors'):
            return int(self.db.count_actors(search_text) or 0)
        return len(list(fallback_rows or []))

    def _count_code_prefixes_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.code_prefix_library, 'count_prefixes'):
            return int(self.code_prefix_library.count_prefixes(search_text) or 0)
        return len(list(fallback_rows or []))

    @staticmethod
    def _safe_float(value):
        try:
            return float(str(value or '').strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _duration_to_seconds(value):
        parts = [segment for segment in str(value or '').strip().split(':') if segment != '']
        if len(parts) != 3:
            return 0
        try:
            hours, minutes, seconds = [int(segment) for segment in parts]
        except ValueError:
            return 0
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _natural_code_key(value):
        normalized_value = str(value or '').strip().upper()
        if '-' in normalized_value:
            prefix, suffix = normalized_value.split('-', 1)
            try:
                return prefix, int(suffix), normalized_value
            except ValueError:
                return prefix, 0, normalized_value
        return normalized_value, 0, normalized_value

    def _attach_actor_update_status(self, rows):
        actor_names = [
            str((row or {}).get('name', '') or '').strip()
            for row in (rows or [])
            if str((row or {}).get('name', '') or '').strip()
        ]
        if not actor_names:
            return rows
        filter_settings = None
        if hasattr(self.video_filter_service, 'load_settings'):
            filter_settings = self.video_filter_service.load_settings()

        local_rows = []
        if hasattr(self.db, 'list_local_videos_by_actor_names'):
            try:
                local_rows = list(self.db.list_local_videos_by_actor_names(actor_names, refresh_categories=False))
            except TypeError:
                local_rows = list(self.db.list_local_videos_by_actor_names(actor_names))
        web_movies_by_actor = {}
        if hasattr(self.db, 'list_actor_movies_by_names'):
            web_movies_by_actor = self.db.list_actor_movies_by_names(actor_names)

        local_movies_by_actor = {name: [] for name in actor_names}
        actor_name_set = set(actor_names)
        for row in local_rows:
            current_names = {
                str(name or '').strip()
                for name in split_actor_names((row or {}).get('author', ''))
                if str(name or '').strip()
            }
            for actor_name in actor_name_set.intersection(current_names):
                local_movies_by_actor.setdefault(actor_name, []).append(dict(row or {}))

        for row in rows:
            actor_name = str((row or {}).get('name', '') or '').strip()
            local_movies = local_movies_by_actor.get(actor_name, [])
            web_movies = web_movies_by_actor.get(actor_name, [])
            visible_local_movies = (
                self.video_filter_service.filter_video_rows(local_movies, settings=filter_settings)
                if local_movies
                else []
            )
            eligible_web_movies = [
                movie
                for movie in (
                    self.video_filter_service.filter_video_rows(web_movies, settings=filter_settings)
                    if web_movies
                    else []
                )
                if is_javtxt_eligible_movie(movie)
            ]
            row['update_status'] = resolve_update_status(visible_local_movies + eligible_web_movies)
        return rows

    def _attach_actor_ladder_tiers(self, rows):
        tier_map = {}
        if hasattr(self.db, 'list_ladder_entries'):
            tier_map = {
                str((entry or {}).get('entity_name', '') or '').strip(): str((entry or {}).get('tier', '') or '').strip().upper()
                for entry in self.db.list_ladder_entries(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR)
                if str((entry or {}).get('entity_name', '') or '').strip()
            }
        for row in rows or []:
            actor_name = str((row or {}).get('name', '') or '').strip()
            row['ladder_tier'] = tier_map.get(actor_name, str((row or {}).get('ladder_tier', '') or '').strip().upper())
        return rows

    def list_paths(self, force_refresh=False):
        return self._get_path_library_snapshot(force_refresh=force_refresh)

    def add_path(self, folder_path):
        path_record = self.path_library.build_path_record(folder_path)
        saved_record = self.db.add_path(path_record['path'])
        enriched_record = self.path_library.with_exists_status(saved_record)
        self.db.update_path_storage_info(enriched_record['id'], enriched_record)
        self._append_to_path_snapshot(enriched_record)
        return {'path': enriched_record, 'refreshed_at': self._snapshot_refreshed_at(self._path_library_snapshot)}

    def delete_path(self, path_id):
        if path_id is None:
            raise ValueError('缺少 path_id')
        deleted_count = self.db.delete_path(path_id)
        self._remove_from_path_snapshot(path_id)
        return {'deleted_count': deleted_count, 'refreshed_at': self._snapshot_refreshed_at(self._path_library_snapshot)}

    def _get_ladder_board_snapshot(self, board_key, force_refresh=False):
        normalized_board_key = str(board_key or '').strip()
        with self._snapshot_guard():
            snapshots = getattr(self, '_ladder_board_snapshots', None)
            if not isinstance(snapshots, dict):
                snapshots = {}
                self._ladder_board_snapshots = snapshots
            snapshot = snapshots.get(normalized_board_key)
            if snapshot is None or force_refresh:
                board = self.ladder_board_service.get_board(normalized_board_key)
                snapshot = self._build_snapshot_payload(board=self._clone_ladder_board(board))
                snapshots[normalized_board_key] = snapshot
            return {
                'board': self._clone_ladder_board((snapshot or {}).get('board', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _store_ladder_board_snapshot(self, board_key, board):
        normalized_board_key = str(board_key or '').strip()
        with self._snapshot_guard():
            snapshots = getattr(self, '_ladder_board_snapshots', None)
            if not isinstance(snapshots, dict):
                snapshots = {}
                self._ladder_board_snapshots = snapshots
            snapshot = self._build_snapshot_payload(board=self._clone_ladder_board(board))
            snapshots[normalized_board_key] = snapshot
            return {
                'board': self._clone_ladder_board((snapshot or {}).get('board', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _get_path_library_snapshot(self, force_refresh=False):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None or force_refresh:
                paths = [self.path_library.with_exists_status(row) for row in self.db.list_paths()]
                snapshot = self._build_snapshot_payload(
                    paths=[dict(path or {}) for path in paths],
                    summary=summarize_paths(paths),
                )
                self._path_library_snapshot = snapshot
            return {
                'paths': [dict(path or {}) for path in (snapshot or {}).get('paths', []) or []],
                'summary': dict((snapshot or {}).get('summary', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _append_to_path_snapshot(self, path_record):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None:
                return
            paths = [dict(path or {}) for path in (snapshot or {}).get('paths', []) or []]
            target_id = (path_record or {}).get('id')
            paths = [path for path in paths if path.get('id') != target_id]
            paths.append(dict(path_record or {}))
            paths.sort(
                key=lambda row: (
                    str((row or {}).get('created_at', '') or ''),
                    int((row or {}).get('id', 0) or 0),
                ),
                reverse=True,
            )
            self._path_library_snapshot = self._build_snapshot_payload(
                paths=paths,
                summary=summarize_paths(paths),
            )

    def _remove_from_path_snapshot(self, path_id):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None:
                return
            remaining_paths = [
                dict(path or {})
                for path in (snapshot or {}).get('paths', []) or []
                if (path or {}).get('id') != path_id
            ]
            self._path_library_snapshot = self._build_snapshot_payload(
                paths=remaining_paths,
                summary=summarize_paths(remaining_paths),
            )

    def _get_canglangge_snapshot(self, force_refresh=False):
        with self._snapshot_guard():
            snapshot = getattr(self, '_canglangge_snapshot', None)
            if snapshot is None or force_refresh:
                rows = self.canglangge_candidate_service.list_candidates()
                snapshot = self._build_snapshot_payload(candidates=[dict(row or {}) for row in rows])
                self._canglangge_snapshot = snapshot
            return {
                'candidates': [dict(row or {}) for row in (snapshot or {}).get('candidates', []) or []],
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _remove_from_canglangge_snapshot(self, actor_names):
        with self._snapshot_guard():
            snapshot = getattr(self, '_canglangge_snapshot', None)
            if snapshot is None:
                return
            target_names = {str(actor_name or '').strip() for actor_name in actor_names or [] if str(actor_name or '').strip()}
            remaining_rows = [
                dict(row or {})
                for row in (snapshot or {}).get('candidates', []) or []
                if str((row or {}).get('actor_name', '') or '').strip() not in target_names
            ]
            self._canglangge_snapshot = self._build_snapshot_payload(candidates=remaining_rows)

    def _snapshot_guard(self):
        return getattr(self, '_snapshot_lock', None) or nullcontext()

    def _build_snapshot_payload(self, **fields):
        return {
            **fields,
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    @staticmethod
    def _snapshot_refreshed_at(snapshot):
        return str((snapshot or {}).get('refreshed_at', '') or '').strip()

    @staticmethod
    def _current_snapshot_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _clone_ladder_board(board):
        board = dict(board or {})
        return {
            **board,
            'candidates': [dict(row or {}) for row in board.get('candidates', []) or []],
            'selected': [dict(row or {}) for row in board.get('selected', []) or []],
        }

    def enrich_videos(self, limit, show_browser=False, cooldown_before_search=False, target_type=None, source_key=None):
        self._begin_enrichment_task('single')
        logger = TaskTraceLogger(
            'single',
            self._build_single_task_key(target_type, source_key),
            self._build_single_task_label(target_type, source_key),
        )
        try:
            enrichment_service = LibraryEnrichmentService(
                self.db,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                should_stop=self.enrichment_task_state.cancel_event.is_set,
                progress_tracker=self.enrichment_progress,
                logger=logger,
                video_candidate_filter=self.video_filter_service.build_pre_enrichment_filter(),
            )
            if target_type == ACTOR_LIBRARY_TARGET:
                self.actor_library_sync_service.sync_from_video_library()

            result = enrichment_service.run(target_type, limit, source_key=source_key)
            result['log_path'] = str(logger.log_path)

            if (not target_type or target_type == VIDEO_LIBRARY_TARGET) and result.get('processed_count', 0) > 0:
                self.actor_library_sync_service.sync_from_video_library()

            return result
        except Exception:
            self.enrichment_progress.finish(message='补全任务异常结束。', stopped=True)
            logger.log('ERROR', '单任务补全异常结束', target_type=target_type or '', source_key=source_key or '')
            raise
        finally:
            self._end_enrichment_task()

    def enrich_combo(
        self,
        combo_key,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        combo_task_settings=None,
        batch_mode=False,
    ):
        normalized_combo_key = normalize_combo_key(combo_key)
        combo_label = get_combo_label(normalized_combo_key)
        self._begin_enrichment_task('combo')
        logger = ComboTaskLogger(normalized_combo_key, combo_label)
        try:
            combo_service = ComboEnrichmentService(
                self.db,
                self.combo_progress,
                logger,
                should_stop=self.enrichment_task_state.cancel_event.is_set,
            )
            result = combo_service.run(
                normalized_combo_key,
                limit,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                combo_task_settings=combo_task_settings,
                batch_mode=batch_mode,
            )
            result['log_path'] = str(logger.log_path)
            return result
        except Exception:
            self.combo_progress.finish(message='组合任务异常结束。', stopped=True)
            raise
        finally:
            self._end_enrichment_task()

    def cancel_enrichment(self):
        return self.enrichment_task_state.request_cancel(self._set_cancel_message)

    def auto_login(self):
        return AutoLoginService().run()

    def reset_browser_profile(self):
        return reset_avfan_browser_profile()

    def sync_library_statuses(self):
        self.ensure_database_loaded()
        if self.enrichment_task_state.is_running:
            raise RuntimeError('当前有补全任务正在运行，请稍后再执行状态同步。')
        return self.library_status_sync_service.sync()

    def _begin_enrichment_task(self, task_kind):
        self.enrichment_task_state.begin(
            task_kind,
            reset_progress=lambda: (
                self.enrichment_progress.reset(),
                self.combo_progress.reset(),
            ),
        )

    def _end_enrichment_task(self):
        self.enrichment_task_state.end()

    def _set_cancel_message(self, task_kind):
        if task_kind == 'combo':
            self.combo_progress.set_message('已请求停止组合任务，等待当前条目处理完成。')
            return
        self.enrichment_progress.set_message('已请求停止补全任务，等待当前条目处理完成。')

    @staticmethod
    def _build_single_task_key(target_type, source_key):
        target_text = str(target_type or VIDEO_LIBRARY_TARGET).strip() or VIDEO_LIBRARY_TARGET
        source_text = str(source_key or '').strip()
        if not source_text:
            return target_text
        return f'{target_text}_{source_text}'

    @staticmethod
    def _build_single_task_label(target_type, source_key):
        target_text = str(target_type or VIDEO_LIBRARY_TARGET).strip() or VIDEO_LIBRARY_TARGET
        source_text = str(source_key or '').strip()
        if not source_text:
            return f'单任务 / {target_text}'
        return f'单任务 / {target_text} / {source_text}'
