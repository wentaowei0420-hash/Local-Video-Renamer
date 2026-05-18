import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from playwright_avfan_demo import collect_movie_info


HOME_URL = 'https://avfan.com/zh-CN'
OUTPUT_PATH = Path('avfan_search_demo_result.json')
SCREENSHOT_PATH = Path('avfan_search_demo_screenshot.png')
DEBUG_SCREENSHOT_PATH = Path('avfan_search_debug_no_input.png')


async def search_avfan_movie(code, open_first=True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(
            viewport={'width': 1440, 'height': 1200},
            locale='zh-CN',
        )

        print(f'打开首页: {HOME_URL}', flush=True)
        await page.goto(HOME_URL, wait_until='domcontentloaded', timeout=60000)
        await accept_age_gate_if_needed(page)
        await page.wait_for_timeout(1500)

        print(f'搜索番号: {code}', flush=True)
        await fill_search_box(page, code)
        await click_search_button(page)
        await wait_after_search(page)

        results = await collect_search_results(page, code)
        data = {
            'query': code,
            'search_url': page.url,
            'results_count': len(results),
            'results': results,
            'first_movie_info': None,
            'screenshot': str(SCREENSHOT_PATH),
        }

        if open_first and results:
            print(f'打开第一个结果: {results[0]["href"]}', flush=True)
            await page.goto(results[0]['href'], wait_until='domcontentloaded', timeout=60000)
            await wait_after_search(page)
            data['first_movie_info'] = await collect_movie_info(page)

        await page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        await browser.close()

        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
        print(f'已保存 JSON: {OUTPUT_PATH}', flush=True)
        print(f'已保存截图: {SCREENSHOT_PATH}', flush=True)
        return data


async def accept_age_gate_if_needed(page):
    candidates = (
        'text=是，我已经成年',
        'text=我已经成年',
        'text=Yes',
        'text=I am over',
    )
    for selector in candidates:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=2500):
                print('检测到成年确认弹窗，点击确认。', flush=True)
                await button.click()
                await page.wait_for_timeout(800)
                return
        except Exception:
            continue


async def fill_search_box(page, code):
    await reveal_search_box_if_needed(page)
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
            if await locator.is_visible(timeout=3000):
                await locator.click()
                await locator.fill(code)
                print(f'已填入搜索框: {selector}', flush=True)
                return
        except Exception:
            continue

    if await fill_search_box_by_js(page, code):
        print('已通过 JS 兜底填入搜索框。', flush=True)
        return

    await dump_search_debug(page)
    raise RuntimeError('未找到搜索输入框')


async def reveal_search_box_if_needed(page):
    click_candidates = (
        'text=搜索',
        'button:has-text("搜索")',
        'a:has-text("搜索")',
        '[aria-label*="搜索"]',
        '[class*="search"]',
    )
    for selector in click_candidates:
        try:
            target = page.locator(selector).first
            if await target.is_visible(timeout=1000):
                await target.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def fill_search_box_by_js(page, code):
    return await page.evaluate(
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
    )


async def dump_search_debug(page):
    await page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    debug = await page.evaluate(
        """
        () => ({
            url: location.href,
            inputs: Array.from(document.querySelectorAll('input')).map((node) => {
                const rect = node.getBoundingClientRect();
                return {
                    type: node.getAttribute('type') || '',
                    name: node.getAttribute('name') || '',
                    placeholder: node.getAttribute('placeholder') || '',
                    value: node.value || '',
                    visible: node.offsetParent !== null,
                    rect: {
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        left: Math.round(rect.left),
                        top: Math.round(rect.top)
                    }
                };
            }),
            buttons: Array.from(document.querySelectorAll('button, a')).slice(0, 80).map((node) => ({
                text: (node.innerText || node.textContent || '').trim(),
                href: node.getAttribute('href') || '',
                role: node.getAttribute('role') || '',
                aria: node.getAttribute('aria-label') || ''
            })).filter((item) => item.text || item.href || item.aria)
        })
        """
    )
    print('未找到搜索框，调试信息如下:', flush=True)
    print(json.dumps(debug, ensure_ascii=False, indent=2), flush=True)
    print(f'已保存调试截图: {DEBUG_SCREENSHOT_PATH}', flush=True)


async def click_search_button(page):
    search_button = page.get_by_role('button', name=re.compile('搜索|搜尋|Search', re.I)).first
    try:
        if await search_button.is_visible(timeout=3000):
            await search_button.click()
            return
    except Exception:
        pass

    await page.keyboard.press('Enter')


async def wait_after_search(page):
    try:
        await page.wait_for_load_state('networkidle', timeout=15000)
    except PlaywrightTimeoutError:
        print('等待 networkidle 超时，继续读取当前结果。', flush=True)
    await page.wait_for_timeout(1000)


async def collect_search_results(page, code):
    results = await page.evaluate(
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
        deduped.append({
            'code_matched': code.upper() in item.get('text', '').upper(),
            'text': item.get('text', ''),
            'href': href,
        })

    matched = [item for item in deduped if item['code_matched']]
    return matched or deduped[:20]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('code', nargs='?', default='HBS-005')
    parser.add_argument('--no-open-first', action='store_true')
    args = parser.parse_args()
    await search_avfan_movie(args.code, open_first=not args.no_open_first)


if __name__ == '__main__':
    asyncio.run(main())
