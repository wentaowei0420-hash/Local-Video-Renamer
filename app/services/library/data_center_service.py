import re
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import perf_counter

from app.core.actor_data_analysis import ACTOR_ANALYSIS_METRIC_MAP
from app.core.code_prefix_data_analysis import CODE_PREFIX_ANALYSIS_METRIC_MAP
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
    get_video_enrichment_source_label,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_entry_state import JAVTXT_SEARCH_STATE_NO_RESULT, classify_search_state
from app.core.supplement_task_state import build_supplement_candidate
from app.core.javtxt_video_state import is_javtxt_eligible_movie, summarize_javtxt_movies
from app.core.video_code import standardize_video_code
from app.services.library import CodePrefixLibrary, build_merged_movie_snapshot, extract_code_prefix
from app.services.video import VIDEO_CATEGORY_COLLECTION, VideoFilterService


VIDEO_LIBRARY_LABEL = '\u89c6\u9891\u5e93'
CODE_PREFIX_LIBRARY_LABEL = '\u756a\u53f7\u5e93'
ACTOR_LIBRARY_LABEL = '\u6f14\u5458\u5e93'
COMPLETED_LABEL = '\u5df2\u5b8c\u6210'
COMPLETED_VIDEO_LABEL = '\u5df2\u5b8c\u6210\u89c6\u9891'
PENDING_VIDEO_LABEL = '\u5f85\u8865\u5168\u89c6\u9891'
NO_SEARCH_LABEL = '\u65e0\u7ed3\u679c'
NO_DETAIL_LABEL = '\u65e0\u8be6\u60c5'
MISSING_AGE_LABEL = '\u65e0\u5e74\u9f84'
MISSING_MEASUREMENTS_LABEL = '\u65e0\u4e09\u56f4'
MISSING_HEIGHT_LABEL = '\u65e0\u8eab\u9ad8'


