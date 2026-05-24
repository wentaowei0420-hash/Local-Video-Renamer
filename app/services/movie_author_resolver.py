import re
from datetime import date, datetime

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.scraper.javtxt_scraper import JavtxtScraper


JAVTXT_AUTHOR_MIN_RELEASE_DATE = date(2020, 1, 1)
TERMINAL_JAVTXT_VIDEO_STATUSES = {
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
}


class MovieAuthorResolver:
    def __init__(self, database, scraper=None, headless=True, should_stop=None):
        self.database = database
        self.scraper = scraper or JavtxtScraper(headless=headless)
        self.should_stop = should_stop or (lambda: False)
        self._author_cache = {}
        self._status_cache = {}

    def session(self):
        return self.scraper.session()

    def enrich_entries(self, entries):
        return self.enrich_entries_with_details(entries).get('entries', [])

    def enrich_entries_with_details(self, entries, max_lookup_count=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = self._load_cached_rows(normalized_entries)
        pending_video_count_before = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        requested_lookup_count = pending_video_count_before
        if max_lookup_count is not None:
            requested_lookup_count = min(
                pending_video_count_before,
                max(0, int(max_lookup_count or 0)),
            )

        processed_video_count = 0
        success_video_count = 0
        failed_video_count = 0

        for entry in normalized_entries:
            if processed_video_count >= requested_lookup_count:
                break
            if self.should_stop():
                break
            if not self._should_attempt_lookup(entry, cached_rows):
                continue

            code = self._normalize_code(entry.get('code', ''))
            if not code:
                continue
            resolution = self._resolve_author_result(code, cached_rows.get(code, {}))
            processed_video_count += 1

            author = normalize_second_source_actor_text(resolution.get('author', ''))
            if author:
                entry['author'] = author
                success_video_count += 1
            else:
                failed_video_count += 1

            cached_rows[code] = {
                'code': code,
                'javtxt_actors': author,
                'javtxt_enrichment_status': resolution.get('status', UNENRICHED_STATUS),
            }

        pending_video_count_after = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        return {
            'entries': normalized_entries,
            'processed_video_count': processed_video_count,
            'success_video_count': success_video_count,
            'failed_video_count': failed_video_count,
            'pending_video_count': pending_video_count_after,
            'requested_video_count': requested_lookup_count,
            'completed': pending_video_count_after <= 0,
        }

    def count_pending_entries(self, entries, cached_rows=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = cached_rows if cached_rows is not None else self._load_cached_rows(normalized_entries)
        pending_count = 0
        for entry in normalized_entries:
            if self._should_attempt_lookup(entry, cached_rows):
                pending_count += 1
        return pending_count

    def _normalize_entry(self, entry):
        updated = dict(entry or {})
        updated['author'] = normalize_second_source_actor_text(updated.get('author', ''))
        return updated

    def _prepare_entries(self, entries):
        normalized_entries = [self._normalize_entry(entry) for entry in (entries or [])]
        normalized_entries.sort(key=self._lookup_order_key)
        return normalized_entries

    def _load_cached_rows(self, entries):
        eligible_codes = [
            self._normalize_code(entry.get('code', ''))
            for entry in entries
            if self._should_lookup_author(entry)
        ]
        return self.database.get_javtxt_actor_cache_by_codes(eligible_codes)

    def _should_attempt_lookup(self, entry, cached_rows):
        if not self._should_lookup_author(entry):
            return False
        if self._has_author(entry):
            return False

        code = self._normalize_code(entry.get('code', ''))
        if not code:
            return False

        cached_row = cached_rows.get(code, {})
        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        if cached_author:
            entry['author'] = cached_author
            return False

        cached_status = self._normalize_video_status((cached_row or {}).get('javtxt_enrichment_status', ''))
        return cached_status == UNENRICHED_STATUS

    @staticmethod
    def _has_author(entry):
        return bool(normalize_second_source_actor_text((entry or {}).get('author', '')))

    def _resolve_author_result(self, code, cached_row):
        if code in self._author_cache or code in self._status_cache:
            return {
                'author': self._author_cache.get(code, ''),
                'status': self._status_cache.get(code, UNENRICHED_STATUS),
            }

        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        cached_status = self._normalize_video_status((cached_row or {}).get('javtxt_enrichment_status', ''))
        if cached_author:
            self._author_cache[code] = cached_author
            self._status_cache[code] = ENRICHED_STATUS
            return {
                'author': cached_author,
                'status': ENRICHED_STATUS,
            }
        if cached_status in TERMINAL_JAVTXT_VIDEO_STATUSES and cached_status != UNENRICHED_STATUS:
            self._author_cache[code] = ''
            self._status_cache[code] = cached_status
            return {
                'author': '',
                'status': cached_status,
            }

        author = ''
        status = UNENRICHED_STATUS
        error_message = ''
        info = {}
        try:
            info = self.scraper.fetch_by_code(code)
            if info.get('found'):
                author = normalize_second_source_actor_text(info.get('author', ''))
                status = ENRICHED_STATUS if author else NO_SEARCH_RESULTS_STATUS
                if not author:
                    error_message = 'JAVTXT 未返回演员信息'
            else:
                status = NO_SEARCH_RESULTS_STATUS
                error_message = str(info.get('error', '') or 'JAVTXT 未找到匹配结果')
        except Exception as exc:
            status = FAILED_STATUS
            error_message = str(exc)

        self._author_cache[code] = author
        self._status_cache[code] = status
        self._save_video_cache(code, info, status=status, error=error_message)
        return {
            'author': author,
            'status': status,
        }

    def _save_video_cache(self, code, info, status=ENRICHED_STATUS, error=''):
        if self.database is None or not hasattr(self.database, 'save_javtxt_cache_for_video'):
            return
        try:
            self.database.save_javtxt_cache_for_video(
                code,
                info,
                status=status,
                error=error,
            )
        except Exception:
            return

    def _should_lookup_author(self, entry):
        code = self._normalize_code((entry or {}).get('code', ''))
        if not code:
            return False
        release_date = self._parse_release_date((entry or {}).get('release_date', ''))
        if release_date is None:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE

    @staticmethod
    def _parse_release_date(value):
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, '%Y-%m-%d').date()
        except ValueError:
            return None

    @staticmethod
    def _normalize_code(value):
        return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

    @staticmethod
    def _normalize_video_status(value):
        text = str(value or '').strip()
        return text or UNENRICHED_STATUS

    def _lookup_order_key(self, entry):
        normalized_code = self._normalize_code((entry or {}).get('code', ''))
        prefix_part = re.match(r'[A-Z]+', normalized_code or '')
        number_match = re.search(r'(\d+)', normalized_code or '')
        prefix_text = prefix_part.group(0) if prefix_part else normalized_code
        number_value = int(number_match.group(1)) if number_match else 10 ** 12
        return (prefix_text, number_value, normalized_code)
