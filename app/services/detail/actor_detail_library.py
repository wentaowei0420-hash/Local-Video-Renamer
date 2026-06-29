import re

from app.core.ladder_board import LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR
from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.actor_profile_display import normalize_actor_age_for_display, normalize_actor_birthday_for_display
from app.core.video_code import standardize_video_code
from app.services.detail import build_actor_detail_web_url, build_video_category_distribution, resolve_update_status
from app.services.identity import split_actor_names
from app.services.library import extract_code_prefix


YEAR_RE = re.compile(r'(19|20)\d{2}')


class ActorDetailLibrary:
    def __init__(self, database, video_ladder_tag_service=None, video_filter_service=None):
        self.database = database
        self.video_ladder_tag_service = video_ladder_tag_service
        self.video_filter_service = video_filter_service

    def get_actor_detail(self, actor_name):
        actor_name = str(actor_name or '').strip()
        if not actor_name:
            raise ValueError('缺少演员姓名')

        actor_row = self._find_actor(actor_name)
        medal_maps = self._load_medal_maps()
        raw_local_videos = self._find_local_actor_videos(actor_name, medal_maps=medal_maps)
        local_videos = self._filter_visible_movies(raw_local_videos)
        raw_web_movies = self._enrich_rows(self.database.list_actor_movies(actor_name), medal_maps=medal_maps)
        web_movies = self._filter_visible_movies(self._filter_eligible_movies(raw_web_movies))
        eligible_web_movies = list(web_movies)
        web_record = self.database.get_actor_enrichment_record(actor_name)
        web_earliest, web_latest = self._collect_date_range(web_movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in web_movies]
        )
        web_summary = summarize_javtxt_movies(web_movies, cache_rows=cache_rows)
        merged_birthday = self._merge_actor_birthday(actor_row, web_record)
        birthday = normalize_actor_birthday_for_display(merged_birthday)
        ladder_entry = self.database.get_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, actor_name)

        actor_id = actor_row.get('actor_id', '') or web_record.get('actor_id', '')
        appearance_prefixes = self._collect_unique_prefixes(local_videos + eligible_web_movies)
        return {
            'name': actor_name,
            'birthday': birthday,
            'age': normalize_actor_age_for_display(actor_row.get('age', ''), birthday),
            'matched': bool(actor_row.get('matched')),
            'actor_id': actor_id,
            'binghuo_person_id': str((web_record or {}).get('binghuo_person_id', '') or '').strip(),
            'binghuo_height': self._merged_profile_value(web_record, 'binghuo_height', 'baomu_height'),
            'binghuo_bust': self._merged_profile_value(web_record, 'binghuo_bust', 'baomu_bust'),
            'binghuo_cup': self._merged_profile_value(web_record, 'binghuo_cup', 'baomu_cup'),
            'binghuo_waist': self._merged_profile_value(web_record, 'binghuo_waist', 'baomu_waist'),
            'binghuo_hip': self._merged_profile_value(web_record, 'binghuo_hip', 'baomu_hip'),
            'baomu_birthday': str((web_record or {}).get('baomu_birthday', '') or '').strip(),
            'baomu_height': str((web_record or {}).get('baomu_height', '') or '').strip(),
            'baomu_bust': str((web_record or {}).get('baomu_bust', '') or '').strip(),
            'baomu_cup': str((web_record or {}).get('baomu_cup', '') or '').strip(),
            'baomu_waist': str((web_record or {}).get('baomu_waist', '') or '').strip(),
            'baomu_hip': str((web_record or {}).get('baomu_hip', '') or '').strip(),
            'baomu_enrichment_status': str((web_record or {}).get('baomu_enrichment_status', '') or '').strip(),
            'web_url': build_actor_detail_web_url(actor_name, actor_id=actor_id),
            'ladder_tier': str((ladder_entry or {}).get('tier', '') or '').strip().upper(),
            'update_status': resolve_update_status(local_videos + eligible_web_movies),
            'local_video_count': len(local_videos),
            'appearance_code_count': len(appearance_prefixes),
            'code_prefix_library_count': self._count_prefixes_in_library(appearance_prefixes),
            'local_prefix_distribution': self._build_prefix_distribution(local_videos),
            'local_year_distribution': self._build_year_distribution(local_videos),
            'web_enrichment_status': self._build_live_web_enrichment_status(web_record, web_movies, cache_rows),
            'web_total_pages': web_record.get('avfan_total_pages', 0),
            'web_total_videos': web_record.get('avfan_total_videos', 0),
            'eligible_video_count': len(eligible_web_movies),
            'eligible_enriched_video_count': web_summary['enriched_count'],
            'web_last_enriched_at': web_record.get('last_enriched_at', ''),
            'web_earliest_release_date': web_earliest,
            'web_latest_release_date': web_latest,
            'web_prefix_distribution': self._build_prefix_distribution(eligible_web_movies),
            'web_year_distribution': self._build_year_distribution(eligible_web_movies),
            'web_video_category_distribution': build_video_category_distribution(eligible_web_movies),
            'local_videos': local_videos,
            'web_movies': web_movies,
            'eligible_web_movies': eligible_web_movies,
            'raw_web_movie_count': len(raw_web_movies),
        }

    def _find_actor(self, actor_name):
        for row in self.database.list_actors(actor_name):
            if str(row.get('name', '')).strip() == actor_name:
                return row
        return {
            'name': actor_name,
            'birthday': '',
            'age': '',
            'matched': False,
        }

    def _find_local_actor_videos(self, actor_name, medal_maps=None):
        if hasattr(self.database, 'list_local_videos_by_actor_name'):
            try:
                local_rows = self.database.list_local_videos_by_actor_name(actor_name, refresh_categories=False)
            except TypeError:
                local_rows = self.database.list_local_videos_by_actor_name(actor_name)
            return self._enrich_rows(
                local_rows,
                medal_maps=medal_maps,
            )
        matched = []
        for row in self._enrich_rows(self.database.list_videos(), medal_maps=medal_maps):
            actor_names = split_actor_names(row.get('author', ''))
            if actor_name in actor_names:
                matched.append(row)
        return matched

    def _load_medal_maps(self):
        if self.video_ladder_tag_service is None:
            return None
        return self.video_ladder_tag_service.load_medal_maps()

    def _enrich_rows(self, rows, medal_maps=None):
        if self.video_ladder_tag_service is None:
            return list(rows or [])
        return self.video_ladder_tag_service.enrich_video_rows(rows, medal_maps=medal_maps)

    def _filter_eligible_movies(self, rows):
        return [row for row in (rows or []) if self._is_eligible_movie(row)]

    def _filter_visible_movies(self, rows):
        if self.video_filter_service is None:
            return list(rows or [])
        return self.video_filter_service.filter_video_rows(rows)

    def _build_live_web_enrichment_status(self, enrichment, movies, cache_rows):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '')).strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '')).strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(movies, cache_rows=cache_rows)
        binghuo_status = str((enrichment or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        baomu_status = str((enrichment or {}).get('baomu_enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        return build_library_enrichment_status_text(avfan_status, javtxt_status, binghuo_status, baomu_status)

    @staticmethod
    def _merge_actor_birthday(actor_row, web_record):
        return str(
            (actor_row or {}).get('birthday', '')
            or (web_record or {}).get('binghuo_birthday', '')
            or (web_record or {}).get('baomu_birthday', '')
            or ''
        ).strip()

    @staticmethod
    def _merged_profile_value(web_record, primary_key, fallback_key):
        return str((web_record or {}).get(primary_key, '') or (web_record or {}).get(fallback_key, '') or '').strip()

    def _build_prefix_distribution(self, rows):
        grouped = {}
        for row in rows:
            prefix = extract_code_prefix(row.get('code', '')) or '未知'
            grouped[prefix] = grouped.get(prefix, 0) + 1

        return [
            {'prefix': prefix, 'video_count': count}
            for prefix, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _build_year_distribution(self, rows):
        grouped = {}
        for row in rows:
            year = self._extract_year(row.get('release_date', ''))
            grouped[year] = grouped.get(year, 0) + 1

        known_items = [(year, count) for year, count in grouped.items() if year != '未知']
        unknown_items = [(year, count) for year, count in grouped.items() if year == '未知']
        known_items.sort(key=lambda item: (-int(item[0]), -item[1], item[0]))
        ordered = known_items + unknown_items
        return [{'year': year, 'video_count': count} for year, count in ordered]

    def _collect_date_range(self, rows):
        dates = sorted(
            str(row.get('release_date', '')).strip()
            for row in rows
            if str(row.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    @staticmethod
    def _extract_year(release_date_text):
        text = str(release_date_text or '').strip()
        match = YEAR_RE.search(text)
        if not match:
            return '未知'
        return match.group(0)

    @staticmethod
    def _is_eligible_movie(movie):
        return is_javtxt_eligible_movie(movie)

    @staticmethod
    def _collect_unique_prefixes(rows):
        return {
            normalized_prefix
            for normalized_prefix in (
                extract_code_prefix(standardize_video_code((row or {}).get('code', '')))
                for row in (rows or [])
            )
            if normalized_prefix
        }

    def _count_prefixes_in_library(self, prefixes):
        if not hasattr(self.database, 'list_code_prefix_enrichment_records'):
            return 0
        available_prefixes = {
            str(prefix or '').strip().upper()
            for prefix in (self.database.list_code_prefix_enrichment_records() or {}).keys()
            if str(prefix or '').strip()
        }
        return sum(1 for prefix in (prefixes or set()) if prefix in available_prefixes)
