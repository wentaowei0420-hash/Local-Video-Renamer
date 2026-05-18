import re


AVFAN_HOME_URL = 'https://avfan.com/zh-CN'
AVFAN_MOVIE_RE = re.compile(r'/movies/([^/?#]+)')


class AvfanScraper:
    def __init__(self, headless=True, locale='zh-CN'):
        self.headless = headless
        self.locale = locale

    def fetch_by_code(self, code):
        code = normalize_code(code)
        if not code:
            raise ValueError('视频编号不能为空')

        sync_playwright = import_sync_playwright()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page(
                viewport={'width': 1440, 'height': 1200},
                locale=self.locale,
            )
            try:
                movie_url = self.search_movie_url(page, code)
                if not movie_url:
                    return {
                        'code': code,
                        'found': False,
                        'error': '未搜索到匹配影片',
                    }

                page.goto(movie_url, wait_until='domcontentloaded', timeout=60000)
                wait_for_page_ready(page)
                movie_info = parse_movie_info_from_page(page)
                movie_info['code'] = movie_info.get('code') or code
                movie_info['avfan_movie_id'] = extract_movie_id(page.url)
                movie_info['avfan_url'] = page.url
                movie_info['found'] = True
                return movie_info
            finally:
                browser.close()

    def fetch_by_url(self, url):
        sync_playwright = import_sync_playwright()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page(
                viewport={'width': 1440, 'height': 1200},
                locale=self.locale,
            )
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                accept_age_gate_if_needed(page)
                wait_for_page_ready(page)
                movie_info = parse_movie_info_from_page(page)
                movie_info['avfan_movie_id'] = extract_movie_id(page.url)
                movie_info['avfan_url'] = page.url
                movie_info['found'] = bool(movie_info.get('code') or movie_info.get('title'))
                return movie_info
            finally:
                browser.close()

    def search_movie_url(self, page, code):
        page.goto(AVFAN_HOME_URL, wait_until='domcontentloaded', timeout=60000)
        accept_age_gate_if_needed(page)
        wait_for_page_ready(page)
        fill_search_box(page, code)
        click_search_button(page)
        wait_for_page_ready(page)

        results = collect_search_results(page, code)
        if results:
            return results[0]['href']
        return None


def import_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            '当前 Python 环境未安装 Playwright。请使用包含 Playwright 的环境运行系统，'
            '例如 video_env，或执行 python -m pip install playwright。'
        ) from exc
    return sync_playwright


def accept_age_gate_if_needed(page):
    for selector in ('text=是，我已经成年', 'text=我已经成年', 'text=Yes', 'text=I am over'):
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2500):
                button.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def wait_for_page_ready(page):
    try:
        page.wait_for_load_state('networkidle', timeout=12000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.body && document.body.innerText.trim().length > 20",
            timeout=12000,
        )
    except Exception:
        pass
    page.wait_for_timeout(600)


def fill_search_box(page, code):
    reveal_search_box_if_needed(page)
    selectors = (
        'input[placeholder*="输入搜索关键词"]',
        'input[placeholder*="关键词"]',
        'input[placeholder*="搜索"]',
        'input[placeholder*="搜尋"]',
        'input[type="search"]',
        'input[type="text"]',
        'input[name="q"]',
        'form input',
        'header input',
        'nav input',
        'input',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=2500):
                locator.click()
                locator.fill(code)
                return
        except Exception:
            continue

    if fill_search_box_by_js(page, code):
        return
    raise RuntimeError('未找到搜索输入框')


def reveal_search_box_if_needed(page):
    for selector in ('text=搜索', 'button:has-text("搜索")', 'a:has-text("搜索")', '[aria-label*="搜索"]'):
        try:
            target = page.locator(selector).first
            if target.is_visible(timeout=800):
                target.click()
                page.wait_for_timeout(400)
                return
        except Exception:
            continue


def fill_search_box_by_js(page, code):
    return bool(page.evaluate(
        """
        (code) => {
            const inputs = Array.from(document.querySelectorAll('input'));
            const target = inputs.find((node) => {
                const rect = node.getBoundingClientRect();
                const placeholder = node.getAttribute('placeholder') || '';
                const type = node.getAttribute('type') || '';
                return rect.width > 80 &&
                    rect.height > 10 &&
                    node.offsetParent !== null &&
                    (placeholder.includes('搜索') ||
                     placeholder.includes('搜尋') ||
                     placeholder.includes('关键词') ||
                     type === 'search' ||
                     type === 'text' ||
                     !type);
            });
            if (!target) return false;
            target.focus();
            target.value = code;
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        """,
        code,
    ))


