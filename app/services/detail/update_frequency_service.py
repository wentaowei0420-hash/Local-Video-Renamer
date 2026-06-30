import re
from datetime import date


_DATE_RE = re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})')


def calculate_update_frequency(rows):
    dated_rows = []
    for row in rows or []:
        release_date = _parse_release_date((row or {}).get('release_date', ''))
        if release_date is not None:
            dated_rows.append(release_date)

    if not dated_rows:
        return {
            'video_count': 0,
            'month_count': 0,
            'videos_per_month': None,
        }

    earliest_release = min(dated_rows)
    latest_release = max(dated_rows)
    month_count = ((latest_release.year - earliest_release.year) * 12) + (latest_release.month - earliest_release.month) + 1
    video_count = len(dated_rows)
    return {
        'video_count': video_count,
        'month_count': month_count,
        'videos_per_month': video_count / month_count if month_count > 0 else None,
    }


def _parse_release_date(value):
    text = str(value or '').strip()
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
