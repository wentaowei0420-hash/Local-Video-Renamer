import argparse
import json
import re

from app.scraper.avfan_code_prefix_scraper import AvfanCodePrefixScraper
from app.scraper.avfan_actor_scraper import AvfanActorScraper
from app.scraper.avfan_scraper import (
    AVFAN_MOVIE_RE,
    AvfanScraper,
    accept_age_gate_if_needed,
    collect_search_results,
    extract_movie_id,
    is_login_page,
    is_security_verification_page,
    parse_movie_info_from_page,
    visible_lines,
    wait_for_manual_login_if_needed,
    wait_for_page_ready,
    wait_for_security_verification_if_needed,
)


NUMBER_LETTERS_RE = re.compile(r'/number_letters/([^/?#]+)', re.IGNORECASE)
PAGE_RE = re.compile(r'[?&]page=(\d+)', re.IGNORECASE)
CODE_RE = re.compile(r'[A-Z0-9]+-\d+', re.IGNORECASE)
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')


def probe_url(url, show_browser=False, max_lines=80, max_entries=20):
    browser = AvfanScraper(headless=not show_browser)
    prefix_scraper = AvfanCodePrefixScraper(headless=not show_browser)

    with browser.session() as page:
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        wait_for_security_verification_if_needed(page, browser.headless)
        accept_age_gate_if_needed(page)
        wait_for_security_verification_if_needed(page, browser.headless)
        wait_for_manual_login_if_needed(page, browser.headless)
        wait_for_page_ready(page)

        final_url = page.url
        lines = visible_lines(page)
        page_type = detect_page_type(final_url)
        result = {
            'requested_url': url,
            'final_url': final_url,
            'page_type': page_type,
            'page_title': safe_page_title(page),
            'is_login_page': is_login_page(page),
            'is_security_verification_page': is_security_verification_page(page),
            'visible_line_count': len(lines),
            'visible_lines_preview': lines[:max_lines],
        }

        if page_type == 'movie':
            movie_info = parse_movie_info_from_page(page)
            movie_info['avfan_movie_id'] = extract_movie_id(final_url)
            movie_info['avfan_url'] = final_url
            movie_info['found'] = bool(movie_info.get('code') or movie_info.get('title'))
            result['movie_info'] = movie_info

        elif page_type == 'code_prefix_listing':
            prefix = extract_listing_prefix(final_url)
            current_page = extract_page_number(final_url)
            raw_entries = prefix_scraper.collect_page_entries(page)[:max_entries]
            parsed_entries = parse_listing_entries(raw_entries)[:max_entries]
            result['code_prefix_listing'] = {
                'prefix': prefix,
                'current_page': current_page,
                'total_pages': prefix_scraper.detect_total_pages(page),
                'entry_count_on_current_page': len(raw_entries),
                'entries': parsed_entries,
                'raw_entries': raw_entries,
            }

        else:
            search_code = extract_first_code(lines)
            result['generic_links'] = {
                'guessed_search_code': search_code,
                'actor_links': AvfanActorScraper.collect_actor_result_links(page)[:max_entries],
                'movie_links': collect_search_results(page, search_code or '')[:max_entries],
            }

        return result


def detect_page_type(url):
    text = str(url or '').lower()
    if '/movies/' in text:
        return 'movie'
    if '/number_letters/' in text:
        return 'code_prefix_listing'
    return 'generic'


def extract_listing_prefix(url):
    match = NUMBER_LETTERS_RE.search(str(url or ''))
    return match.group(1).upper() if match else ''


def extract_page_number(url):
    match = PAGE_RE.search(str(url or ''))
    return int(match.group(1)) if match else 1


def extract_first_code(lines):
    for line in lines:
        match = CODE_RE.search(str(line or '').upper())
        if match:
            return match.group(0).upper()
    return ''


def parse_listing_entries(rows):
    entries = []
    for row in rows:
        text = str(row.get('text', '')).strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        code = extract_first_code(lines + [row.get('href', '')])
        release_date = extract_release_date(text)
        title = ''
        author = ''

        for line in lines:
            normalized = line.strip()
            if not normalized or normalized == code:
                continue
            if DATE_RE.search(normalized):
                continue
            if not title:
                title = normalized
                continue
            if not author:
                author = normalized
                break

        entries.append({
            'code': code,
            'title': title,
            'author': author,
            'release_date': release_date,
            'href': row.get('href', ''),
            'text': text,
        })
    return entries


def extract_release_date(text):
    match = DATE_RE.search(str(text or ''))
    return match.group(0) if match else ''


def safe_page_title(page):
    try:
        return page.title()
    except Exception:
        return ''


def parse_args():
    parser = argparse.ArgumentParser(description='Probe an AVFan page and print what can be extracted.')
    parser.add_argument('url', nargs='?', help='AVFan page URL to inspect')
    parser.add_argument('--show-browser', action='store_true', help='Show the browser window instead of headless mode')
    parser.add_argument('--max-lines', type=int, default=80, help='Maximum visible lines to include in preview')
    parser.add_argument('--max-entries', type=int, default=20, help='Maximum entries/links to include in output')
    return parser.parse_args()


def main():
    args = parse_args()
    url = args.url or input('请输入要测试的 AVFan 链接: ').strip()
    if not url:
        raise SystemExit('未提供链接，已取消。')

    result = probe_url(
        url=url,
        show_browser=args.show_browser,
        max_lines=max(1, int(args.max_lines or 80)),
        max_entries=max(1, int(args.max_entries or 20)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
