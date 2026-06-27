import re

from app.core.javtxt_video_state import COLLECTION_TITLE_KEYWORDS
from app.core.enrichment_status import UNENRICHED_STATUS
from app.services.video import COLLECTION_TAG_KEYWORDS


FILTER_FIELD_CODE = 'code'
FILTER_FIELD_TITLE = 'title'
FILTER_FIELD_JAVTXT_TAGS = 'javtxt_tags'
FILTER_FIELD_CO_STAR_CODE = 'co_star_code'

FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
    FILTER_FIELD_JAVTXT_TAGS,
    FILTER_FIELD_CO_STAR_CODE,
)

PRE_ENRICHMENT_FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
)

LIBRARY_HIDDEN_FILTER_FIELDS = (
    FILTER_FIELD_CODE,
    FILTER_FIELD_TITLE,
    FILTER_FIELD_JAVTXT_TAGS,
)

VR_FILTER_KEYWORD = 'VR'
DEFAULT_TITLE_FILTER_KEYWORDS = (
    VR_FILTER_KEYWORD,
    *COLLECTION_TITLE_KEYWORDS,
    *COLLECTION_TAG_KEYWORDS,
)
DEFAULT_JAVTXT_TAG_FILTER_KEYWORDS = (
    VR_FILTER_KEYWORD,
    *COLLECTION_TITLE_KEYWORDS,
    *COLLECTION_TAG_KEYWORDS,
)
VR_MARKER_RE = re.compile(r'(?<![A-Z0-9])V\s*R(?![A-Z0-9])', re.IGNORECASE)

DEFAULT_VIDEO_FILTER_SETTINGS = {
    'rules': {
        FILTER_FIELD_CODE: [],
        FILTER_FIELD_TITLE: list(DEFAULT_TITLE_FILTER_KEYWORDS),
        FILTER_FIELD_JAVTXT_TAGS: list(DEFAULT_JAVTXT_TAG_FILTER_KEYWORDS),
        FILTER_FIELD_CO_STAR_CODE: [],
    }
}


def normalize_video_filter_settings(settings):
    payload = dict(settings or {}) if isinstance(settings, dict) else {}
    raw_rules = payload.get('rules', payload)
    if not isinstance(raw_rules, dict):
        raw_rules = {}

    return {
        'rules': {
            field: _normalize_keyword_list(raw_rules.get(field, []))
            for field in FILTER_FIELDS
        }
    }


def get_filter_keywords(settings, field_name):
    normalized = normalize_video_filter_settings(settings)
    return list(normalized.get('rules', {}).get(field_name, []))


def matches_filter_keywords(value, keywords):
    raw_value = str(value or '').strip()
    if not raw_value:
        return False
    normalized_value = raw_value.lower()
    return any(_matches_single_keyword(raw_value, normalized_value, keyword) for keyword in _normalize_keyword_list(keywords))


def should_skip_video_before_enrichment(video, settings):
    normalized = normalize_video_filter_settings(settings)
    rules = normalized.get('rules', {})
    return any(
        matches_filter_keywords((video or {}).get(field_name, ''), rules.get(field_name, []))
        for field_name in PRE_ENRICHMENT_FILTER_FIELDS
    )


def should_hide_video_from_library(video, settings):
    if not is_post_enrichment_video(video):
        return False
    normalized = normalize_video_filter_settings(settings)
    rules = normalized.get('rules', {})
    return any(
        matches_filter_keywords((video or {}).get(field_name, ''), rules.get(field_name, []))
        for field_name in LIBRARY_HIDDEN_FILTER_FIELDS
    )


def _normalize_keyword_list(values):
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, (list, tuple)):
        values = []

    normalized = []
    seen = set()
    for value in values:
        keyword = str(value or '').strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
    return normalized


def _matches_single_keyword(raw_value, normalized_value, keyword):
    normalized_keyword = str(keyword or '').strip().lower()
    if not normalized_keyword:
        return False
    if normalized_keyword == VR_FILTER_KEYWORD.lower():
        normalized_text = raw_value.replace('Ｖ', 'V').replace('Ｒ', 'R')
        return bool(VR_MARKER_RE.search(normalized_text))
    return normalized_keyword in normalized_value


def is_post_enrichment_video(video):
    row = dict(video or {})
    if str(row.get('manual_tier', '') or '').strip():
        return True
    if any(
        str(row.get(field_name, '') or '').strip()
        for field_name in ('javtxt_movie_id', 'javtxt_url', 'javtxt_title', 'javtxt_actors', 'javtxt_tags')
    ):
        return True
    status = str(row.get('javtxt_enrichment_status', '') or '').strip()
    return bool(status) and status != UNENRICHED_STATUS
