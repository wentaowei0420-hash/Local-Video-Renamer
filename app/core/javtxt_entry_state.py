from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.second_source_actor_text import is_unpublished_actor_text, normalize_second_source_actor_text


JAVTXT_ACTOR_STATE_NAMED = 'named'
JAVTXT_ACTOR_STATE_UNPUBLISHED = 'unpublished'
JAVTXT_ACTOR_STATE_BLANK = 'blank'

JAVTXT_SEARCH_STATE_RESOLVED = 'resolved'
JAVTXT_SEARCH_STATE_NO_RESULT = 'no_result'
JAVTXT_SEARCH_STATE_FAILED = 'failed'
JAVTXT_SEARCH_STATE_UNSEARCHED = 'unsearched'


def normalize_actor_raw_text(value):
    return ' '.join(str(value or '').replace('\u3000', ' ').split()).strip()


def resolve_actor_texts(record=None, cached_row=None):
    record = dict(record or {})
    cached_row = dict(cached_row or {})
    display_text = normalize_second_source_actor_text(
        record.get('author', cached_row.get('javtxt_actors', ''))
    )
    raw_text = normalize_actor_raw_text(
        record.get(
            'author_raw',
            cached_row.get(
                'javtxt_actors_raw',
                record.get('javtxt_actors', cached_row.get('javtxt_actors', record.get('author', ''))),
            ),
        )
    )
    return display_text, raw_text


def classify_actor_state(record=None, cached_row=None):
    display_text, raw_text = resolve_actor_texts(record, cached_row=cached_row)
    if display_text:
        return JAVTXT_ACTOR_STATE_NAMED
    if is_unpublished_actor_text(raw_text):
        return JAVTXT_ACTOR_STATE_UNPUBLISHED
    return JAVTXT_ACTOR_STATE_BLANK


def normalize_javtxt_search_status(value):
    text = str(value or '').strip()
    return text or UNENRICHED_STATUS


def has_detail_reference(record=None, cached_row=None):
    record = dict(record or {})
    cached_row = dict(cached_row or {})
    return bool(
        str(record.get('javtxt_movie_id', cached_row.get('javtxt_movie_id', '')) or '').strip()
        or str(record.get('javtxt_url', cached_row.get('javtxt_url', '')) or '').strip()
    )


def classify_search_state(record=None, cached_row=None):
    record = dict(record or {})
    cached_row = dict(cached_row or {})
    status = normalize_javtxt_search_status(
        record.get('javtxt_enrichment_status', cached_row.get('javtxt_enrichment_status', ''))
    )
    actor_state = classify_actor_state(record, cached_row=cached_row)
    detail_found = has_detail_reference(record, cached_row=cached_row)

    if actor_state in (JAVTXT_ACTOR_STATE_NAMED, JAVTXT_ACTOR_STATE_UNPUBLISHED):
        return JAVTXT_SEARCH_STATE_RESOLVED
    if status == NO_SEARCH_RESULTS_STATUS:
        return JAVTXT_SEARCH_STATE_NO_RESULT
    if status == FAILED_STATUS and not detail_found:
        return JAVTXT_SEARCH_STATE_FAILED
    if status == ENRICHED_STATUS and detail_found:
        return JAVTXT_SEARCH_STATE_RESOLVED
    if status == FAILED_STATUS and detail_found:
        return JAVTXT_SEARCH_STATE_RESOLVED
    return JAVTXT_SEARCH_STATE_UNSEARCHED


def is_resolved_search_state(search_state):
    return search_state in (
        JAVTXT_SEARCH_STATE_RESOLVED,
        JAVTXT_SEARCH_STATE_NO_RESULT,
    )


def is_retryable_search_state(search_state):
    return search_state in (
        JAVTXT_SEARCH_STATE_FAILED,
        JAVTXT_SEARCH_STATE_UNSEARCHED,
    )


def classify_entry_state(record=None, cached_row=None):
    return {
        'actor_state': classify_actor_state(record, cached_row=cached_row),
        'search_state': classify_search_state(record, cached_row=cached_row),
    }


def is_manual_category_candidate(record=None, cached_row=None):
    return classify_actor_state(record, cached_row=cached_row) in (
        JAVTXT_ACTOR_STATE_NAMED,
        JAVTXT_ACTOR_STATE_UNPUBLISHED,
    )
