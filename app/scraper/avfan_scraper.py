import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from app.core.app_config import get_setting
from app.core.project_paths import AVFAN_PROFILE_DIR, BROWSER_PROFILES_DIR
from app.scraper.login_status_service import ensure_logged_in_on_home


AVFAN_MOVIE_RE = re.compile(r'/movies/([^/?#]+)')
DEFAULT_PROFILE_DIR = AVFAN_PROFILE_DIR
SEARCH_COOLDOWN_MS = 180000
MANUAL_CHECK_TIMEOUT_MS = 600000


def reset_avfan_browser_profile(profile_dir=None):
    target = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
    target = target.resolve()
    profile_root = BROWSER_PROFILES_DIR.resolve()

    if target != profile_root / 'avfan':
        raise ValueError('拒绝清理非 AVFan 专用浏览器档案目录')

    if not target.exists():
        return {
            'reset': False,
            'profile_dir': str(target),
            'message': '网页登录状态已经是空的。',
        }

    try:
        shutil.rmtree(target)
    except PermissionError as exc:
        raise RuntimeError('网页登录状态正在被浏览器占用，请先关闭补全时弹出的浏览器窗口后再重置。') from exc

    return {
        'reset': True,
        'profile_dir': str(target),
        'message': '已重置网页登录状态。',
    }


class AvfanScraper:
    def __init__(self, headless=True, locale='zh-CN', profile_dir=None, cooldown_before_search=False):
        self.headless = headless
        self.locale = locale
        self.profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
        self.cooldown_before_search = cooldown_before_search
        self.cooldown_used = False
        self.home_url = get_setting('SCRAPER_HOME_URL', required=True)
        self._playwright_manager = None
        self._playwright = None
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
        self._context = self.open_context(self._playwright)
        self._page = self.get_page(self._context)
        return self._page

    def use_fresh_page(self, close_existing=False):
        page = self.open_session()
        context = self._context
        if context is None:
            return page

        existing_pages = list(context.pages)
        if close_existing:
            for existing_page in existing_pages:
                try:
                    existing_page.close()
                except Exception:
                    continue
            self._page = context.new_page()
            return self._page

        if page is None or page.is_closed():
            self._page = context.new_page()
            return self._page

        current_url = (page.url or '').lower()
        if '/movies/' in current_url:
            self._page = context.new_page()
            return self._page

        return page

    def close_session(self):
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            self.cooldown_used = False
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            finally:
                self._playwright = None
                self._playwright_manager = None

    def fetch_by_code(self, code):
        code = normalize_code(code)
        if not code:
            raise ValueError('视频编号不能为空')

        with self.session() as page:
            movie_url = self.search_movie_url(page, code)
            if not movie_url:
                return {
                    'code': code,
                    'found': False,
                    'error': '未搜索到匹配影片',
                }

            page.goto(movie_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_security_verification_if_needed(page, self.headless)
            wait_for_manual_login_if_needed(page, self.headless)
            wait_for_page_ready(page)
            movie_info = parse_movie_info_from_page(page)
            movie_info['code'] = movie_info.get('code') or code
            movie_info['avfan_movie_id'] = extract_movie_id(page.url)
            movie_info['avfan_url'] = page.url
            movie_info['found'] = True
            return movie_info

    def fetch_by_url(self, url):
        with self.session() as page:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            wait_for_security_verification_if_needed(page, self.headless)
            accept_age_gate_if_needed(page)
            wait_for_security_verification_if_needed(page, self.headless)
            wait_for_manual_login_if_needed(page, self.headless)
            wait_for_page_ready(page)
            movie_info = parse_movie_info_from_page(page)
            movie_info['avfan_movie_id'] = extract_movie_id(page.url)
            movie_info['avfan_url'] = page.url
            movie_info['found'] = bool(movie_info.get('code') or movie_info.get('title'))
            return movie_info

    def open_context(self, playwright):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        launch_options = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={'width': 1440, 'height': 1200},
            locale=self.locale,
        )
        try:
            return playwright.chromium.launch_persistent_context(channel='chrome', **launch_options)
        except Exception:
            return playwright.chromium.launch_persistent_context(**launch_options)

    def get_page(self, context):
        # Persistent profiles may restore the last browsing session, including
        # movie detail pages. Start every workflow from a fresh page so auto
        # login and scraping do not briefly jump to stale tabs.
        fresh_page = context.new_page()
        for page in list(context.pages):
            if page == fresh_page:
                continue
            try:
                page.close()
            except Exception:
                continue
        return fresh_page

    def search_movie_url(self, page, code):
        if is_login_page(page) or is_security_verification_page(page) or not can_search_from_current_page(page):
            page.goto(self.home_url, wait_until='domcontentloaded', timeout=60000)

        wait_for_security_verification_if_needed(page, self.headless)
        accept_age_gate_if_needed(page)
        wait_for_security_verification_if_needed(page, self.headless)
        wait_for_manual_login_if_needed(page, self.headless)
        wait_for_page_ready(page)
        if same_home_page(page.url, self.home_url):
            ensure_logged_in_on_home(page, self.headless)
        self.wait_before_first_search(page)
        fill_search_box(page, code)
        click_search_button(page)
        wait_for_page_ready(page)
        wait_for_security_verification_if_needed(page, self.headless)
        wait_for_manual_login_if_needed(page, self.headless)
        wait_for_page_ready(page)

        results = collect_search_results(page, code)
        if results:
            return results[0]['href']
        return None

    def wait_before_first_search(self, page):
        if not self.cooldown_before_search or self.cooldown_used:
            return
        self.cooldown_used = True
        page.wait_for_timeout(SEARCH_COOLDOWN_MS)