def click_search_button(page):
    try:
        button = page.get_by_role('button', name=re.compile('搜索|搜尋|Search', re.I)).first
        if button.is_visible(timeout=2500):
            button.click()
            return
    except Exception:
        pass
    page.keyboard.press('Enter')


def collect_search_results(page, code):
    results = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href*="/movies/"]')).map((node) => {
            const text = (node.innerText || node.textContent || '').trim();
            return {
                text,
                href: new URL(node.getAttribute('href'), location.href).href
            };
        }).filter((item) => item.href);
        """
    )

    deduped = []
    seen = set()
    for item in results:
        href = item.get('href', '')
        if href in seen:
            continue
        seen.add(href)
        text = item.get('text', '')
        deduped.append({
            'code_matched': normalize_code(code) in normalize_code(text),
            'text': text,
            'href': href,
        })

    matched = [item for item in deduped if item['code_matched']]
    return matched or deduped[:20]


def parse_movie_info_from_page(page):
    lines = visible_lines(page)
    info = {
        'title': first_text(page, 'h1'),
        'code': '',
        'release_date': '',
        'duration': '',
        'director': [],
        'maker': [],
        'publisher': [],
        'tags': [],
        'actors': [],
    }
    parse_visible_field_lines(info, lines)
    return normalize_movie_info(info)


def visible_lines(page):
    try:
        text = page.locator('body').inner_text(timeout=30000)
    except Exception:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def first_text(page, selector):
    try:
        return page.locator(selector).first.inner_text(timeout=5000).strip()
    except Exception:
        return ''


def parse_visible_field_lines(info, lines):
    for line in lines:
        for field, aliases in movie_field_aliases().items():
            matched_alias = next(
                (alias for alias in aliases if line.startswith(f'{alias}:') or line.startswith(f'{alias}：')),
                None,
            )
            if not matched_alias:
                continue

            value = line.split(':', 1)[1] if ':' in line else line.split('：', 1)[1]
            merge_field_value(info, field, value)


def movie_field_aliases():
    return {
        'code': ('番号', '番號', '品番'),
        'release_date': ('发行日期', '發行日期', '发售日', '発売日', '日期'),
        'duration': ('片长', '片長', '时长', '時長', '収録時間'),
        'director': ('导演', '導演', '監督'),
        'maker': ('制作商', '製作商', 'メーカー'),
        'publisher': ('发行商', '發行商', '厂牌', 'レーベル'),
        'tags': ('标签', '標籤', '类别', '類別', 'ジャンル'),
        'actors': ('演员', '演員', '女优', '女優', '出演者'),
    }


def merge_field_value(info, field, value):
    value = normalize_value(value)
    if not value:
        return

    if isinstance(info[field], list):
        for part in split_multi_value(value):
            if is_valid_movie_value(part) and part not in info[field]:
                info[field].append(part)
    elif not info[field]:
        info[field] = value


def normalize_movie_info(info):
    for field in ('director', 'maker', 'publisher', 'tags', 'actors'):
        info[field] = [item for item in info[field] if is_valid_movie_value(item)]
    return info


def normalize_value(value):
    return ' '.join(str(value or '').replace('复制', '').split()).strip()


def split_multi_value(value):
    value = normalize_value(value)
    if not value:
        return []
    for separator in ('、', ',', '，', '/', '／'):
        value = value.replace(separator, ' ')
    return [item.strip() for item in value.split() if item.strip()]


def is_valid_movie_value(value):
    ignored_values = {
        '复制', '推荐', '亚洲', '欧美', '系列', '制作商', '导演', '磁链',
        '搜索', '反馈', '演员', '类别', '想看', '看过', '保存至清单',
    }
    return bool(value and value not in ignored_values)


def extract_movie_id(url):
    match = AVFAN_MOVIE_RE.search(url or '')
    return match.group(1) if match else ''


def normalize_code(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