class DataCenterService:
    SNAPSHOT_VERSION = 1
    ANALYSIS_SNAPSHOT_VERSION = 1
    EXPECTED_SUMMARY_SOURCE_KEYS = {
        'video_library': (AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE, SUPPLEMENT_TASK_SOURCE),
        'code_prefix_library': (AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE, SUPPLEMENT_TASK_SOURCE),
        'actor_library': (
            AVFAN_VIDEO_SOURCE,
            JAVTXT_VIDEO_SOURCE,
            BINGHUO_ACTOR_SOURCE,
            BAOMU_ACTOR_SOURCE,
            SUPPLEMENT_TASK_SOURCE,
        ),
    }

    def __init__(self, database, video_filter_service=None, snapshot_file=None, refresh_logger=None):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)
        self.video_filter_service = video_filter_service or VideoFilterService()
        self.snapshot_file = Path(snapshot_file) if snapshot_file else None
        self.refresh_logger = refresh_logger
        self._snapshot_filter_fingerprint = self._build_filter_settings_fingerprint(self._load_filter_settings())
        self._summary_cache = None
        self._summary_cache_refreshed_at = ''
        self._summary_cache_refresh_duration_ms = 0
        self._summary_cache_refresh_duration_text = ''
        self._summary_cache_lock = Lock()
        self._analysis_cache = {}
        self._analysis_cache_lock = Lock()
        self._snapshot_file_lock = Lock()
        self._load_persisted_snapshots()

    def get_summary(self, force_refresh=False):
        return self.get_summary_snapshot(force_refresh=force_refresh)['summary']

    def get_summary_snapshot(self, force_refresh=False):
        with self._summary_cache_lock:
            filter_settings = self._refresh_filter_settings_state()
            if self._is_complete_summary_snapshot(self._summary_cache) and not force_refresh:
                return {
                    'summary': dict(self._summary_cache or {}),
                    'refreshed_at': self._summary_cache_refreshed_at,
                    'refresh_duration_ms': self._summary_cache_refresh_duration_ms,
                    'refresh_duration_text': self._summary_cache_refresh_duration_text,
                }
            if not force_refresh:
                self._summary_cache = None
                self._summary_cache_refreshed_at = ''
                self._summary_cache_refresh_duration_ms = 0
                self._summary_cache_refresh_duration_text = ''

            started_at = perf_counter()
            summary = self._build_summary(filter_settings=filter_settings)
            refresh_duration_ms = self._build_duration_ms(started_at)
            self._summary_cache = summary
            self._summary_cache_refreshed_at = self._current_cache_timestamp()
            self._summary_cache_refresh_duration_ms = refresh_duration_ms
            self._summary_cache_refresh_duration_text = self._format_duration_text(refresh_duration_ms)
            self._persist_snapshots()
            self._log_refresh(
                snapshot_key='data_center',
                refreshed_at=self._summary_cache_refreshed_at,
                refresh_duration_ms=refresh_duration_ms,
                cache_kind='summary',
            )
            return {
                'summary': dict(summary or {}),
                'refreshed_at': self._summary_cache_refreshed_at,
                'refresh_duration_ms': self._summary_cache_refresh_duration_ms,
                'refresh_duration_text': self._summary_cache_refresh_duration_text,
            }

    def get_actor_metric_analysis(self, metric_key, force_refresh=False):
        return self.get_actor_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)['analysis']

    def get_actor_metric_analysis_snapshot(self, metric_key, force_refresh=False):
        config = self._get_actor_metric_config(metric_key)
        cache_key = self._build_analysis_cache_key('actor', config['key'])
        with self._analysis_cache_lock:
            self._refresh_filter_settings_state()
            cached = self._analysis_cache.get(cache_key)
            if cached is not None and not force_refresh:
                return dict(cached)

            payload = {
                'analysis': self._build_actor_metric_analysis(config),
                'refreshed_at': self._current_cache_timestamp(),
            }
            self._analysis_cache[cache_key] = payload
            self._persist_snapshots()
            return dict(payload)

    def get_actor_metric_bucket_snapshot(self, metric_key, bucket_value, force_refresh=False):
        config = self._get_actor_metric_config(metric_key)
        normalized_bucket_value = self._normalize_actor_metric_bucket_value(config, bucket_value)
        if normalized_bucket_value in (None, ''):
            raise ValueError(f'Unknown actor metric bucket value: {bucket_value}')

        cache_key = self._build_analysis_cache_key(
            'actor_bucket',
            f'{config["key"]}:{normalized_bucket_value}',
        )
        with self._analysis_cache_lock:
            self._refresh_filter_settings_state()
            cached = self._analysis_cache.get(cache_key)
            if cached is not None and not force_refresh:
                return dict(cached)

            payload = {
                'metric_key': config['key'],
                'bucket_value': normalized_bucket_value,
                'bucket_label': self._format_actor_metric_bucket_label(config, normalized_bucket_value),
                'actors': self._build_actor_metric_bucket(config, normalized_bucket_value),
                'refreshed_at': self._current_cache_timestamp(),
            }
            self._analysis_cache[cache_key] = payload
            self._persist_snapshots()
            return dict(payload)

    def get_code_prefix_metric_analysis(self, metric_key, force_refresh=False):
        return self.get_code_prefix_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)['analysis']

    def get_code_prefix_metric_analysis_snapshot(self, metric_key, force_refresh=False):
        config = self._get_code_prefix_metric_config(metric_key)
        cache_key = self._build_analysis_cache_key('code_prefix', config['key'])
        with self._analysis_cache_lock:
            self._refresh_filter_settings_state()
            cached = self._analysis_cache.get(cache_key)
            if cached is not None and not force_refresh:
                return dict(cached)

            payload = {
                'analysis': self._build_code_prefix_metric_analysis(config),
                'refreshed_at': self._current_cache_timestamp(),
            }
            self._analysis_cache[cache_key] = payload
            self._persist_snapshots()
            return dict(payload)

    def _load_persisted_snapshots(self):
        if self.snapshot_file is None:
            return
        try:
            if not self.snapshot_file.exists():
                return
            payload = json.loads(self.snapshot_file.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return

        if not isinstance(payload, dict):
            return
        if int(payload.get('version', 0) or 0) != self.SNAPSHOT_VERSION:
            return
        persisted_fingerprint = str(payload.get('filter_settings_fingerprint', '') or '').strip()
        should_migrate_legacy_snapshot = not persisted_fingerprint
        if persisted_fingerprint and persisted_fingerprint != self._snapshot_filter_fingerprint:
            return

        summary_snapshot = self._normalize_summary_snapshot(payload.get('summary_snapshot'))
        if summary_snapshot is not None and self._is_complete_summary_snapshot(summary_snapshot.get('summary', {})):
            self._summary_cache = summary_snapshot.get('summary', {})
            self._summary_cache_refreshed_at = str(summary_snapshot.get('refreshed_at', '') or '').strip()
            self._summary_cache_refresh_duration_ms = int(summary_snapshot.get('refresh_duration_ms', 0) or 0)
            self._summary_cache_refresh_duration_text = str(
                summary_snapshot.get('refresh_duration_text', '') or ''
            ).strip()

        analysis_snapshot_version = int(payload.get('analysis_snapshot_version', 0) or 0)
        if analysis_snapshot_version == self.ANALYSIS_SNAPSHOT_VERSION:
            analysis_snapshots = payload.get('analysis_snapshots', {})
            if not isinstance(analysis_snapshots, dict):
                return

            normalized_analysis_snapshots = {}
            for cache_key, snapshot in analysis_snapshots.items():
                normalized_snapshot = self._normalize_analysis_snapshot(snapshot)
                if normalized_snapshot is None:
                    continue
                normalized_analysis_snapshots[str(cache_key or '').strip()] = normalized_snapshot
            self._analysis_cache = normalized_analysis_snapshots
        else:
            self._analysis_cache = {}
        if should_migrate_legacy_snapshot and (self._summary_cache is not None or self._analysis_cache):
            self._persist_snapshots()

    def _persist_snapshots(self):
        if self.snapshot_file is None:
            return
        payload = {
            'version': self.SNAPSHOT_VERSION,
            'analysis_snapshot_version': self.ANALYSIS_SNAPSHOT_VERSION,
            'filter_settings_fingerprint': self._snapshot_filter_fingerprint,
            'summary_snapshot': self._build_persisted_summary_snapshot(),
            'analysis_snapshots': self._build_persisted_analysis_snapshots(),
        }
        temp_snapshot_file = self.snapshot_file.with_suffix(self.snapshot_file.suffix + '.tmp')

        try:
            with self._snapshot_file_lock:
                self.snapshot_file.parent.mkdir(parents=True, exist_ok=True)
                temp_snapshot_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_snapshot_file.replace(self.snapshot_file)
        except OSError:
            return

    def _build_persisted_summary_snapshot(self):
        if self._summary_cache is None:
            return {}
        return {
            'summary': dict(self._summary_cache or {}),
            'refreshed_at': self._summary_cache_refreshed_at,
            'refresh_duration_ms': int(self._summary_cache_refresh_duration_ms or 0),
            'refresh_duration_text': str(self._summary_cache_refresh_duration_text or '').strip(),
        }

    def _build_persisted_analysis_snapshots(self):
        snapshots = {}
        for cache_key, payload in dict(self._analysis_cache or {}).items():
            normalized_key = str(cache_key or '').strip()
            normalized_payload = self._normalize_analysis_snapshot(payload)
            if not normalized_key or normalized_payload is None:
                continue
            snapshots[normalized_key] = normalized_payload
        return snapshots

    @staticmethod
    def _normalize_summary_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        summary = snapshot.get('summary')
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        if not isinstance(summary, dict):
            return None
        return {
            'summary': dict(summary or {}),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': int(snapshot.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(snapshot.get('refresh_duration_text', '') or '').strip(),
        }

    def _log_refresh(self, snapshot_key, refreshed_at, refresh_duration_ms, cache_kind=''):
        logger = getattr(self, 'refresh_logger', None)
        if not callable(logger):
            return
        try:
            logger(
                snapshot_key=str(snapshot_key or '').strip() or 'data_center',
                refreshed_at=str(refreshed_at or '').strip(),
                refresh_duration_ms=int(refresh_duration_ms or 0),
                refresh_duration_text=self._format_duration_text(refresh_duration_ms),
                cache_kind=str(cache_kind or '').strip(),
            )
        except Exception:
            return

    @staticmethod
    def _build_duration_ms(started_at):
        return max(0, int(round((perf_counter() - float(started_at or 0.0)) * 1000)))

    @staticmethod
    def _format_duration_text(duration_ms):
        total_seconds = max(0, int(round((int(duration_ms or 0) / 1000.0))))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours}小时{minutes}分{seconds}秒'
        if minutes > 0:
            return f'{minutes}分{seconds}秒'
        return f'{seconds}秒'

    @classmethod
    def _is_complete_summary_snapshot(cls, summary):
        if not isinstance(summary, dict):
            return False
        for library_key, source_keys in cls.EXPECTED_SUMMARY_SOURCE_KEYS.items():
            library_summary = summary.get(library_key, {})
            if not isinstance(library_summary, dict):
                return False
            sources = library_summary.get('sources', {})
            if not isinstance(sources, dict):
                return False
            for source_key in source_keys:
                source_summary = sources.get(source_key)
                if not isinstance(source_summary, dict) or not source_summary:
                    return False
        return True

    @staticmethod
    def _normalize_analysis_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        normalized_snapshot = {
            str(key or '').strip(): value
            for key, value in dict(snapshot or {}).items()
            if str(key or '').strip()
        }
        if not normalized_snapshot or not refreshed_at:
            return None
        normalized_snapshot['refreshed_at'] = refreshed_at
        return normalized_snapshot

    def _build_summary(self, filter_settings=None):
        return {
            'video_library': {
                'label': VIDEO_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_video_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_video_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    SUPPLEMENT_TASK_SOURCE: self._build_video_supplement_summary(
                        filter_settings=filter_settings,
                    ),
                },
            },
            'code_prefix_library': {
                'label': CODE_PREFIX_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    SUPPLEMENT_TASK_SOURCE: self._build_code_prefix_supplement_summary(
                        filter_settings=filter_settings,
                    ),
                },
            },
            'actor_library': {
                'label': ACTOR_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_actor_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_actor_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    BINGHUO_ACTOR_SOURCE: self._build_actor_source_summary(
                        BINGHUO_ACTOR_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    BAOMU_ACTOR_SOURCE: self._build_actor_source_summary(
                        BAOMU_ACTOR_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    SUPPLEMENT_TASK_SOURCE: self._build_actor_supplement_summary(
                        filter_settings=filter_settings,
                    ),
                },
            },
        }

    def _build_video_source_summary(self, source_key, filter_settings=None):
        label = self._build_source_label(VIDEO_LIBRARY_LABEL, source_key)
        visible_rows = self._list_visible_video_summary_rows(filter_settings=filter_settings)
        if source_key == JAVTXT_VIDEO_SOURCE:
            summary = summarize_javtxt_movies(visible_rows)
            return {
                'label': label,
                'total_count': summary['total_count'],
                'enriched_count': summary['enriched_count'],
                'success_count': summary['success_count'],
                'pending_count': summary['pending_count'],
                'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
                'count_label': COMPLETED_LABEL,
                'failed_count': summary['failed_count'],
                'no_search_count': summary['no_search_count'],
                'no_detail_count': summary['no_detail_count'],
                'list_kind': 'video',
                'issue_groups': self._build_javtxt_video_issue_groups(visible_rows),
            }
        return self._build_video_status_summary(label, visible_rows, 'avfan_enrichment_status')

    def _build_video_status_summary(self, label, rows, status_field):
        statuses = [str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS for row in rows or []]
        summary = self._build_status_summary(label, statuses)
        summary['count_label'] = COMPLETED_LABEL
        summary['list_kind'] = 'video'
        summary['issue_groups'] = self._build_status_issue_groups(
            rows,
            lambda row: self._build_video_issue_item(row),
            lambda row: str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS,
        )
        return summary

    def _build_video_supplement_summary(self, filter_settings=None):
        pending_rows = [
            row
            for row in self._list_visible_video_summary_rows(filter_settings=filter_settings)
            if build_supplement_candidate(row, filter_settings=filter_settings)
        ]
        return self._build_pending_only_summary(
            self._build_source_label(VIDEO_LIBRARY_LABEL, SUPPLEMENT_TASK_SOURCE),
            pending_rows,
            list_kind='video',
            item_builder=self._build_video_issue_item,
        )

    def _build_code_prefix_source_summary(self, source_key, filter_settings=None):
        if source_key == JAVTXT_VIDEO_SOURCE:
            prefixes = [
                str(row.get('prefix', '')).strip().upper()
                for row in self.code_prefix_library.list_prefixes()
                if str(row.get('prefix', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key),
                self.database.list_code_prefix_movies_by_prefixes(prefixes),
                filter_settings=filter_settings,
                list_kind='video',
            )

        records = self.database.list_code_prefix_enrichment_records()
        prefix_rows = [row for row in self.code_prefix_library.list_prefixes() if row.get('prefix')]
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in prefix_rows
        ]
        summary = self._build_status_summary(self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key), statuses)
        summary['list_kind'] = 'code_prefix'
        summary['issue_groups'] = self._build_status_issue_groups(
            prefix_rows,
            lambda row: self._build_code_prefix_issue_item(row.get('prefix', '')),
            lambda row: self._get_source_status(records.get(row.get('prefix', ''), {}), source_key),
        )
        return summary

    def _build_code_prefix_supplement_summary(self, filter_settings=None):
        prefixes = [
            str(row.get('prefix', '') or '').strip().upper()
            for row in self.code_prefix_library.list_prefixes()
            if str(row.get('prefix', '') or '').strip()
        ]
        movies_by_prefix = self.database.list_code_prefix_movies_by_prefixes(prefixes) if prefixes else {}
        filtered_movies_by_prefix = self._filter_grouped_movies(
            movies_by_prefix,
            filter_settings=filter_settings,
        )
        merged_movies = self._merge_movies_by_code(
            [
                movie
                for movies in filtered_movies_by_prefix.values()
                for movie in (movies or [])
            ]
        )
        pending_movies = [
            movie for movie in merged_movies if build_supplement_candidate(movie, filter_settings=filter_settings)
        ]
        return self._build_pending_only_summary(
            self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, SUPPLEMENT_TASK_SOURCE),
            pending_movies,
            list_kind='video',
            item_builder=self._build_video_issue_item,
        )

    def _build_actor_source_summary(self, source_key, filter_settings=None):
        if source_key == BINGHUO_ACTOR_SOURCE:
            return self._build_actor_binghuo_source_summary()
        if source_key == JAVTXT_VIDEO_SOURCE:
            actor_names = [
                str(row.get('name', '')).strip()
                for row in self.database.list_actors()
                if str(row.get('name', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(ACTOR_LIBRARY_LABEL, source_key),
                self.database.list_actor_movies_by_names(actor_names),
                filter_settings=filter_settings,
                list_kind='video',
            )

        records = self.database.list_actor_enrichment_records()
        actor_rows = [row for row in self.database.list_actors() if str(row.get('name', '')).strip()]
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in actor_rows
        ]
        summary = self._build_status_summary(self._build_source_label(ACTOR_LIBRARY_LABEL, source_key), statuses)
        summary['list_kind'] = 'actor'
        summary['issue_groups'] = self._build_status_issue_groups(
            actor_rows,
            lambda row: self._build_actor_issue_item(row.get('name', '')),
            lambda row: self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key),
        )
        return summary

    def _build_actor_supplement_summary(self, filter_settings=None):
        actor_names = [
            str(row.get('name', '') or '').strip()
            for row in self.database.list_actors()
            if str(row.get('name', '') or '').strip()
        ]
        movies_by_actor = self.database.list_actor_movies_by_names(actor_names) if actor_names else {}
        filtered_movies_by_actor = self._filter_grouped_movies(
            movies_by_actor,
            filter_settings=filter_settings,
        )
        merged_movies = self._merge_movies_by_code(
            [
                movie
                for movies in filtered_movies_by_actor.values()
                for movie in (movies or [])
            ]
        )
        pending_movies = [
            movie for movie in merged_movies if build_supplement_candidate(movie, filter_settings=filter_settings)
        ]
        return self._build_pending_only_summary(
            self._build_source_label(ACTOR_LIBRARY_LABEL, SUPPLEMENT_TASK_SOURCE),
            pending_movies,
            list_kind='video',
            item_builder=self._build_video_issue_item,
        )

    def _build_actor_binghuo_source_summary(self):
        records = self.database.list_actor_enrichment_records()
        total_count = 0
        success_count = 0
        failed_count = 0
        no_search_count = 0
        no_detail_count = 0
        missing_age_count = 0
        missing_measurements_count = 0
        missing_height_count = 0
        no_search_items = []
        missing_age_items = []
        missing_measurements_items = []
        missing_height_items = []

        for row in self.database.list_actors():
            actor_name = str((row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            total_count += 1
            record = records.get(actor_name, {})
            status = str((record or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            if status == NO_SEARCH_RESULTS_STATUS:
                no_search_count += 1
                no_search_items.append(self._build_actor_issue_item(actor_name))
            elif status == NO_VIDEO_DETAIL_STATUS or self._is_incomplete_binghuo_profile(record):
                no_detail_count += 1
                if self._is_missing_binghuo_age(record):
                    missing_age_count += 1
                    missing_age_items.append(self._build_actor_issue_item(actor_name))
                if self._is_missing_binghuo_measurements(record):
                    missing_measurements_count += 1
                    missing_measurements_items.append(self._build_actor_issue_item(actor_name))
                if self._is_missing_binghuo_height(record):
                    missing_height_count += 1
                    missing_height_items.append(self._build_actor_issue_item(actor_name))
            elif self._is_complete_binghuo_profile(record):
                success_count += 1
            elif status == FAILED_STATUS:
                failed_count += 1

        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': self._build_source_label(ACTOR_LIBRARY_LABEL, BINGHUO_ACTOR_SOURCE),
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'missing_age_count': missing_age_count,
            'missing_measurements_count': missing_measurements_count,
            'missing_height_count': missing_height_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': COMPLETED_LABEL,
            'list_kind': 'actor',
            'issue_groups': self._compact_issue_groups(
                [
                    self._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                    self._build_issue_group('missing_age', MISSING_AGE_LABEL, missing_age_items),
                    self._build_issue_group(
                        'missing_measurements',
                        MISSING_MEASUREMENTS_LABEL,
                        missing_measurements_items,
                    ),
                    self._build_issue_group('missing_height', MISSING_HEIGHT_LABEL, missing_height_items),
                ]
            ),
        }

    def _build_status_summary(self, label, statuses):
        total_count = len(statuses)
        success_count = sum(1 for status in statuses if status == ENRICHED_STATUS)
        failed_count = sum(1 for status in statuses if status == FAILED_STATUS)
        no_search_count = sum(1 for status in statuses if status == NO_SEARCH_RESULTS_STATUS)
        no_detail_count = sum(1 for status in statuses if status == NO_VIDEO_DETAIL_STATUS)
        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': COMPLETED_LABEL,
        }

    def _build_javtxt_library_video_summary(self, label, movies_by_group, filter_settings=None, list_kind='video'):
        filtered_movies_by_group = self._filter_grouped_movies(
            movies_by_group,
            filter_settings=filter_settings,
        )
        visible_movies = [
            movie
            for movies in filtered_movies_by_group.values()
            for movie in (movies or [])
        ]
        merged_movies = self._merge_movies_by_code(visible_movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in merged_movies]
        )
        summary = summarize_javtxt_movies(merged_movies, cache_rows=cache_rows)
        return {
            'label': label,
            'total_count': summary['total_count'],
            'enriched_count': summary['enriched_count'],
            'success_count': summary['success_count'],
            'pending_count': summary['pending_count'],
            'failed_count': summary['failed_count'],
            'no_search_count': summary['no_search_count'],
            'no_detail_count': summary['no_detail_count'],
            'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
            'count_label': COMPLETED_VIDEO_LABEL,
            'pending_label': PENDING_VIDEO_LABEL,
            'list_kind': list_kind,
            'issue_groups': self._build_javtxt_issue_groups_by_kind(
                merged_movies if str(list_kind or '').strip() == 'video' else filtered_movies_by_group,
                filter_settings=filter_settings,
                list_kind=list_kind,
                movies_already_filtered=True,
                movies_already_merged=str(list_kind or '').strip() == 'video',
            ),
        }

    def _load_filter_settings(self):
        if self.video_filter_service is None:
            return None
        return self.video_filter_service.load_settings()

    def _refresh_filter_settings_state(self):
        filter_settings = self._load_filter_settings()
        current_fingerprint = self._build_filter_settings_fingerprint(filter_settings)
        if current_fingerprint != self._snapshot_filter_fingerprint:
            self._snapshot_filter_fingerprint = current_fingerprint
            self._summary_cache = None
            self._summary_cache_refreshed_at = ''
            self._summary_cache_refresh_duration_ms = 0
            self._summary_cache_refresh_duration_text = ''
            self._analysis_cache = {}
        return filter_settings

    @staticmethod
    def _build_filter_settings_fingerprint(filter_settings):
        normalized_settings = filter_settings if isinstance(filter_settings, dict) else {}
        return json.dumps(normalized_settings, ensure_ascii=False, sort_keys=True)

    def _build_actor_metric_analysis(self, config):
        distribution_counts = {}
        ranking_rows = []
        unknown_count = 0
        enrichment_records = self.database.list_actor_enrichment_records()

        for actor_row in self.database.list_actors():
            actor_name = str((actor_row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            numeric_value, display_value = self._resolve_actor_metric_value(
                config,
                actor_row,
                enrichment_records.get(actor_name, {}),
            )
            if numeric_value is None:
                unknown_count += 1
                continue
            distribution_counts[display_value] = distribution_counts.get(display_value, 0) + 1
            ranking_rows.append(
                {
                    'actor_name': actor_name,
                    'display_value': display_value,
                    'numeric_value': numeric_value,
                }
            )

        distribution_rows = [
            {'label': label, 'count': count}
            for label, count in sorted(
                distribution_counts.items(),
                key=lambda item: (-self._parse_metric_number(item[0]), item[0]),
            )
        ]
        if unknown_count > 0:
            distribution_rows.append({'label': '无数据', 'count': unknown_count})

        ranking_rows.sort(key=lambda item: (-item['numeric_value'], item['actor_name']))
        return {
            'metric_key': config['key'],
            'distribution_rows': distribution_rows,
            'ranking_rows': ranking_rows[:50],
        }

    def _build_code_prefix_metric_analysis(self, config):
        if config.get('key') != 'collection_ratio':
            raise ValueError(f"Unknown code prefix analysis metric: {config.get('key', '')}")

        filter_settings = self._load_filter_settings()
        code_prefixes = [
            str((row or {}).get('prefix', '') or '').strip().upper()
            for row in self.code_prefix_library.list_prefixes()
            if str((row or {}).get('prefix', '') or '').strip()
        ]
        code_prefix_movies_by_prefix = self.database.list_code_prefix_movies_by_prefixes(code_prefixes) if code_prefixes else {}
        actor_movies_by_prefix = self._group_actor_movies_for_code_prefix_analysis()
        prefixes = sorted(set(code_prefixes) | set(actor_movies_by_prefix))
        distribution_counts = {percent: 0 for percent in range(1, 101)}
        ranking_rows = []

        for prefix in prefixes:
            merged_movies = self._merge_movies_by_code(
                [
                    *list(code_prefix_movies_by_prefix.get(prefix, []) or []),
                    *list(actor_movies_by_prefix.get(prefix, []) or []),
                ]
            )
            visible_movies = self._filter_visible_movies(merged_movies, filter_settings=filter_settings)
            total_count = len(visible_movies)
            if total_count <= 0:
                continue

            collection_count = sum(
                1
                for movie in visible_movies
                if str((movie or {}).get('video_category', '') or '').strip() == VIDEO_CATEGORY_COLLECTION
            )
            ratio_percent = self._round_half_up((float(collection_count) / float(total_count)) * 100.0, digits=1)
            rounded_percent = int(self._round_half_up(ratio_percent, digits=0))
            if rounded_percent >= 1:
                distribution_counts[min(rounded_percent, 100)] += 1
            ranking_rows.append(
                {
                    'prefix': prefix,
                    'label': prefix,
                    'display_value': f'{ratio_percent:.1f}% ({collection_count}/{total_count})',
                    'numeric_value': ratio_percent,
                    'collection_count': collection_count,
                    'total_count': total_count,
                }
            )

        ranking_rows.sort(
            key=lambda item: (
                -float(item.get('numeric_value', 0.0) or 0.0),
                -int(item.get('collection_count', 0) or 0),
                str(item.get('prefix', '') or ''),
            )
        )
        return {
            'metric_key': config['key'],
            'distribution_rows': [
                {'label': f'{percent}%', 'count': distribution_counts[percent]}
                for percent in range(1, 101)
            ],
            'ranking_rows': ranking_rows[:50],
            'distribution_items_per_line': 6,
            'ranking_items_per_line': 6,
        }

    def _build_actor_metric_analysis(self, config):
        metric_rows, unknown_count = self._collect_actor_metric_rows(config)
        if self._is_categorical_actor_metric(config):
            distribution_by_value = {}
            for row in metric_rows:
                bucket_value = str(row.get('bucket_value', '') or '').strip()
                if bucket_value not in distribution_by_value:
                    distribution_by_value[bucket_value] = {
                        'label': str(row.get('display_value', '') or '').strip(),
                        'count': 0,
                        'bucket_value': bucket_value,
                    }
                distribution_by_value[bucket_value]['count'] += 1

            distribution_rows = [
                distribution_by_value[bucket_value]
                for bucket_value in sorted(
                    distribution_by_value.keys(),
                    key=self._categorical_metric_sort_key,
                    reverse=str(config.get('sort_order', 'asc') or '').strip().lower() == 'desc',
                )
            ]
            if unknown_count > 0:
                distribution_rows.append({'label': '\u65e0\u6570\u636e', 'count': unknown_count})

            return {
                'metric_key': config['key'],
                'distribution_rows': distribution_rows,
                'ranking_rows': [],
            }

        distribution_by_value = {}
        for row in metric_rows:
            numeric_value = int(row.get('numeric_value', 0) or 0)
            if numeric_value not in distribution_by_value:
                distribution_by_value[numeric_value] = {
                    'label': str(row.get('display_value', '') or '').strip(),
                    'count': 0,
                    'bucket_value': numeric_value,
                }
            distribution_by_value[numeric_value]['count'] += 1

        distribution_rows = [
            distribution_by_value[numeric_value]
            for numeric_value in sorted(distribution_by_value.keys(), reverse=True)
        ]
        if unknown_count > 0:
            distribution_rows.append({'label': '\u65e0\u6570\u636e', 'count': unknown_count})

        ranking_rows = sorted(
            metric_rows,
            key=lambda item: (-item['numeric_value'], item['actor_name']),
        )
        return {
            'metric_key': config['key'],
            'distribution_rows': distribution_rows,
            'ranking_rows': ranking_rows[:50],
        }

    def _build_actor_metric_bucket(self, config, bucket_value):
        metric_rows, _unknown_count = self._collect_actor_metric_rows(config)
        if self._is_categorical_actor_metric(config):
            normalized_bucket_value = str(bucket_value or '').strip().upper()
            return [
                {
                    'actor_name': str(row.get('actor_name', '') or '').strip(),
                    'display_value': str(row.get('display_value', '') or '').strip(),
                    'bucket_value': str(row.get('bucket_value', '') or '').strip(),
                }
                for row in sorted(
                    metric_rows,
                    key=lambda item: str(item.get('actor_name', '') or '').strip(),
                )
                if str(row.get('bucket_value', '') or '').strip().upper() == normalized_bucket_value
            ]

        normalized_bucket_value = int(bucket_value or 0)
        return [
            {
                'actor_name': str(row.get('actor_name', '') or '').strip(),
                'display_value': str(row.get('display_value', '') or '').strip(),
                'numeric_value': int(row.get('numeric_value', 0) or 0),
            }
            for row in sorted(
                metric_rows,
                key=lambda item: (item.get('numeric_value', 0), item.get('actor_name', '')),
            )
            if int(row.get('numeric_value', 0) or 0) == normalized_bucket_value
        ]

    def _collect_actor_metric_rows(self, config):
        metric_rows = []
        unknown_count = 0
        enrichment_records = self.database.list_actor_enrichment_records()

        for actor_row in self.database.list_actors():
            actor_name = str((actor_row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            metric_row = self._resolve_actor_metric_row(
                config,
                actor_row,
                enrichment_records.get(actor_name, {}),
            )
            if metric_row is None:
                unknown_count += 1
                continue
            metric_rows.append(metric_row)

        return metric_rows, unknown_count

    @staticmethod
    def _resolve_actor_metric_raw_value(config, actor_row, enrichment_record):
        source_name = str(config.get('source', '') or '').strip()
        field_name = str(config.get('field', '') or '').strip()
        if source_name == 'enrichment':
            raw_value = str((enrichment_record or {}).get(field_name, '') or '').strip()
            fallback_field = str(config.get('fallback_field', '') or '').strip()
            if not raw_value and fallback_field:
                raw_value = str((enrichment_record or {}).get(fallback_field, '') or '').strip()
        else:
            raw_value = str(
                (actor_row or {}).get(f'raw_{field_name}', (actor_row or {}).get(field_name, '')) or ''
            ).strip()
        return raw_value

    @classmethod
    def _resolve_actor_metric_row(cls, config, actor_row, enrichment_record):
        actor_name = str((actor_row or {}).get('name', '') or '').strip()
        raw_value = cls._resolve_actor_metric_raw_value(config, actor_row, enrichment_record)
        if cls._is_categorical_actor_metric(config):
            bucket_value = cls._parse_metric_text_bucket(raw_value)
            if not bucket_value:
                return None
            return {
                'actor_name': actor_name,
                'display_value': bucket_value,
                'bucket_value': bucket_value,
            }

        suffix = str(config.get('suffix', '') or '')
        numeric_value = DataCenterService._parse_metric_number(raw_value)
        if numeric_value is None:
            return None
        return {
            'actor_name': actor_name,
            'display_value': f'{numeric_value}{suffix}',
            'numeric_value': numeric_value,
        }

    @staticmethod
    def _is_categorical_actor_metric(config):
        return str((config or {}).get('value_type', '') or '').strip().lower() == 'categorical'

    @classmethod
    def _normalize_actor_metric_bucket_value(cls, config, bucket_value):
        if cls._is_categorical_actor_metric(config):
            return cls._parse_metric_text_bucket(bucket_value)
        return cls._parse_metric_number(bucket_value)

    @staticmethod
    def _format_actor_metric_bucket_label(config, bucket_value):
        if DataCenterService._is_categorical_actor_metric(config):
            return str(bucket_value or '').strip()
        return f'{bucket_value}{str(config.get("suffix", "") or "")}'

    @staticmethod
    def _parse_metric_text_bucket(value):
        match = re.search(r'[A-Z]+', str(value or '').strip().upper())
        if not match:
            return ''
        return match.group(0)

    @staticmethod
    def _categorical_metric_sort_key(value):
        text = str(value or '').strip().upper()
        return (len(text), text)

    @staticmethod
    def _parse_metric_number(value):
        match = re.search(r'\d+', str(value or '').strip())
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _has_binghuo_physical_data(record):
        current = dict(record or {})
        return any(
            str(current.get(field_name, '') or '').strip()
            for field_name in ('binghuo_height', 'binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @staticmethod
    def _is_missing_binghuo_age(record):
        current = dict(record or {})
        return not str(current.get('binghuo_age', '') or '').strip()

    @staticmethod
    def _is_missing_binghuo_height(record):
        current = dict(record or {})
        return not str(current.get('binghuo_height', '') or '').strip()

    @staticmethod
    def _is_missing_binghuo_measurements(record):
        current = dict(record or {})
        return any(
            not str(current.get(field_name, '') or '').strip()
            for field_name in ('binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @classmethod
    def _is_complete_binghuo_profile(cls, record):
        current = dict(record or {})
        birthday = str(current.get('binghuo_birthday', '') or '').strip()
        return bool(birthday) and cls._has_binghuo_physical_data(current)

    @classmethod
    def _is_incomplete_binghuo_profile(cls, record):
        current = dict(record or {})
        has_any_profile_data = any(
            str(current.get(field_name, '') or '').strip()
            for field_name in (
                'binghuo_birthday',
                'binghuo_age',
                'binghuo_height',
                'binghuo_bust',
                'binghuo_waist',
                'binghuo_hip',
            )
        )
        return has_any_profile_data and not cls._is_complete_binghuo_profile(current)

    @staticmethod
    def _current_cache_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _get_actor_metric_config(metric_key):
        normalized_key = str(metric_key or '').strip()
        config = ACTOR_ANALYSIS_METRIC_MAP.get(normalized_key)
        if config is None:
            raise ValueError(f'Unknown actor analysis metric: {normalized_key}')
        return dict(config)

    @staticmethod
    def _get_code_prefix_metric_config(metric_key):
        normalized_key = str(metric_key or '').strip()
        config = CODE_PREFIX_ANALYSIS_METRIC_MAP.get(normalized_key)
        if config is None:
            raise ValueError(f'Unknown code prefix analysis metric: {normalized_key}')
        return dict(config)

    @staticmethod
    def _build_analysis_cache_key(analysis_type, metric_key):
        return f'{str(analysis_type or "").strip()}:{str(metric_key or "").strip()}'

    def _list_visible_video_summary_rows(self, filter_settings=None):
        return self._filter_visible_movies(
            self.database.list_video_summary_rows(),
            filter_settings=filter_settings,
        )

    def _filter_visible_movies(self, rows, filter_settings=None):
        if not rows:
            return []
        if self.video_filter_service is None:
            return list(rows or [])
        return self.video_filter_service.filter_video_rows(rows, settings=filter_settings)

    def _filter_grouped_movies(self, movies_by_group, filter_settings=None):
        filtered_movies_by_group = {}
        for group_key, movies in (movies_by_group or {}).items():
            visible_movies = self._filter_visible_movies(movies or [], filter_settings=filter_settings)
            if visible_movies:
                filtered_movies_by_group[group_key] = visible_movies
        return filtered_movies_by_group

    def _group_actor_movies_for_code_prefix_analysis(self):
        if not hasattr(self.database, 'list_all_actor_movies'):
            return {}
        grouped_movies = {}
        for row in self.database.list_all_actor_movies():
            prefix = extract_code_prefix((row or {}).get('code', ''))
            if not prefix:
                continue
            grouped_movies.setdefault(prefix, []).append(dict(row or {}))
        return grouped_movies

    @staticmethod
    def _build_source_label(library_label, source_key):
        return f'{library_label} \u00b7 {get_video_enrichment_source_label(source_key)}'

    @staticmethod
    def _merge_movies_by_code(movies):
        movies_by_code = {}
        for movie in movies or []:
            normalized_code = standardize_video_code((movie or {}).get('code', ''))
            if not normalized_code:
                continue
            movies_by_code.setdefault(normalized_code, []).append(dict(movie or {}))

        merged_movies = []
        for normalized_code, rows in movies_by_code.items():
            merged_snapshot = build_merged_movie_snapshot(normalized_code, rows)
            if merged_snapshot:
                merged_movies.append(merged_snapshot)
            else:
                merged_movies.append(dict(rows[0] or {}))
        return merged_movies

    @staticmethod
    def _get_source_status(record, source_key):
        if source_key == JAVTXT_VIDEO_SOURCE:
            key = 'javtxt_enrichment_status'
        elif source_key == BINGHUO_ACTOR_SOURCE:
            key = 'binghuo_enrichment_status'
        elif source_key == BAOMU_ACTOR_SOURCE:
            key = 'baomu_enrichment_status'
        else:
            key = 'avfan_enrichment_status'
        return str((record or {}).get(key, '') or '').strip() or UNENRICHED_STATUS

    @staticmethod
    def _build_issue_group(key, label, items):
        normalized_items = [dict(item or {}) for item in items or [] if dict(item or {})]
        if not normalized_items:
            return {}
        return {
            'key': str(key or '').strip(),
            'label': str(label or '').strip(),
            'items': normalized_items,
        }

    @classmethod
    def _compact_issue_groups(cls, groups):
        return [group for group in (groups or []) if dict(group or {}).get('items')]

    @staticmethod
    def _build_video_issue_item(row):
        current = dict(row or {})
        return {
            'code': str(current.get('code', '') or '').strip(),
            'title': str(current.get('title', '') or '').strip(),
            'author': str(
                current.get('author', '')
                or current.get('local_author', '')
                or current.get('author_raw', '')
                or ''
            ).strip(),
        }

    @staticmethod
    def _build_code_prefix_issue_item(prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return {}
        return {'prefix': normalized_prefix}

    @staticmethod
    def _build_actor_issue_item(actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return {}
        return {'name': normalized_name}

    @classmethod
    def _build_status_issue_groups(cls, rows, item_builder, status_builder):
        no_search_items = []
        no_detail_items = []
        for row in rows or []:
            status = str(status_builder(row) or '').strip() or UNENRICHED_STATUS
            item = dict(item_builder(row) or {})
            if not item:
                continue
            if status == NO_SEARCH_RESULTS_STATUS:
                no_search_items.append(item)
            elif status == NO_VIDEO_DETAIL_STATUS:
                no_detail_items.append(item)
        return cls._compact_issue_groups(
            [
                cls._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                cls._build_issue_group('no_detail', NO_DETAIL_LABEL, no_detail_items),
            ]
        )

    def _build_javtxt_video_issue_groups(
        self,
        movies,
        filter_settings=None,
        movies_already_filtered=False,
        movies_already_merged=False,
    ):
        issue_items = {
            'no_search': [],
            'no_detail': [],
        }
        local_rows_by_code = {
            standardize_video_code((row or {}).get('code', '')): dict(row or {})
            for row in self._list_visible_video_summary_rows(filter_settings=filter_settings)
            if standardize_video_code((row or {}).get('code', ''))
        }
        visible_movies = list(movies or []) if movies_already_filtered else self._filter_visible_movies(
            movies or [],
            filter_settings=filter_settings,
        )
        merged_movies = list(visible_movies or []) if movies_already_merged else self._merge_movies_by_code(visible_movies)
        for movie in merged_movies:
            issue_key = self._classify_javtxt_issue_key(movie)
            if not issue_key:
                continue
            issue_items[issue_key].append(
                self._build_video_issue_item(
                    self._merge_issue_movie_with_local_row(
                        movie,
                        local_rows_by_code.get(standardize_video_code((movie or {}).get('code', '')), {}),
                    )
                )
            )
        return self._compact_issue_groups(
            [
                self._build_issue_group('no_search', NO_SEARCH_LABEL, issue_items['no_search']),
                self._build_issue_group('no_detail', NO_DETAIL_LABEL, issue_items['no_detail']),
            ]
        )

    def _build_javtxt_issue_groups_by_kind(
        self,
        movies_by_group,
        filter_settings=None,
        list_kind='video',
        movies_already_filtered=False,
        movies_already_merged=False,
    ):
        if str(list_kind or '').strip() == 'video':
            flat_movies = list(movies_by_group or []) if movies_already_merged else [
                movie
                for movies in (movies_by_group or {}).values()
                for movie in (movies or [])
            ]
            return self._build_javtxt_video_issue_groups(
                flat_movies,
                filter_settings=filter_settings,
                movies_already_filtered=movies_already_filtered,
                movies_already_merged=movies_already_merged,
            )

        no_search_items = []
        no_detail_items = []
        for group_key, movies in (movies_by_group or {}).items():
            visible_movies = list(movies or []) if movies_already_filtered else self._filter_visible_movies(
                movies or [],
                filter_settings=filter_settings,
            )
            merged_visible_movies = self._merge_movies_by_code(visible_movies)
            if not merged_visible_movies:
                continue
            issue_keys = {self._classify_javtxt_issue_key(movie) for movie in merged_visible_movies}
            if str(list_kind or '').strip() == 'code_prefix':
                item = self._build_code_prefix_issue_item(group_key)
            else:
                item = self._build_actor_issue_item(group_key)
            if not item:
                continue
            if 'no_search' in issue_keys:
                no_search_items.append(item)
            if 'no_detail' in issue_keys:
                no_detail_items.append(item)

        return self._compact_issue_groups(
            [
                self._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                self._build_issue_group('no_detail', NO_DETAIL_LABEL, no_detail_items),
            ]
        )

    @classmethod
    def _build_pending_only_summary(cls, label, rows, list_kind, item_builder):
        pending_items = []
        for row in rows or []:
            item = dict(item_builder(row) or {})
            if item:
                pending_items.append(item)
        pending_count = len(pending_items)
        return {
            'label': label,
            'total_count': pending_count,
            'completed_count': 0,
            'success_count': 0,
            'pending_count': pending_count,
            'failed_count': 0,
            'no_search_count': 0,
            'no_detail_count': 0,
            'progress_percent': 0.0,
            'count_label': '待补充',
            'pending_label': '待补充',
            'list_kind': list_kind,
            'issue_groups': cls._compact_issue_groups(
                [
                    cls._build_issue_group('pending', '待补充', pending_items),
                ]
            ),
        }

    @staticmethod
    def _classify_javtxt_issue_key(movie):
        if not is_javtxt_eligible_movie(movie):
            return ''
        if classify_search_state(movie) != JAVTXT_SEARCH_STATE_NO_RESULT:
            return ''
        status = str((movie or {}).get('javtxt_enrichment_status', '') or '').strip()
        if status == NO_VIDEO_DETAIL_STATUS:
            return 'no_detail'
        if status == NO_SEARCH_RESULTS_STATUS:
            return 'no_search'
        return 'no_search'

    @staticmethod
    def _merge_issue_movie_with_local_row(movie, local_row):
        merged_movie = dict(movie or {})
        current_local_row = dict(local_row or {})
        for field_name in ('title', 'author', 'author_raw', 'local_author'):
            if str(merged_movie.get(field_name, '') or '').strip():
                continue
            merged_movie[field_name] = current_local_row.get(field_name, '')
        return merged_movie

    @staticmethod
    def _round_half_up(value, digits=0):
        exponent = '1' if int(digits or 0) <= 0 else '1.' + ('0' * int(digits or 0))
        return float(Decimal(str(value)).quantize(Decimal(exponent), rounding=ROUND_HALF_UP))


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