def import_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            '当前 Python 环境未安装 Playwright。请使用包含 Playwright 的环境运行系统，例如 video_env，'
            '或执行 python -m pip install playwright。'
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


def wait_for_security_verification_if_needed(page, headless):
    if not is_security_verification_page(page):
        return

    if headless:
        raise RuntimeError(
            'AVFan 出现 Cloudflare 真人验证。请重新点击“补全信息”，勾选“显示浏览器窗口”，'
            '在弹出的浏览器中手动完成验证；如果页面显示 Verification failed，请刷新页面后再验证。'
        )

    try:
        page.wait_for_function(
            """
            () => {
                const text = (document.body?.innerText || '').toLowerCase();
                const title = (document.title || '').toLowerCase();
                const combined = `${title}\\n${text}`;
                const markers = [
                    'security verification',
                    'please complete the captcha',
                    'verification failed',
                    'cloudflare',
                    'captcha',
                    '请验证您是真人'
                ];
                const hasMarker = markers.some((marker) => combined.includes(marker));
                const hasChallengeFrame = Boolean(
                    document.querySelector('iframe[src*="challenges.cloudflare.com"]') ||
                    document.querySelector('input[name="cf-turnstile-response"]') ||
                    document.querySelector('[class*="cf-turnstile"]')
                );
                return !hasMarker && !hasChallengeFrame;
            }
            """,
            timeout=MANUAL_CHECK_TIMEOUT_MS,
        )
        wait_for_page_ready(page)
    except Exception as exc:
        raise RuntimeError('等待真人验证超时，请刷新验证页面，通过后重新点击“补全信息”。') from exc


def is_security_verification_page(page):
    try:
        title = page.title().lower()
    except Exception:
        title = ''

    try:
        text = page.locator('body').inner_text(timeout=1500).lower()
    except Exception:
        text = ''

    combined = f'{title}\n{text}'
    markers = (
        'security verification',
        'please complete the captcha',
        'verification failed',
        'cloudflare',
        'captcha',
        '请验证您是真人',
    )
    if any(marker in combined for marker in markers):
        return True

    for selector in (
        'iframe[src*="challenges.cloudflare.com"]',
        'input[name="cf-turnstile-response"]',
        '[class*="cf-turnstile"]',
    ):
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue

    return False


def wait_for_manual_login_if_needed(page, headless):
    if not is_login_page(page):
        return

    if headless:
        raise RuntimeError(
            'AVFan 需要登录。请点击“补全信息”，勾选“显示浏览器窗口”，'
            '在弹出的浏览器中完成登录后再继续补全。'
        )

    try:
        page.wait_for_function(
            """
            () => {
                const path = location.pathname.toLowerCase();
                if (path.includes('sign_in') || path.includes('login')) return false;
                const passwordInput = document.querySelector('input[type="password"]');
                return !passwordInput;
            }
            """,
            timeout=300000,
        )
        wait_for_page_ready(page)
    except Exception as exc:
        raise RuntimeError('等待登录超时，请重新点击“补全信息”并完成登录。') from exc


def is_login_page(page):
    url = (page.url or '').lower()
    if 'sign_in' in url or 'login' in url:
        return True

    try:
        return page.locator('input[type="password"]').first.is_visible(timeout=1200)
    except Exception:
        return False


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


def can_search_from_current_page(page):
    if not page.url or page.url == 'about:blank':
        return False
    if is_security_verification_page(page) or is_login_page(page):
        return True
    return has_search_input(page)


def has_search_input(page):
    selectors = (
        'input[placeholder*="输入搜索关键词"]',
        'input[placeholder*="关键词"]',
        'input[placeholder*="搜索"]',
        'input[placeholder*="搜尋"]',
        'input[type="search"]',
        'input[name="q"]',
    )
    for selector in selectors:
        try:
            if page.locator(selector).first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


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
            target.value = '';
            target.dispatchEvent(new Event('input', { bubbles: true }));
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
        'duration': ('片长', '片長', '时长', '時間', '収録時間'),
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


def same_home_page(current_url, home_url):
    current = str(current_url or '').rstrip('/')
    target = str(home_url or '').rstrip('/')
    return bool(current and target and current == target)
