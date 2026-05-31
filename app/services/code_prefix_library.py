import re

from app.core.video_code import standardize_video_code
from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS


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
    def __init__(self, database):
        self.database = database

    def list_prefixes(self, search_text=''):
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
        grouped = {}

        for row in rows:
            prefix = extract_code_prefix(row.get('code', ''))
            if not prefix or prefix in hidden_prefixes:
                continue
            grouped[prefix] = grouped.get(prefix, 0) + 1

        search = str(search_text or '').strip().upper()
        prefixes = [prefix for prefix in sorted(grouped) if not search or search in prefix]
        movies_by_prefix = self.database.list_code_prefix_movies_by_prefixes(prefixes)

        results = []
        for prefix in prefixes:

            enrichment = enrichment_records.get(prefix, {})
            movies = movies_by_prefix.get(prefix, [])
            earliest_release_date, latest_release_date = self._collect_date_range(movies)
            enrichment_status = self._build_live_enrichment_status(enrichment)

            results.append({
                'prefix': prefix,
                'video_count': grouped[prefix],
                'enrichment_status': enrichment_status,
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
