import json
import re
from contextlib import contextmanager
from urllib.parse import quote

from app.core.runtime_config import get_scraper_browser_channel, get_scraper_locale
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


BAOMU_BASE_URL = 'https://netflav.com'
NEXT_DATA_RE = re.compile(
    r"<script[^>]+id=['\"]__NEXT_DATA__['\"][^>]*>\s*(\{.*?\})\s*</script>",
    re.IGNORECASE | re.DOTALL,
)


class BaomuActorScraper:
    def __init__(self, headless=True, locale=None):
        self.headless = headless
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self._playwright_manager = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @contextmanager
    def session(self):
        created_here = False
        if self._context is None or self._page is None:
            self.open_session()
            created_here = True
        try:
            yield self._page
        finally:
            if created_here:
                self.close_session()

    def open_session(self):
        if self._context is not None and self._page is not None:
            return self._page

        sync_playwright = import_sync_playwright()
        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        browser_channel = get_scraper_browser_channel()
        launch_options = {'headless': self.headless}
        if browser_channel:
            launch_options['channel'] = browser_channel
        try:
            self._browser = self._playwright.chromium.launch(**launch_options)
        except Exception:
            launch_options.pop('channel', None)
            self._browser = self._playwright.chromium.launch(**launch_options)
        self._context = self._browser.new_context(locale=self.locale, viewport={'width': 1440, 'height': 1200})
        self._page = self._context.new_page()
        minimize_browser_window_if_needed(self._page, self.headless)
        return self._page

    def close_session(self):
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            try:
                if self._browser is not None:
                    self._browser.close()
            finally:
                self._browser = None
                try:
                    if self._playwright is not None:
                        self._playwright.stop()
                finally:
                    self._playwright = None
                    self._playwright_manager = None

    def open_actor_page(self, page, actor_name):
        target_url = self.build_actor_url(actor_name)
        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        wait_for_page_ready(page)
        return target_url

    def parse_profile(self, page):
        return self.parse_profile_html(page.content())

    @staticmethod
    def build_actor_url(actor_name):
        return f'{BAOMU_BASE_URL}/all?actress={quote(str(actor_name or "").strip())}'

    @classmethod
    def parse_profile_html(cls, html):
        match = NEXT_DATA_RE.search(str(html or ''))
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
        props = payload.get('props') or {}
        actress = (((props.get('pageProps') or {}).get('actress')) or {})
        if not actress:
            actress = ((((props.get('initialState') or {}).get('all') or {}).get('actress')) or {})
        if not actress:
            return {}
        breast_text = str(actress.get('breast') or '').strip()
        waist_text = str(actress.get('waist') or '').strip()
        hip_text = str(actress.get('hip') or '').strip()
        explicit_cup_text = str(actress.get('cup') or '').strip()
        cup_text = explicit_cup_text or _extract_cup(breast_text)
        return {
            'actor_name': str(actress.get('name') or '').strip(),
            'birthday': _normalize_date(str(actress.get('birthday') or '').strip()),
            'height': _normalize_metric(str(actress.get('height') or '').strip()),
            'bust': _normalize_metric(breast_text),
            'waist': _normalize_metric(waist_text),
            'hip': _normalize_metric(hip_text),
            'cup': cup_text,
            'measurements_raw': _build_measurements_raw(breast_text, waist_text, hip_text, explicit_cup_text),
        }


def _normalize_date(text):
    normalized = str(text or '').strip().rstrip('-').strip()
    return normalized if re.fullmatch(r'\d{4}-\d{2}-\d{2}', normalized) else normalized


def _normalize_metric(text):
    match = re.search(r'(\d{2,3})', str(text or ''))
    return str(match.group(1)) if match else ''


def _extract_cup(text):
    match = re.search(r'\(\s*([A-Z]{1,3})\s*\)', str(text or ''), re.IGNORECASE)
    return str(match.group(1) or '').strip().upper() if match else ''


def _build_measurements_raw(breast_text, waist_text, hip_text, cup_text):
    parts = []
    if str(breast_text or '').strip():
        parts.append(f'breast={str(breast_text or "").strip()}')
    if str(waist_text or '').strip():
        parts.append(f'waist={str(waist_text or "").strip()}')
    if str(hip_text or '').strip():
        parts.append(f'hip={str(hip_text or "").strip()}')
    if str(cup_text or '').strip():
        parts.append(f'cup={str(cup_text or "").strip().upper()}')
    return '; '.join(parts)
