import re
from contextlib import contextmanager
from urllib.parse import quote, urlparse

from app.core.runtime_config import get_scraper_browser_channel, get_scraper_locale
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


BINGHUO_BASE_URL = 'https://www.fouroursonsinc.com'
PERSON_PATH_RE = re.compile(r'/person/(\d+)')
COMPACT_MEASUREMENT_RE = re.compile(
    r'(?<!\d)(?:[0-9]{1,4}\s*[-/／]\s*)+[0-9]{1,4}(?:\s*\(\s*cm\s*\))?(?!\d)',
    re.IGNORECASE,
)


class BinghuoActorScraper:
    def __init__(self, headless=True, locale=None, logger=None):
        self.headless = headless
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self.logger = logger
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

    def open_search_page(self, page, actor_name):
        target_url = self.build_search_url(actor_name)
        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        wait_for_page_ready(page)
        return target_url

    def collect_search_results(self, page):
        return page.evaluate(
            """
            () => {
                const rows = [];
                const seen = new Set();
                for (const link of Array.from(document.querySelectorAll('a[href]'))) {
                    let href = '';
                    try {
                        href = new URL(link.getAttribute('href'), location.href).href;
                    } catch (error) {
                        continue;
                    }
                    if (!href || !href.includes('/person/')) {
                        continue;
                    }
                    if (seen.has(href)) {
                        continue;
                    }
                    seen.add(href);
                    rows.push({
                        href,
                        title: (link.innerText || link.textContent || '').trim(),
                        summary: ((link.closest('article, li, .item, .result, .search-result, .card') || link.parentElement || link).innerText || '').trim(),
                    });
                }
                return rows;
            }
            """
        )

    def open_person_page(self, page, person_id='', url=''):
        target_url = str(url or '').strip() or self.build_person_url(person_id)
        if not target_url:
            raise ValueError('Missing Binghuo person target')
        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        wait_for_page_ready(page)
        return page.url or target_url

    def parse_profile(self, page):
        body_text = str(page.locator('body').inner_text(timeout=10000) or '').strip()
        measurements = _extract_measurements(body_text)
        return {
            'person_id': self.extract_person_id(page.url or ''),
            'birthday': _normalize_date_text(
                _extract_first(body_text, [r'\u751f\u65e5[:：]?\s*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})'])
            ),
            'age': _extract_first(body_text, [r'\u5e74\u9f84[:：]?\s*([0-9]{1,3})']),
            'height': _normalize_height(
                _extract_first(body_text, [r'\u8eab\u9ad8[:：]?\s*([0-9]{2,3}\s*cm?)'])
            ),
            'bust': measurements['bust'],
            'cup': measurements['cup'],
            'measurements_raw': measurements['measurements_raw'],
            'waist': measurements['waist'],
            'hip': measurements['hip'],
        }

    @staticmethod
    def build_search_url(actor_name):
        return f'{BINGHUO_BASE_URL}/search.php?f=_all&s=relevance&q={quote(str(actor_name or "").strip())}'

    @staticmethod
    def build_person_url(person_id):
        normalized_person_id = str(person_id or '').strip()
        if not normalized_person_id:
            return ''
        return f'{BINGHUO_BASE_URL}/person/{normalized_person_id}'

    @staticmethod
    def extract_person_id(url):
        match = PERSON_PATH_RE.search(urlparse(str(url or '').strip()).path or '')
        return match.group(1) if match else ''


def _extract_first(text, patterns):
    normalized_text = str(text or '').strip()
    for pattern in patterns:
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match:
            return str(match.group(1) or '').strip()
    return ''


def _normalize_height(text):
    normalized = str(text or '').strip().lower().replace(' ', '')
    if normalized.endswith('cm'):
        normalized = normalized[:-2]
    return normalized


def _normalize_date_text(text):
    normalized = str(text or '').strip()
    if not normalized:
        return ''
    match = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', normalized)
    if not match:
        return normalized
    year, month, day = match.groups()
    return f'{year}-{int(month):02d}-{int(day):02d}'


def _extract_measurement(text, axis):
    normalized_text = str(text or '').strip()
    axis_pattern = rf'{re.escape(axis)}\s*[:：]?\s*([0-9]{{2,3}})'
    match = re.search(axis_pattern, normalized_text, re.IGNORECASE)
    if match:
        return str(match.group(1) or '').strip()
    return _extract_first(
        normalized_text,
        [
            rf'{re.escape(_axis_label(axis))}[:：]?\s*([0-9]{{2,3}})',
        ],
    )


