from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.core.ladder_board import LADDER_TIER_A, LADDER_TIER_B, LADDER_TIER_C, LADDER_TIER_S


DETAIL_FILTER_ALL = 'all'
DETAIL_FILTER_PENDING = 'pending'
DETAIL_FILTER_FAILED = 'failed'
DETAIL_FILTER_ENRICHED = 'enriched'
DETAIL_FILTER_ACTIVE = 'active'
DETAIL_FILTER_SUSPECT = 'suspect'
DETAIL_FILTER_INACTIVE = 'inactive'
DETAIL_FILTER_AVFAN_PENDING = 'avfan_pending'
DETAIL_FILTER_AVFAN_FAILED = 'avfan_failed'
DETAIL_FILTER_AVFAN_ENRICHED = 'avfan_enriched'
DETAIL_FILTER_JAVTXT_PENDING = 'javtxt_pending'
DETAIL_FILTER_JAVTXT_FAILED = 'javtxt_failed'
DETAIL_FILTER_JAVTXT_ENRICHED = 'javtxt_enriched'
DETAIL_FILTER_TIER_S = 'tier_s'
DETAIL_FILTER_TIER_A = 'tier_a'
DETAIL_FILTER_TIER_B = 'tier_b'
DETAIL_FILTER_TIER_C = 'tier_c'
DETAIL_FILTER_MISSING_BIRTHDAY = 'missing_birthday'
DETAIL_FILTER_MISSING_AGE = 'missing_age'

BASE_DETAIL_FILTER_OPTIONS = (
    DETAIL_FILTER_ALL,
    DETAIL_FILTER_PENDING,
    DETAIL_FILTER_FAILED,
    DETAIL_FILTER_ENRICHED,
    DETAIL_FILTER_ACTIVE,
    DETAIL_FILTER_SUSPECT,
    DETAIL_FILTER_INACTIVE,
)

SOURCE_DETAIL_FILTER_OPTIONS = (
    DETAIL_FILTER_AVFAN_PENDING,
    DETAIL_FILTER_AVFAN_FAILED,
    DETAIL_FILTER_AVFAN_ENRICHED,
    DETAIL_FILTER_JAVTXT_PENDING,
    DETAIL_FILTER_JAVTXT_FAILED,
    DETAIL_FILTER_JAVTXT_ENRICHED,
)

TIER_DETAIL_FILTER_OPTIONS = (
    DETAIL_FILTER_TIER_S,
    DETAIL_FILTER_TIER_A,
    DETAIL_FILTER_TIER_B,
    DETAIL_FILTER_TIER_C,
)

ACTOR_DETAIL_FILTER_OPTIONS = (
    *BASE_DETAIL_FILTER_OPTIONS,
    *SOURCE_DETAIL_FILTER_OPTIONS,
    *TIER_DETAIL_FILTER_OPTIONS,
    DETAIL_FILTER_MISSING_BIRTHDAY,
    DETAIL_FILTER_MISSING_AGE,
)

CODE_PREFIX_DETAIL_FILTER_OPTIONS = (
    *BASE_DETAIL_FILTER_OPTIONS,
    *SOURCE_DETAIL_FILTER_OPTIONS,
    *TIER_DETAIL_FILTER_OPTIONS,
)


def filter_library_rows(rows, filter_key):
    normalized_key = str(filter_key or DETAIL_FILTER_ALL).strip().lower() or DETAIL_FILTER_ALL
    if normalized_key == DETAIL_FILTER_ALL:
        return list(rows or [])
    return [
        dict(row or {})
        for row in (rows or [])
        if matches_detail_filter(row, normalized_key)
    ]


def matches_detail_filter(row, filter_key):
    normalized_key = str(filter_key or DETAIL_FILTER_ALL).strip().lower() or DETAIL_FILTER_ALL
    if normalized_key == DETAIL_FILTER_ALL:
        return True

    avfan_status = _status_text((row or {}).get('avfan_enrichment_status', ''))
    javtxt_status = _status_text((row or {}).get('javtxt_enrichment_status', ''))
    update_status = _status_text((row or {}).get('update_status', ''))
    ladder_tier = _status_text((row or {}).get('ladder_tier', '')).upper()
    birthday = _status_text((row or {}).get('birthday', ''))
    raw_age = _status_text((row or {}).get('raw_age', (row or {}).get('age', '')))

    if normalized_key == DETAIL_FILTER_PENDING:
        return UNENRICHED_STATUS in (avfan_status, javtxt_status)
    if normalized_key == DETAIL_FILTER_FAILED:
        return FAILED_STATUS in (avfan_status, javtxt_status)
    if normalized_key == DETAIL_FILTER_ENRICHED:
        return avfan_status == ENRICHED_STATUS and javtxt_status == ENRICHED_STATUS
    if normalized_key == DETAIL_FILTER_AVFAN_PENDING:
        return avfan_status == UNENRICHED_STATUS
    if normalized_key == DETAIL_FILTER_AVFAN_FAILED:
        return avfan_status == FAILED_STATUS
    if normalized_key == DETAIL_FILTER_AVFAN_ENRICHED:
        return avfan_status == ENRICHED_STATUS
    if normalized_key == DETAIL_FILTER_JAVTXT_PENDING:
        return javtxt_status == UNENRICHED_STATUS
    if normalized_key == DETAIL_FILTER_JAVTXT_FAILED:
        return javtxt_status == FAILED_STATUS
    if normalized_key == DETAIL_FILTER_JAVTXT_ENRICHED:
        return javtxt_status == ENRICHED_STATUS
    if normalized_key == DETAIL_FILTER_ACTIVE:
        return update_status == 'active'
    if normalized_key == DETAIL_FILTER_SUSPECT:
        return update_status == 'suspect'
    if normalized_key == DETAIL_FILTER_INACTIVE:
        return update_status == 'inactive'
    if normalized_key == DETAIL_FILTER_TIER_S:
        return ladder_tier == LADDER_TIER_S
    if normalized_key == DETAIL_FILTER_TIER_A:
        return ladder_tier == LADDER_TIER_A
    if normalized_key == DETAIL_FILTER_TIER_B:
        return ladder_tier == LADDER_TIER_B
    if normalized_key == DETAIL_FILTER_TIER_C:
        return ladder_tier == LADDER_TIER_C
    if normalized_key == DETAIL_FILTER_MISSING_BIRTHDAY:
        return not birthday
    if normalized_key == DETAIL_FILTER_MISSING_AGE:
        return not raw_age
    return True


def _status_text(value):
    return str(value or '').strip()
