import re

from app.core.video_code import standardize_video_code
from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.ladder_board import LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX
from app.services.detail import resolve_update_status


SEPARATED_PREFIX_RE = re.compile(r'^\s*([A-Za-z0-9]+?)[\s_-]+\d', re.IGNORECASE)
LEADING_ALPHA_PREFIX_RE = re.compile(r'^\s*([A-Za-z]+)\d', re.IGNORECASE)


def extract_code_prefix(code):
    text = standardize_video_code(code)
    if not text:
        return ''

    match = SEPARATED_PREFIX_RE.match(text)
    if match:
        prefix = re.sub(r'[^A-Z0-9]', '', match.group(1).upper())
        return prefix if any(ch.isalpha() for ch in prefix) else ''

    match = LEADING_ALPHA_PREFIX_RE.match(text)
    if match:
        return match.group(1).upper()

    prefix_chars = []
    for char in text:
        if char.isdigit():
            break
        if char.isalnum():
            prefix_chars.append(char)

    prefix = ''.join(prefix_chars)
    return prefix if any(ch.isalpha() for ch in prefix) else ''


class CodePrefixLibrary:
    def __init__(self, database, video_filter_service=None):
        self.database = database
        self.video_filter_service = video_filter_service

    def list_prefixes(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        if hasattr(self.database, 'list_code_prefix_summaries'):
            try:
                return self._list_prefixes_from_summaries(
                    search_text,
                    sort_field=sort_field,
                    sort_order=sort_order,
                    limit=limit,
                    offset=offset,
                )
            except TypeError:
                pass
        return self._list_prefixes_legacy(search_text)

    def count_prefixes(self, search_text=''):
        if hasattr(self.database, 'count_code_prefixes'):
            try:
                return int(self.database.count_code_prefixes(search_text) or 0)
            except TypeError:
                pass
        return len(self._list_prefixes_legacy(search_text))

    def _list_prefixes_from_summaries(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        ladder_tier_map = self._load_ladder_tier_map()
        summary_rows = list(
            self.database.list_code_prefix_summaries(
                search_text=search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        )
        prefixes = [
            str((row or {}).get('prefix', '') or '').strip().upper()
            for row in summary_rows
            if str((row or {}).get('prefix', '') or '').strip()
        ]
        local_rows_by_prefix = {prefix: [] for prefix in prefixes}
        if prefixes and hasattr(self.database, 'list_local_videos_by_prefixes'):
            try:
                local_source_rows = self.database.list_local_videos_by_prefixes(prefixes, refresh_categories=False)
            except TypeError:
                local_source_rows = self.database.list_local_videos_by_prefixes(prefixes)
            for row in local_source_rows:
                prefix = extract_code_prefix((row or {}).get('code', ''))
                if prefix in local_rows_by_prefix:
                    local_rows_by_prefix.setdefault(prefix, []).append(dict(row or {}))
        movies_by_prefix = self.database.list_code_prefix_movies_by_prefixes(prefixes) if prefixes else {}

        results = []
        for row in summary_rows:
            prefix = str((row or {}).get('prefix', '') or '').strip().upper()
            if not prefix:
                continue
            visible_local_rows = self._filter_visible_rows(local_rows_by_prefix.get(prefix, []))
            eligible_movies = [
                dict(movie or {})
                for movie in self._filter_visible_rows(movies_by_prefix.get(prefix, []))
                if is_javtxt_eligible_movie(movie)
            ]
            avfan_status = str((row or {}).get('avfan_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            javtxt_status = str((row or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            results.append(
                {
                    'prefix': prefix,
                    'ladder_tier': ladder_tier_map.get(prefix, ''),
                    'video_count': int((row or {}).get('video_count', 0) or 0),
                    'enrichment_status': build_library_enrichment_status_text(avfan_status, javtxt_status),
                    'avfan_enrichment_status': avfan_status,
                    'javtxt_enrichment_status': javtxt_status,
                    'update_status': resolve_update_status(visible_local_rows + eligible_movies),
                    'avfan_total_pages': int((row or {}).get('avfan_total_pages', 0) or 0),
                    'avfan_total_videos': int((row or {}).get('avfan_total_videos', 0) or 0),
                    'earliest_release_date': str((row or {}).get('earliest_release_date', '') or ''),
                    'latest_release_date': str((row or {}).get('latest_release_date', '') or ''),
                    'last_enriched_at': str((row or {}).get('last_enriched_at', '') or ''),
                }
            )
        return results

    def _list_prefixes_legacy(self, search_text=''):
        rows = self.database.list_videos()
        enrichment_records = {}
        hidden_prefixes = set()
        if hasattr(self.database, 'list_code_prefix_enrichment_records'):
            try:
                enrichment_records = self.database.list_code_prefix_enrichment_records()
            except Exception:
                enrichment_records = {}
        if hasattr(self.database, 'list_hidden_code_prefixes'):
            try:
                hidden_prefixes = self.database.list_hidden_code_prefixes()
            except Exception:
                hidden_prefixes = set()
        ladder_tier_map = self._load_ladder_tier_map()
        grouped = {}
        local_rows_by_prefix = {}

        for row in rows:
            prefix = extract_code_prefix(row.get('code', ''))
            if not prefix or prefix in hidden_prefixes:
                continue
            grouped[prefix] = grouped.get(prefix, 0) + 1
            local_rows_by_prefix.setdefault(prefix, []).append(dict(row or {}))

        search = str(search_text or '').strip().upper()
        all_prefixes = set(grouped)
        all_prefixes.update(
            prefix
            for prefix in enrichment_records
            if str(prefix or '').strip().upper() and str(prefix or '').strip().upper() not in hidden_prefixes
        )
        prefixes = [prefix for prefix in sorted(all_prefixes) if not search or search in prefix]
        movies_by_prefix = self.database.list_code_prefix_movies_by_prefixes(prefixes)

        results = []
        for prefix in prefixes:

            enrichment = enrichment_records.get(prefix, {})
            movies = movies_by_prefix.get(prefix, [])
            earliest_release_date, latest_release_date = self._collect_date_range(movies)
            enrichment_status = self._build_live_enrichment_status(enrichment)
            visible_local_rows = self._filter_visible_rows(local_rows_by_prefix.get(prefix, []))
            eligible_movies = [
                dict(movie or {})
                for movie in self._filter_visible_rows(movies)
                if is_javtxt_eligible_movie(movie)
            ]

            results.append({
                'prefix': prefix,
                'ladder_tier': ladder_tier_map.get(prefix, ''),
                'video_count': grouped.get(prefix, 0),
                'enrichment_status': enrichment_status,
                'avfan_enrichment_status': str((enrichment or {}).get('avfan_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                'javtxt_enrichment_status': str((enrichment or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                'update_status': resolve_update_status(visible_local_rows + eligible_movies),
                'avfan_total_pages': enrichment.get('avfan_total_pages', 0),
                'avfan_total_videos': enrichment.get('avfan_total_videos', 0),
                'earliest_release_date': earliest_release_date,
                'latest_release_date': latest_release_date,
                'last_enriched_at': enrichment.get('last_enriched_at', ''),
            })

        return results

    @staticmethod
    def _collect_date_range(movies):
        dates = sorted(
            str(movie.get('release_date', '')).strip()
            for movie in movies
            if str(movie.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    def _build_live_enrichment_status(self, enrichment):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '') or '').strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        return build_library_enrichment_status_text(avfan_status, javtxt_record_status)

    def _filter_visible_rows(self, rows):
        if self.video_filter_service is None:
            return list(rows or [])
        return self.video_filter_service.filter_video_rows(rows)

    def _load_ladder_tier_map(self):
        if not hasattr(self.database, 'list_ladder_entries'):
            return {}
        return {
            str((entry or {}).get('entity_name', '') or '').strip().upper(): str((entry or {}).get('tier', '') or '').strip().upper()
            for entry in self.database.list_ladder_entries(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX)
            if str((entry or {}).get('entity_name', '') or '').strip()
        }
