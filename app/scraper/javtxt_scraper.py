import re
from contextlib import contextmanager

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.runtime_config import (
    get_javtxt_base_url,
    get_javtxt_search_url,
    get_scraper_browser_channel,
    get_scraper_locale,
)
from app.core.second_source_actor_text import (
    is_unpublished_actor_text,
    normalize_second_source_actor_text,
)
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


JAVTXT_DETAIL_RE = re.compile(r'/v/(\d+)')
SECTION_ICON_RE = re.compile(r'^[^\w\s]')
TITLE_SUFFIX_RE = re.compile(r'\s*-\s*JAV.*$', re.I)

TITLE_SECTION_LABELS = {'番号', '演员', '出演女优'}
ACTOR_SECTION_LABELS = ('出演女优', '演员')
PRIMARY_ACTOR_SECTION_LABELS = ('出演女优',)
SECONDARY_ACTOR_SECTION_LABELS = ('演员',)
RELEASE_DATE_LABELS = ('发行时间', '登场时间')
MAKER_LABELS = ('片商',)
PUBLISHER_LABELS = ('厂牌',)
TAG_LABELS = ('类别',)


class JavtxtScraper:
    def __init__(self, headless=True, locale=None, logger=None):
        self.headless = headless
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self.base_url = get_javtxt_base_url()
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
        self._log('INFO', 'JAVTXT 浏览器会话已打开', headless=self.headless, locale=self.locale)
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
                    self._log('INFO', 'JAVTXT 浏览器会话已关闭')

    def fetch_by_code(self, code):
        normalized_code = normalize_code(code)
        if not normalized_code:
            raise ValueError('视频编号不能为空')

        with self.session() as page:
            search_url = self.build_search_url(normalized_code)
            self._log('INFO', '开始请求 JAVTXT 搜索页', code=normalized_code, search_url=search_url)
            page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)

            detail_url = self.find_first_detail_url(page)
            if not detail_url:
                self._log('WARNING', 'JAVTXT 搜索页未找到详情链接', code=normalized_code, search_url=search_url)
                return {
                    'code': normalized_code,
                    'found': False,
                    'error': '未搜索到匹配影片',
                    'source': JAVTXT_VIDEO_SOURCE,
                }

            self._log('INFO', 'JAVTXT 搜索命中详情页', code=normalized_code, detail_url=detail_url)
            page.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)
            info = self.parse_movie_info(page, normalized_code)
            info['found'] = bool(info.get('javtxt_movie_id'))
            info['source'] = JAVTXT_VIDEO_SOURCE
            self._log(
                'INFO',
                'JAVTXT 详情页解析完成',
                code=normalized_code,
                found=bool(info.get('found')),
                javtxt_movie_id=info.get('javtxt_movie_id', ''),
                author=info.get('author', ''),
                release_date=info.get('release_date', ''),
            )
            return info

    def build_search_url(self, normalized_code):
        search_code = re.sub(r'[^A-Z0-9]', '', str(normalized_code or '').upper())
        return get_javtxt_search_url(search_code)

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
        raw_actors_text, actors_text = extract_actors_text_details(lines)
        release_date = extract_detail_value(lines, RELEASE_DATE_LABELS)
        maker = extract_detail_value(lines, MAKER_LABELS)
        publisher = extract_detail_value(lines, PUBLISHER_LABELS)
        tags_text = extract_section_text(lines, TAG_LABELS)
        self._log(
            'INFO',
            'JAVTXT 页面文本已提取',
            code=requested_code,
            visible_line_count=len(lines),
            movie_id=movie_id,
            title=title,
            actors_text=actors_text,
            raw_actors_text=raw_actors_text,
        )
        return {
            'code': requested_code,
            'title': title,
            'author': actors_text,
            'author_raw': raw_actors_text,
            'release_date': release_date,
            'maker': maker,
            'publisher': publisher,
            'javtxt_title': title,
            'javtxt_actors': actors_text,
            'javtxt_actors_raw': raw_actors_text,
            'javtxt_tags': tags_text,
            'javtxt_movie_id': movie_id,
            'javtxt_url': final_url,
        }

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='javtxt_scraper', **fields)


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

    for actor_label in ACTOR_SECTION_LABELS:
        for label_index, line in enumerate(lines):
            matched_label, _ = match_section_label(line, (actor_label,))
            if matched_label != actor_label:
                continue
            for index in range(label_index - 1, -1, -1):
                cleaned = clean_title(lines[index], requested_code)
                if cleaned and cleaned not in TITLE_SECTION_LABELS:
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
    value = TITLE_SUFFIX_RE.sub('', value).strip()
    normalized_code = normalize_code(requested_code)
    if normalized_code:
        prefix_pattern = re.compile(rf'^\s*{re.escape(normalized_code)}[-_\s:：*]*', re.I)
        value = prefix_pattern.sub('', value).strip()
        hyphenated_code = re.sub(r'([A-Z]+)(\d+)$', r'\1-\2', normalized_code)
        value = re.sub(rf'^\s*{re.escape(hyphenated_code)}[-_\s:：*]*', '', value, flags=re.I).strip()
    return value


