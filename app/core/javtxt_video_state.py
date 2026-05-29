import re
from datetime import date, datetime

from app.core.javtxt_entry_state import (
    JAVTXT_SEARCH_STATE_FAILED,
    JAVTXT_SEARCH_STATE_NO_RESULT,
    JAVTXT_SEARCH_STATE_RESOLVED,
    classify_search_state,
)
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.services.video_category_service import VIDEO_CATEGORY_COLLECTION, normalize_video_category


JAVTXT_AUTHOR_MIN_RELEASE_DATE = date(2020, 1, 1)
VR_MARKER_RE = re.compile(r'v\s*r', re.IGNORECASE)

JAVTXT_VIDEO_STATE_COMPLETED = 'completed'
JAVTXT_VIDEO_STATE_FAILED = 'failed'
JAVTXT_VIDEO_STATE_NO_RESULT = 'no_result'
JAVTXT_VIDEO_STATE_PENDING = 'pending'


def normalize_javtxt_code(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def is_javtxt_eligible_movie(movie):
    code = normalize_javtxt_code((movie or {}).get('code', ''))
    if not code:
        return False
    if _is_collection_movie(movie):
        return False
    if _contains_vr_marker((movie or {}).get('title', '')):
        return False
    if _contains_vr_marker((movie or {}).get('javtxt_tags', '')):
        return False

    release_date_text = str((movie or {}).get('release_date', '') or '').strip()
    if not release_date_text:
        return False

    try:
        release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
    except ValueError:
        return False

    return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE


def _is_collection_movie(movie):
    return normalize_video_category((movie or {}).get('video_category', '')) == VIDEO_CATEGORY_COLLECTION


def _contains_vr_marker(value):
    normalized_text = str(value or '').replace('Ｖ', 'V').replace('Ｒ', 'R')
    return bool(VR_MARKER_RE.search(normalized_text))


def get_javtxt_cache_row(cache_rows, movie):
    code = normalize_javtxt_code((movie or {}).get('code', ''))
    if not code:
        return {}
    return dict((cache_rows or {}).get(code, {}) or {})


def classify_javtxt_movie(movie, cached_row=None):
    search_state = classify_search_state(movie, cached_row=cached_row)
    if search_state == JAVTXT_SEARCH_STATE_NO_RESULT:
        return JAVTXT_VIDEO_STATE_NO_RESULT
    if search_state == JAVTXT_SEARCH_STATE_RESOLVED:
        return JAVTXT_VIDEO_STATE_COMPLETED
    if search_state == JAVTXT_SEARCH_STATE_FAILED:
        return JAVTXT_VIDEO_STATE_FAILED
    return JAVTXT_VIDEO_STATE_PENDING


def summarize_javtxt_movies(movies, cache_rows=None):
    summary = {
        'total_count': 0,
        'enriched_count': 0,
        'pending_count': 0,
        'failed_count': 0,
        'no_search_count': 0,
    }

    for movie in movies or []:
        if not is_javtxt_eligible_movie(movie):
            continue

        summary['total_count'] += 1
        state = classify_javtxt_movie(movie, get_javtxt_cache_row(cache_rows, movie))
        if state == JAVTXT_VIDEO_STATE_COMPLETED:
            summary['enriched_count'] += 1
        elif state == JAVTXT_VIDEO_STATE_NO_RESULT:
            summary['enriched_count'] += 1
            summary['no_search_count'] += 1
        elif state == JAVTXT_VIDEO_STATE_FAILED:
            summary['failed_count'] += 1
        else:
            summary['pending_count'] += 1

    return summary


def build_javtxt_library_status(movies, cache_rows=None):
    summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
    if summary['total_count'] <= 0:
        return UNENRICHED_STATUS
    if summary['pending_count'] > 0:
        return UNENRICHED_STATUS
    if summary['failed_count'] > 0:
        return FAILED_STATUS
    return ENRICHED_STATUS
