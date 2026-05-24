from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from app.scraper.avfan_scraper import (
    AvfanScraper,
    accept_age_gate_if_needed,
    wait_for_manual_login_if_needed,
    wait_for_page_ready,
    wait_for_security_verification_if_needed,
)


class AvfanActorScraper:
    def __init__(self, headless=True, locale='zh-CN', profile_dir=None):
        self.browser = AvfanScraper(
            headless=headless,
            locale=locale,
            profile_dir=profile_dir,
        )
        self.actor_base_urls = {}

    def session(self):
        return self.browser.session()

    def open_listing_page(self, page, actor_name, page_number):
        actor_name = str(actor_name or '').strip()
        if not actor_name:
            raise ValueError('缺少演员姓名')

        base_url = self.actor_base_urls.get(actor_name)
        if not base_url:
            search_url = self.build_search_url(actor_name)
            page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            self._prepare_page(page)
            base_url = self._open_first_actor_result(page)
            if not base_url:
                return search_url
            self.actor_base_urls[actor_name] = base_url

        target_url = self.build_actor_page_url(base_url, page_number)
        if page.url != target_url:
            page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
            self._prepare_page(page)
        return target_url

    @staticmethod
    def build_search_url(actor_name):
        safe_actor_name = quote(str(actor_name or '').strip())
        return f'https://avfan.com/search?q={safe_actor_name}&st=cast'

    @staticmethod
    def build_actor_page_url(base_url, page_number):
        parsed = urlparse(str(base_url or '').strip())
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if int(page_number or 1) <= 1:
            query.pop('page', None)
        else:
            query['page'] = str(int(page_number))
        return urlunparse(parsed._replace(query=urlencode(query)))

    @staticmethod
    def extract_actor_id(url):
        parsed = urlparse(str(url or '').strip())
        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) >= 2 and parts[-2] == 'casts':
            return parts[-1]
        if parts and parts[-1] == 'casts':
            return ''
        return parts[-1] if parts else ''

    @staticmethod
    def detect_total_pages(page):
        total_pages = page.evaluate(
            """
            () => {
                const pages = new Set();
                for (const link of document.querySelectorAll('a[href*="page="]')) {
                    try {
                        const href = new URL(link.href, location.href);
                        const value = Number.parseInt(href.searchParams.get('page') || '', 10);
                        if (Number.isFinite(value) && value > 0) {
                            pages.add(value);
                        }
                    } catch (error) {
                    }
                }
                return pages.size ? Math.max(...pages) : 1;
            }
            """
        )
        try:
            return max(1, int(total_pages or 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def collect_page_entries(page):
        return page.evaluate(
            """
            () => {
                const rows = [];
                const seen = new Set();
                const links = Array.from(document.querySelectorAll('a[href*="/movies/"]'));
                for (const link of links) {
                    let href = '';
                    try {
                        href = new URL(link.getAttribute('href'), location.href).href;
                    } catch (error) {
                        continue;
                    }
                    if (!href || seen.has(href)) {
                        continue;
                    }
                    seen.add(href);

                    const container =
                        link.closest('article, li, .card, .item, .movie, .col, .col-md-2, .col-md-3, .col-sm-3, .col-xs-6, div') ||
                        link.parentElement ||
                        link;
                    const text = (container.innerText || link.innerText || '').trim();
                    if (!text) {
                        continue;
                    }
                    rows.push({ href, text });
                }
                return rows;
            }
            """
        )

    def _prepare_page(self, page):
        wait_for_security_verification_if_needed(page, self.browser.headless)
        accept_age_gate_if_needed(page)
        wait_for_security_verification_if_needed(page, self.browser.headless)
        wait_for_manual_login_if_needed(page, self.browser.headless)
        wait_for_page_ready(page)

    def _open_first_actor_result(self, page):
        target_url = self._resolve_first_actor_result_url(page)
        if not target_url:
            return ''

        current_url = page.url
        try:
            page.locator('a[data-codex-actor-result-index="0"]').first.click(timeout=5000)
            page.wait_for_function(
                "(previousUrl) => location.href !== previousUrl",
                current_url,
                timeout=15000,
            )
            self._prepare_page(page)
            if '/casts/' in (page.url or ''):
                return page.url
        except Exception:
            pass

        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        self._prepare_page(page)
        return page.url or target_url

    @staticmethod
    def _resolve_first_actor_result_url(page):
        actor_links = AvfanActorScraper.collect_actor_result_links(page)
        if not actor_links:
            return ''
        return actor_links[0].get('href', '')

    @staticmethod
    def collect_actor_result_links(page):
        return page.evaluate(
            """
            () => {
                const rows = [];
                let resultIndex = 0;
                const ignoredIds = new Set(['new_and_recommendations']);
                const searchRoot =
                    document.querySelector('h2.title-h2')?.parentElement ||
                    document.querySelector('main') ||
                    document.body;
                const candidates = Array.from(document.querySelectorAll('a[href]'));
                for (const link of candidates) {
                    let href = '';
                    try {
                        href = new URL(link.getAttribute('href'), location.href).href;
                    } catch (error) {
                        continue;
                    }

                    if (!href) {
                        continue;
                    }

                    let pathname = '';
                    try {
                        pathname = new URL(href, location.href).pathname || '';
                    } catch (error) {
                        continue;
                    }
                    const pathParts = pathname.split('/').filter(Boolean);
                    if (
                        pathParts.length < 2 ||
                        String(pathParts[pathParts.length - 2] || '').toLowerCase() !== 'casts' ||
                        !pathParts[pathParts.length - 1]
                    ) {
                        continue;
                    }
                    if (ignoredIds.has(String(pathParts[pathParts.length - 1] || '').toLowerCase())) {
                        continue;
                    }
                    if (searchRoot && !searchRoot.contains(link)) {
                        continue;
                    }

                    const text = (link.innerText || link.textContent || '').trim();
                    const image = link.querySelector('img');
                    const hasCardShape = Boolean(
                        image ||
                        link.classList.contains('block') ||
                        link.querySelector('.history-link') ||
                        link.closest('article, li, .card, .item, .avatar, .col, .col-md-2, .col-md-3, .col-sm-3, .col-xs-6')
                    );
                    if ((text || image) && hasCardShape) {
                        link.setAttribute('data-codex-actor-result-index', String(resultIndex));
                        rows.push({
                            href,
                            text,
                            has_image: Boolean(image),
                            index: resultIndex,
                        });
                        resultIndex += 1;
                    }
                }
                return rows;
            }
            """
        )
