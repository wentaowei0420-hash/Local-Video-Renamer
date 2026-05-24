import re
from contextlib import contextmanager

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


JAVTXT_DETAIL_RE = re.compile(r'/v/(\d+)')
SECTION_ICON_RE = re.compile(r'^[🆔🗂️📅🎥🔖🏷️🧲📙🔍🔥🆕📊]')


class JavtxtScraper:
    def __init__(self, headless=True, locale='zh-CN'):
        self.headless = headless
        self.locale = locale
        self.base_url = 'https://javtxt.top'
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
        self._browser = self._playwright.chromium.launch(headless=self.headless)
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

    def fetch_by_code(self, code):
        normalized_code = normalize_code(code)
        if not normalized_code:
            raise ValueError('视频编号不能为空')

        with self.session() as page:
            search_url = self.build_search_url(normalized_code)
            page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)

            detail_url = self.find_first_detail_url(page)
            if not detail_url:
                return {
                    'code': normalized_code,
                    'found': False,
                    'error': '未搜索到匹配影片',
                    'source': JAVTXT_VIDEO_SOURCE,
                }

            page.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)
            info = self.parse_movie_info(page, normalized_code)
            info['found'] = bool(info.get('javtxt_movie_id'))
            info['source'] = JAVTXT_VIDEO_SOURCE
            return info

    def build_search_url(self, normalized_code):
        search_code = re.sub(r'[^A-Z0-9]', '', str(normalized_code or '').upper())
        return f'{self.base_url}/search?type=id&q={search_code}'

    def find_first_detail_url(self, page):
        links = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]'))
                .map((node) => {
                    try {
                        return new URL(node.getAttribute('href'), location.href).href;
                    } catch (error) {
                        return '';
                    }
                })
                .filter((href) => /\\/v\\/\\d+/.test(href));
            """
        )
        return links[0] if links else ''

    def parse_movie_info(self, page, requested_code):
        lines = visible_lines(page)
        final_url = page.url or ''
        movie_id = extract_javtxt_movie_id(final_url)
        title = extract_title(page, lines, requested_code)
        actors_text = extract_actor_text(lines)
        release_date = extract_detail_value(lines, ('📅 发行时间', '发行时间', '發行時間'))
        maker = extract_detail_value(lines, ('🎥 片商', '片商'))
        publisher = extract_detail_value(lines, ('🔖 厂牌', '厂牌', '廠牌'))
        return {
            'code': requested_code,
            'title': title,
            'author': actors_text,
            'release_date': release_date,
            'maker': maker,
            'publisher': publisher,
            'javtxt_title': title,
            'javtxt_actors': actors_text,
            'javtxt_movie_id': movie_id,
            'javtxt_url': final_url,
        }


def visible_lines(page):
    try:
        text = page.locator('body').inner_text(timeout=30000)
    except Exception:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_javtxt_movie_id(url):
    match = JAVTXT_DETAIL_RE.search(url or '')
    return match.group(1) if match else ''


def extract_title(page, lines, requested_code):
    for selector in ('main h1', 'article h1', 'h1', 'main h2', 'article h2', 'h2'):
        try:
            text = page.locator(selector).first.inner_text(timeout=3000).strip()
        except Exception:
            continue
        cleaned = clean_title(text, requested_code)
        if cleaned:
            return cleaned

    for actor_label in ('出演女优', '演员'):
        if actor_label not in lines:
            continue
        label_index = lines.index(actor_label)
        for index in range(label_index - 1, -1, -1):
            cleaned = clean_title(lines[index], requested_code)
            if cleaned and cleaned not in {'番号', '演员'}:
                return cleaned

    page_title = ''
    try:
        page_title = page.title().strip()
    except Exception:
        page_title = ''
    return clean_title(page_title, requested_code)


def clean_title(text, requested_code):
    value = str(text or '').strip()
    if not value:
        return ''
    value = re.sub(r'\s*-\s*JAV档案馆\s*$', '', value, flags=re.I)
    normalized_code = normalize_code(requested_code)
    if normalized_code:
        prefix_pattern = re.compile(rf'^\s*{re.escape(normalized_code)}[-_\s:：]*', re.I)
        value = prefix_pattern.sub('', value).strip()
        hyphenated_code = re.sub(r'([A-Z]+)(\d+)$', r'\1-\2', normalized_code)
        value = re.sub(rf'^\s*{re.escape(hyphenated_code)}[-_\s:：]*', '', value, flags=re.I).strip()
    return value


def extract_actor_text(lines):
    for label in ('出演女优', '演员'):
        if label not in lines:
            continue
        label_index = lines.index(label)
        for index in range(label_index + 1, len(lines)):
            line = str(lines[index] or '').strip()
            if not line:
                continue
            if is_next_section_label(line):
                break
            return normalize_actor_line(line)
    return ''


def extract_detail_value(lines, labels):
    normalized_labels = {str(label or '').strip() for label in labels}
    for index, line in enumerate(lines):
        if str(line or '').strip() not in normalized_labels:
            continue
        for next_index in range(index + 1, len(lines)):
            value = str(lines[next_index] or '').strip()
            if not value:
                continue
            if value in normalized_labels:
                continue
            if is_next_section_label(value):
                break
            return value
    return ''


def is_next_section_label(text):
    value = str(text or '').strip()
    if not value:
        return False
    if value in {'剧情介绍', '出演女优', '演员', '番号'}:
        return True
    return bool(SECTION_ICON_RE.match(value))


def normalize_actor_line(text):
    return ' '.join(part for part in re.split(r'\s{2,}', str(text or '').strip()) if part)


def normalize_code(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
