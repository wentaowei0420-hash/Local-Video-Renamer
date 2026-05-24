import re
from datetime import date, datetime

from app.scraper.javtxt_scraper import JavtxtScraper


JAVTXT_AUTHOR_MIN_RELEASE_DATE = date(2020, 1, 1)


class MovieAuthorResolver:
    def __init__(self, database, scraper=None, headless=True, should_stop=None):
        self.database = database
        self.scraper = scraper or JavtxtScraper(headless=headless)
        self.should_stop = should_stop or (lambda: False)
        self._author_cache = {}

    def session(self):
        return self.scraper.session()

    def enrich_entries(self, entries):
        normalized_entries = [self._reset_author(entry) for entry in (entries or [])]
        eligible_codes = [
            self._normalize_code(entry.get('code', ''))
            for entry in normalized_entries
            if self._should_lookup_author(entry)
        ]
        cached_rows = self.database.get_javtxt_actor_cache_by_codes(eligible_codes)

        for entry in normalized_entries:
            if not self._should_lookup_author(entry):
                continue
            if self.should_stop():
                break
            code = self._normalize_code(entry.get('code', ''))
            if not code:
                continue
            entry['author'] = self._resolve_author(code, cached_rows.get(code, {}))

        return normalized_entries

    @staticmethod
    def _reset_author(entry):
        updated = dict(entry or {})
        updated['author'] = ''
        return updated

    def _resolve_author(self, code, cached_row):
        if code in self._author_cache:
            return self._author_cache[code]

        cached_author = str((cached_row or {}).get('javtxt_actors', '') or '').strip()
        if cached_author:
            self._author_cache[code] = cached_author
            return cached_author

        author = ''
        try:
            info = self.scraper.fetch_by_code(code)
            if info.get('found'):
                author = str(info.get('author', '') or '').strip()
                self._save_video_cache(code, info)
        except Exception:
            author = ''
        self._author_cache[code] = author
        return author

    def _save_video_cache(self, code, info):
        if self.database is None or not hasattr(self.database, 'save_javtxt_cache_for_video'):
            return
        try:
            self.database.save_javtxt_cache_for_video(code, info)
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