def _extract_measurements(text):
    for candidate_text in _measurement_candidate_texts(text):
        measurements_raw = _extract_explicit_measurements_raw(candidate_text)
        explicit_measurements = {
            'bust': _extract_measurement(candidate_text, 'B'),
            'cup': _extract_cup(candidate_text),
            'measurements_raw': measurements_raw,
            'waist': _extract_measurement(candidate_text, 'W'),
            'hip': _extract_measurement(candidate_text, 'H'),
        }
        if any(explicit_measurements.values()):
            return explicit_measurements

        compact_measurements = _extract_compact_measurements(candidate_text)
        if compact_measurements is not None:
            return compact_measurements

    return {'bust': '', 'cup': '', 'measurements_raw': '', 'waist': '', 'hip': ''}


def _measurement_candidate_texts(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ['']

    local_candidates = []
    lines = [str(line or '').strip() for line in normalized_text.splitlines()]
    sanwei_label = '\u4e09\u56f4'
    for index, line in enumerate(lines):
        if sanwei_label not in line:
            continue
        nearby_lines = [line]
        for next_line in lines[index + 1:index + 3]:
            if next_line:
                nearby_lines.append(next_line)
        candidate = ' '.join(part for part in nearby_lines if part).strip()
        if candidate and candidate not in local_candidates:
            local_candidates.append(candidate)

    if local_candidates:
        return local_candidates

    return [normalized_text]


def _extract_compact_measurements(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return None

    for match in COMPACT_MEASUREMENT_RE.finditer(normalized_text):
        raw_text = str(match.group(0) or '').strip()
        groups = re.findall(r'\d+', str(match.group(0) or ''))
        if len(groups) != 3:
            return {'bust': '', 'cup': '', 'measurements_raw': raw_text, 'waist': '', 'hip': ''}
        if not all(2 <= len(group) <= 3 for group in groups):
            return {'bust': '', 'cup': '', 'measurements_raw': raw_text, 'waist': '', 'hip': ''}
        bust, waist, hip = groups
        return {
            'bust': str(bust or '').strip(),
            'cup': '',
            'measurements_raw': raw_text,
            'waist': str(waist or '').strip(),
            'hip': str(hip or '').strip(),
        }

    return None


def _extract_cup(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ''

    patterns = (
        r'B\s*[:锛歖?\s*[0-9]{2,3}\s*cm?\s*\(\s*([A-Z]{1,3})\s*\)',
        r'B\s*[:锛歖?\s*[0-9]{2,3}\s*\(\s*([A-Z]{1,3})\s*\)',
        rf'{re.escape(_axis_label("B"))}[:锛歖?\s*[0-9]{{2,3}}\s*cm?\s*\(\s*([A-Z]{{1,3}})\s*\)',
        rf'{re.escape(_axis_label("B"))}[:锛歖?\s*[0-9]{{2,3}}\s*\(\s*([A-Z]{{1,3}})\s*\)',
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match:
            return str(match.group(1) or '').strip().upper()
    return ''


def _extract_explicit_measurements_raw(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ''

    patterns = (
        r'(B\s*[:锛歖?\s*[0-9]{2,3}(?:\s*cm?)?(?:\s*\(\s*[A-Z]{1,3}\s*\))?\s*(?:[/\s]+W\s*[:锛歖?\s*[0-9]{2,3}(?:\s*cm?)?)\s*(?:[/\s]+H\s*[:锛歖?\s*[0-9]{2,3}(?:\s*cm?)?))',
        rf'({re.escape(_axis_label("B"))}\s*[:锛歖?\s*[0-9]{{2,3}}(?:\s*cm?)?(?:\s*\(\s*[A-Z]{{1,3}}\s*\))?\s*'
        rf'(?:[/\s]+{re.escape(_axis_label("W"))}\s*[:锛歖?\s*[0-9]{{2,3}}(?:\s*cm?)?)\s*'
        rf'(?:[/\s]+{re.escape(_axis_label("H"))}\s*[:锛歖?\s*[0-9]{{2,3}}(?:\s*cm?)?))',
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text, re.IGNORECASE)
        if match:
            return _strip_measurement_leading_label(str(match.group(1) or '').strip())
    return ''


def _strip_measurement_leading_label(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ''
    return re.sub(r'^\s*三围\s*[:：]\s*', '', normalized_text, flags=re.IGNORECASE).strip()


def _axis_label(axis):
    mapping = {
        'B': '\u80f8\u56f4',
        'W': '\u8170\u56f4',
        'H': '\u81c0\u56f4',
    }
    return mapping.get(str(axis or '').upper(), str(axis or '').upper())
