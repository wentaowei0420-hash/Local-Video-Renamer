import asyncio
import json
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


TARGET_URL = 'https://avfan.com/zh-CN/movies/NBZzjWgU'
OUTPUT_PATH = Path('avfan_demo_result.json')
SCREENSHOT_PATH = Path('avfan_demo_screenshot.png')


async def collect_avfan_page(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={'width': 1440, 'height': 1200},
            locale='zh-CN',
        )

        print(f'打开页面: {url}', flush=True)
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        print('DOM 已加载，等待页面主要内容...', flush=True)
        try:
            await page.wait_for_load_state('networkidle', timeout=15000)
            print('网络请求已稳定。', flush=True)
        except PlaywrightTimeoutError:
            print('等待 networkidle 超时，继续提取当前已渲染内容。', flush=True)

        await wait_for_body_text(page)
        print('开始提取页面信息...', flush=True)

        result = {
            'url': page.url,
            'title': await page.title(),
            'movie_info': await collect_movie_info(page),
            'meta': await collect_meta(page),
            'json_ld': await collect_json_ld(page),
            'headings': await collect_texts(page, 'h1, h2, h3'),
            'possible_fields': await collect_possible_fields(page),
            'links': await collect_links(page),
            'images': await collect_images(page),
            'visible_text_sample': await collect_visible_text_sample(page),
            'screenshot': str(SCREENSHOT_PATH),
        }

        await page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        await browser.close()
        print(f'已保存 JSON: {OUTPUT_PATH}', flush=True)
        print(f'已保存截图: {SCREENSHOT_PATH}', flush=True)
        return result


async def wait_for_body_text(page):
    try:
        await page.wait_for_function(
            "() => document.body && document.body.innerText.trim().length > 20",
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        print('页面正文等待超时，继续尝试提取。', flush=True)


async def collect_meta(page):
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('meta')).map((node) => ({
            name: node.getAttribute('name') || node.getAttribute('property') || '',
            content: node.getAttribute('content') || ''
        })).filter((item) => item.name || item.content)
        """
    )


async def collect_json_ld(page):
    raw_items = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
            .map((node) => node.textContent || '')
            .filter(Boolean)
        """
    )

    parsed_items = []
    for raw_item in raw_items:
        try:
            parsed_items.append(json.loads(raw_item))
        except json.JSONDecodeError:
            parsed_items.append({'raw': raw_item})
    return parsed_items


async def collect_texts(page, selector):
    return await page.evaluate(
        """
        (selector) => Array.from(document.querySelectorAll(selector))
            .map((node) => (node.innerText || node.textContent || '').trim())
            .filter(Boolean)
        """,
        selector,
    )


async def collect_possible_fields(page):
    labels = (
        '番号', '标题', '片名', '演员', '女优', '导演', '制作商', '发行商',
        '系列', '类别', '标签', '发行日期', '日期', '时长', '评分'
    )
    visible_text = await page.locator('body').inner_text(timeout=30000)
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]

    fields = {}
    for index, line in enumerate(lines):
        for label in labels:
            if label in line:
                nearby = lines[index:index + 4]
                fields.setdefault(label, []).append(' | '.join(nearby))

    return fields


async def collect_movie_info(page):
    visible_text = await page.locator('body').inner_text(timeout=30000)
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]

    title = await first_text(page, 'h1')
    info = {
        'title': title,
        'code': '',
        'release_date': '',
        'duration': '',
        'director': [],
        'maker': [],
        'label': [],
        'tags': [],
        'actors': [],
    }

    parse_visible_field_lines(info, lines)

    if missing_core_fields(info):
        for item in await collect_label_value_items(page):
            merge_labeled_value(info, item.get('label', ''), item.get('value', ''))

    return normalize_movie_info(info)


def parse_visible_field_lines(info, lines):
    field_aliases = movie_field_aliases()

    for line in lines:
        for field, aliases in field_aliases.items():
            matched_alias = next(
                (alias for alias in aliases if line.startswith(f'{alias}:') or line.startswith(f'{alias}：')),
                None,
            )
            if not matched_alias:
                continue

            value = line.split(':', 1)[1] if ':' in line else line.split('：', 1)[1]
            merge_field_value(info, field, value)


def merge_labeled_value(info, label, value):
    for field, aliases in movie_field_aliases().items():
        if any(alias in label for alias in aliases):
            merge_field_value(info, field, value)


def movie_field_aliases():
    return {
        'code': ('番号', '番號', '品番'),
        'release_date': ('发行日期', '發行日期', '发售日', '発売日', '日期'),
        'duration': ('片长', '片長', '时长', '時長', '収録時間'),
        'director': ('导演', '導演', '監督'),
        'maker': ('制作商', '製作商', 'メーカー'),
        'label': ('发行商', '發行商', '厂牌', 'レーベル'),
        'tags': ('标签', '標籤', '类别', '類別', 'ジャンル'),
        'actors': ('演员', '演員', '女优', '女優', '出演者'),
    }


def missing_core_fields(info):
    return not all((info.get('code'), info.get('release_date'), info.get('duration')))


async def first_text(page, selector):
    try:
        text = await page.locator(selector).first.inner_text(timeout=5000)
        return text.strip()
    except Exception:
        return ''


async def collect_label_value_items(page):
    return await page.evaluate(
        """
        () => {
            const labels = ['番号', '番號', '品番', '发行日期', '發行日期', '片长', '片長',
                '时长', '時長', '导演', '導演', '制作商', '製作商', '发行商', '發行商',
                '标签', '標籤', '演员', '演員'];
            const items = [];

            for (const node of Array.from(document.querySelectorAll('body *'))) {
                const text = (node.innerText || node.textContent || '').trim();
                if (!text) continue;

                const label = labels.find((candidate) => text.startsWith(candidate));
                if (!label) continue;

                const nearbyTexts = [];
                for (const child of Array.from(node.querySelectorAll('a, span, div')).slice(0, 20)) {
                    const childText = (child.innerText || child.textContent || '').trim();
                    if (childText && childText !== text) nearbyTexts.push(childText);
                }

                const cleaned = text.replace(label, '').replace(/^[\\s:：]+/, '').trim();
                items.push({
                    label,
                    value: nearbyTexts.length ? nearbyTexts.join(' ') : cleaned
                });
            }

            return items;
        }
        """
    )


def merge_field_value(info, field, value):
    value = normalize_value(value)
    if not value:
        return

    if isinstance(info[field], list):
        for part in split_multi_value(value):
            if part and part not in info[field]:
                info[field].append(part)
    elif not info[field]:
        info[field] = value


def normalize_movie_info(info):
    for field in ('director', 'maker', 'label', 'tags', 'actors'):
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


async def collect_links(page):
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).slice(0, 100).map((node) => ({
            text: (node.innerText || node.textContent || '').trim(),
            href: new URL(node.getAttribute('href'), location.href).href
        })).filter((item) => item.text || item.href)
        """
    )


async def collect_images(page):
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('img')).slice(0, 80).map((node) => ({
            alt: node.getAttribute('alt') || '',
            src: node.currentSrc || node.src || '',
            width: node.naturalWidth || 0,
            height: node.naturalHeight || 0
        })).filter((item) => item.src)
        """
    )


async def collect_visible_text_sample(page):
    visible_text = await page.locator('body').inner_text(timeout=30000)
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
    return lines[:120]


async def main():
    result = await collect_avfan_page(TARGET_URL)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
