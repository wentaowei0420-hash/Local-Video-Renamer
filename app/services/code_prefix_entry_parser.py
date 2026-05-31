import re

from app.core.video_code import standardize_video_code

CODE_RE = re.compile(r'\b\d*[A-Z]+[A-Z0-9]*[-_ ]?\d+\b', re.IGNORECASE)
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
RATING_RE = re.compile(r'^\d+(?:\.\d+)?分$')
BADGE_TEXTS = ('有字幕', '有磁链', '48小时磁链')


def parse_code_prefix_card(text, href='', prefix='', page_number=1):
    raw_text = str(text or '').strip()
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    code = extract_code(raw_text)
    title_line = extract_title_line(lines, code)
    title, _author = split_title_and_author(title_line)
    release_date = extract_release_date(raw_text)

    return {
        'prefix': str(prefix or '').strip().upper(),
        'code': code,
        'title': title,
        'author': '',
        'title_with_author': title_line,
        'release_date': release_date,
        'avfan_url': str(href or '').strip(),
        'page_number': int(page_number or 1),
        'raw_text': raw_text,
    }


def extract_code(text):
    match = CODE_RE.search(str(text or '').upper())
    return standardize_video_code(match.group(0)) if match else ''


def extract_release_date(text):
    match = DATE_RE.search(str(text or ''))
    return match.group(0) if match else ''


def extract_title_line(lines, code):
    normalized_code = str(code or '').upper()
    for line in lines:
        normalized_line = str(line or '').strip()
        if not normalized_line:
            continue
        if normalized_code and normalized_line.upper() == normalized_code:
            continue
        if DATE_RE.search(normalized_line):
            continue
        if RATING_RE.match(normalized_line):
            continue
        if normalized_line in BADGE_TEXTS:
            continue
        return normalized_line
    return ''


def split_title_and_author(title_line):
    text = str(title_line or '').strip()
    if not text:
        return '', ''

    parts = [part.strip() for part in re.split(r'\s+', text) if part.strip()]
    if len(parts) <= 1:
        return text, ''

    author = parts[-1]
    title = text[:text.rfind(author)].rstrip()
    return title or text, author