def extract_actors_text_details(lines):
    for labels in (PRIMARY_ACTOR_SECTION_LABELS, SECONDARY_ACTOR_SECTION_LABELS):
        actor_lines = extract_actor_section_lines(lines, labels)
        raw_actor_text = normalize_actor_source_text(' '.join(actor_lines))
        actor_text = normalize_second_source_actor_text(raw_actor_text)
        if actor_text or is_unpublished_actor_text(raw_actor_text):
            return raw_actor_text, actor_text
    return '', ''


def extract_actor_section_lines(lines, labels):
    normalized_labels = [str(label or '').strip() for label in labels if str(label or '').strip()]
    for index, line in enumerate(lines):
        matched_label, inline_value = match_section_label(line, normalized_labels)
        if inline_value is None:
            continue

        values = []
        inline_text = normalize_actor_source_text(inline_value)
        if normalize_second_source_actor_text(inline_text) or is_unpublished_actor_text(inline_text):
            values.append(inline_text)
            return values

        for next_index in range(index + 1, len(lines)):
            value = str(lines[next_index] or '').strip()
            if not value:
                continue
            next_label, next_inline = match_section_label(value, ACTOR_SECTION_LABELS)
            if next_label:
                break
            if is_next_section_label(value):
                break
            normalized_value = normalize_actor_source_text(value)
            if normalize_second_source_actor_text(normalized_value) or is_unpublished_actor_text(normalized_value):
                values.append(normalized_value)
            else:
                break
        if values:
            return values
        if matched_label:
            return []
    return []


def normalize_actor_source_text(value):
    return ' '.join(str(value or '').replace('\u3000', ' ').split()).strip()


def extract_detail_value(lines, labels):
    section_lines = extract_section_lines(lines, labels)
    return section_lines[0] if section_lines else ''


def extract_section_text(lines, labels):
    return ' '.join(extract_section_lines(lines, labels)).strip()


def extract_section_lines(lines, labels):
    normalized_labels = [
        str(label or '').strip()
        for label in labels
        if str(label or '').strip()
    ]
    for index, line in enumerate(lines):
        _, inline_value = match_section_label(line, normalized_labels)
        if inline_value is None:
            continue
        values = []
        if inline_value:
            values.append(inline_value)
        for next_index in range(index + 1, len(lines)):
            value = str(lines[next_index] or '').strip()
            if not value:
                continue
            if match_section_label(value, normalized_labels)[1] is not None:
                continue
            if is_next_section_label(value):
                break
            values.append(value)
        if values:
            return values
    return []


def match_section_label(line, labels):
    value = str(line or '').strip()
    if not value:
        return '', None
    normalized_value = strip_leading_section_icons(value)

    sorted_labels = sorted(labels, key=len, reverse=True)
    for label in sorted_labels:
        if normalized_value == label:
            return label, ''
        if not normalized_value.startswith(label):
            continue

        remainder = normalized_value[len(label):].strip()
        if remainder:
            remainder = re.sub(r'^[\s:：|·•-]+', '', remainder).strip()
        return label, remainder

    return '', None


def is_next_section_label(text):
    raw_value = str(text or '').strip()
    value = strip_leading_section_icons(raw_value)
    if not value:
        return False
    if value in {'出演女优', '演员', '番号', '类别', '标签'}:
        return True
    if value.endswith(('介绍', '简介')):
        return True
    if value.startswith(('剧情', '简介', '介绍', '系列', '片商', '导演', '厂牌', '发行时间', '登场时间')):
        return True
    return bool(SECTION_ICON_RE.match(raw_value)) and len(value) <= 12


def strip_leading_section_icons(text):
    value = str(text or '').strip()
    if not value:
        return ''
    return re.sub(r'^[^\w\u4e00-\u9fffぁ-んァ-ヴー]+', '', value).strip()


def normalize_code(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
