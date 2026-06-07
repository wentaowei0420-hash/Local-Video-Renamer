from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
)
from app.core.javtxt_entry_state import (
    JAVTXT_SEARCH_STATE_FAILED,
    JAVTXT_SEARCH_STATE_NO_RESULT,
    JAVTXT_SEARCH_STATE_RESOLVED,
    JAVTXT_SEARCH_STATE_UNSEARCHED,
    classify_actor_state,
    classify_search_state,
    has_detail_reference,
    normalize_actor_raw_text,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.services.video_category_service import normalize_video_category


SEARCH_STATE_PRIORITY = {
    JAVTXT_SEARCH_STATE_RESOLVED: 0,
    JAVTXT_SEARCH_STATE_NO_RESULT: 1,
    JAVTXT_SEARCH_STATE_FAILED: 2,
    JAVTXT_SEARCH_STATE_UNSEARCHED: 3,
}


def build_merged_movie_snapshot(code, library_rows, processed_row=None, cache_row=None):
    normalized_code = str(code or "").strip().upper()
    candidates = [dict(row or {}) for row in (library_rows or [])]
    processed_candidate = _build_processed_candidate(processed_row, cache_row)
    if processed_candidate:
        candidates.append(processed_candidate)

    if not candidates:
        return {}

    best_search_candidate, best_search_state = _pick_best_search_candidate(candidates)
    merged_status = _status_from_search_state(
        best_search_state,
        best_search_candidate.get("javtxt_enrichment_status", UNENRICHED_STATUS),
    )
    merged_author = _pick_best_author(candidates)
    merged_author_raw = _pick_best_author_raw(candidates, merged_author)

    return {
        "code": normalized_code,
        "title": _pick_best_title(normalized_code, candidates),
        "author": merged_author,
        "author_raw": merged_author_raw,
        "release_date": _pick_best_text(candidates, "release_date"),
        "javtxt_release_date": _pick_best_text(candidates, "javtxt_release_date"),
        "avfan_url": _pick_best_text(candidates, "avfan_url"),
        "javtxt_enrichment_status": merged_status,
        "javtxt_movie_id": _pick_best_text([best_search_candidate] + candidates, "javtxt_movie_id"),
        "javtxt_url": _pick_best_text([best_search_candidate] + candidates, "javtxt_url"),
        "javtxt_tags": _pick_best_text([best_search_candidate] + candidates, "javtxt_tags"),
        "video_category": _pick_best_category(candidates),
        "search_state": best_search_state,
    }


def merge_movie_row(existing_row, merged_snapshot):
    current = dict(existing_row or {})
    merged = dict(merged_snapshot or {})
    if not current or not merged:
        return current

    updated = dict(current)
    code = str(current.get("code", "") or "").strip().upper()

    best_title = str(merged.get("title", "") or "").strip()
    if _is_better_title(best_title, str(updated.get("title", "") or "").strip(), code):
        updated["title"] = best_title

    current_author = normalize_second_source_actor_text(updated.get("author", ""))
    merged_author = normalize_second_source_actor_text(merged.get("author", ""))
    current_author_raw = normalize_actor_raw_text(updated.get("author_raw", ""))
    merged_author_raw = normalize_actor_raw_text(merged.get("author_raw", ""))
    if _author_quality(merged_author, merged_author_raw) > _author_quality(current_author, current_author_raw):
        updated["author"] = merged_author
        updated["author_raw"] = merged_author_raw
    elif not current_author_raw and merged_author_raw:
        updated["author_raw"] = merged_author_raw

    if not str(updated.get("release_date", "") or "").strip() and str(merged.get("release_date", "") or "").strip():
        updated["release_date"] = str(merged.get("release_date", "") or "").strip()

    if not str(updated.get("javtxt_release_date", "") or "").strip() and str(merged.get("javtxt_release_date", "") or "").strip():
        updated["javtxt_release_date"] = str(merged.get("javtxt_release_date", "") or "").strip()

    if not str(updated.get("avfan_url", "") or "").strip() and str(merged.get("avfan_url", "") or "").strip():
        updated["avfan_url"] = str(merged.get("avfan_url", "") or "").strip()

    current_search_state = classify_search_state(updated, cached_row=updated)
    merged_search_state = str(merged.get("search_state", JAVTXT_SEARCH_STATE_UNSEARCHED) or JAVTXT_SEARCH_STATE_UNSEARCHED)
    if SEARCH_STATE_PRIORITY.get(merged_search_state, 99) <= SEARCH_STATE_PRIORITY.get(current_search_state, 99):
        merged_status = str(merged.get("javtxt_enrichment_status", "") or "").strip() or UNENRICHED_STATUS
        if str(updated.get("javtxt_enrichment_status", "") or "").strip() != merged_status:
            updated["javtxt_enrichment_status"] = merged_status
        if (
            SEARCH_STATE_PRIORITY.get(merged_search_state, 99) < SEARCH_STATE_PRIORITY.get(current_search_state, 99)
            or not str(updated.get("javtxt_movie_id", "") or "").strip()
        ) and str(merged.get("javtxt_movie_id", "") or "").strip():
            updated["javtxt_movie_id"] = str(merged.get("javtxt_movie_id", "") or "").strip()
        if (
            SEARCH_STATE_PRIORITY.get(merged_search_state, 99) < SEARCH_STATE_PRIORITY.get(current_search_state, 99)
            or not str(updated.get("javtxt_url", "") or "").strip()
        ) and str(merged.get("javtxt_url", "") or "").strip():
            updated["javtxt_url"] = str(merged.get("javtxt_url", "") or "").strip()
        merged_tags = str(merged.get("javtxt_tags", "") or "").strip()
        current_tags = str(updated.get("javtxt_tags", "") or "").strip()
        if _is_better_text(merged_tags, current_tags):
            updated["javtxt_tags"] = merged_tags

    current_category = normalize_video_category(updated.get("video_category", ""))
    merged_category = normalize_video_category(merged.get("video_category", ""))
    if not current_category and merged_category:
        updated["video_category"] = merged_category

    if not has_detail_reference(updated, cached_row=updated):
        updated["author"] = ""
        updated["author_raw"] = ""

    updated["author"] = normalize_second_source_actor_text(updated.get("author", ""))
    updated["author_raw"] = normalize_actor_raw_text(updated.get("author_raw", ""))
    updated["video_category"] = normalize_video_category(updated.get("video_category", ""))
    return updated


def has_movie_row_changes(before_row, after_row):
    keys = (
        "title",
        "author",
        "author_raw",
        "release_date",
        "avfan_url",
        "javtxt_enrichment_status",
        "javtxt_movie_id",
        "javtxt_url",
        "javtxt_tags",
        "javtxt_release_date",
        "video_category",
    )
    for key in keys:
        if str((before_row or {}).get(key, "") or "").strip() != str((after_row or {}).get(key, "") or "").strip():
            return True
    return False


def is_sync_eligible_movie(movie):
    return is_javtxt_eligible_movie(movie)


def clear_movie_javtxt_state(existing_row):
    current = dict(existing_row or {})
    if not current:
        return current
    updated = dict(current)
    updated["author"] = ""
    updated["author_raw"] = ""
    updated["javtxt_enrichment_status"] = UNENRICHED_STATUS
    updated["javtxt_movie_id"] = ""
    updated["javtxt_url"] = ""
    updated["javtxt_tags"] = ""
    return updated


def _build_processed_candidate(processed_row=None, cache_row=None):
    processed_row = dict(processed_row or {})
    cache_row = dict(cache_row or {})
    if not processed_row and not cache_row:
        return {}
    return {
        "code": str(processed_row.get("code", cache_row.get("code", "")) or "").strip().upper(),
        "title": str(processed_row.get("title", "") or "").strip(),
        "author": normalize_second_source_actor_text(
            cache_row.get("javtxt_actors", processed_row.get("author", ""))
        ),
        "author_raw": normalize_actor_raw_text(cache_row.get("javtxt_actors_raw", "")),
        "release_date": str(processed_row.get("release_date", "") or "").strip(),
        "javtxt_release_date": str(
            cache_row.get("javtxt_release_date", processed_row.get("javtxt_release_date", ""))
            or ""
        ).strip(),
        "avfan_url": "",
        "javtxt_enrichment_status": str(cache_row.get("javtxt_enrichment_status", "") or "").strip() or UNENRICHED_STATUS,
        "javtxt_movie_id": str(cache_row.get("javtxt_movie_id", "") or "").strip(),
        "javtxt_url": str(cache_row.get("javtxt_url", "") or "").strip(),
        "javtxt_tags": str(cache_row.get("javtxt_tags", processed_row.get("javtxt_tags", "")) or "").strip(),
        "video_category": normalize_video_category(processed_row.get("video_category", "")),
    }


def _pick_best_search_candidate(candidates):
    decorated = []
    for candidate in candidates or []:
        current = dict(candidate or {})
        search_state = classify_search_state(current, cached_row=current)
        actor_state = classify_actor_state(current, cached_row=current)
        decorated.append(
            (
                SEARCH_STATE_PRIORITY.get(search_state, 99),
                0 if normalize_second_source_actor_text(current.get("author", "")) else 1,
                0 if actor_state == "unpublished" else 1,
                0 if str(current.get("javtxt_url", "") or current.get("javtxt_movie_id", "")).strip() else 1,
                -len(str(current.get("javtxt_tags", "") or "").strip()),
                current,
                search_state,
            )
        )
    decorated.sort(key=lambda item: item[:5])
    best = decorated[0]
    return dict(best[5]), best[6]


def _pick_best_author(candidates):
    best_value = ""
    best_score = -1
    for candidate in candidates or []:
        if not has_detail_reference(candidate, cached_row=candidate):
            continue
        author = normalize_second_source_actor_text((candidate or {}).get("author", ""))
        author_raw = normalize_actor_raw_text((candidate or {}).get("author_raw", ""))
        score = _author_quality(author, author_raw)
        if score > best_score or (score == best_score and len(author) > len(best_value)):
            best_value = author
            best_score = score
    return best_value


def _pick_best_author_raw(candidates, merged_author):
    best_value = ""
    best_score = -1
    normalized_author = normalize_second_source_actor_text(merged_author)
    for candidate in candidates or []:
        if not has_detail_reference(candidate, cached_row=candidate):
            continue
        author = normalize_second_source_actor_text((candidate or {}).get("author", ""))
        author_raw = normalize_actor_raw_text((candidate or {}).get("author_raw", ""))
        score = _author_quality(author, author_raw)
        if normalized_author and author and author != normalized_author:
            continue
        if score > best_score or (score == best_score and len(author_raw) > len(best_value)):
            best_value = author_raw
            best_score = score
    return best_value


def _pick_best_title(code, candidates):
    best_title = ""
    for candidate in candidates or []:
        title = str((candidate or {}).get("title", "") or "").strip()
        if _is_better_title(title, best_title, code):
            best_title = title
    return best_title


def _pick_best_text(candidates, field_name):
    best_value = ""
    for candidate in candidates or []:
        value = str((candidate or {}).get(field_name, "") or "").strip()
        if _is_better_text(value, best_value):
            best_value = value
    return best_value


def _pick_best_category(candidates):
    for candidate in candidates or []:
        category = normalize_video_category((candidate or {}).get("video_category", ""))
        if category:
            return category
    return ""


def _status_from_search_state(search_state, fallback_status=UNENRICHED_STATUS):
    if search_state == JAVTXT_SEARCH_STATE_RESOLVED:
        return ENRICHED_STATUS
    if search_state == JAVTXT_SEARCH_STATE_NO_RESULT:
        normalized_fallback = str(fallback_status or "").strip()
        if is_no_result_status(normalized_fallback):
            return normalized_fallback
        return NO_SEARCH_RESULTS_STATUS
    if search_state == JAVTXT_SEARCH_STATE_FAILED:
        return FAILED_STATUS
    return UNENRICHED_STATUS


def _author_quality(author, author_raw):
    normalized_author = normalize_second_source_actor_text(author)
    normalized_raw = normalize_actor_raw_text(author_raw)
    if normalized_author:
        return 2
    if normalized_raw:
        return 1
    return 0


def _is_better_title(candidate, current, code):
    candidate_text = str(candidate or "").strip()
    current_text = str(current or "").strip()
    if not candidate_text:
        return False
    if not current_text:
        return True
    candidate_score = _title_score(candidate_text, code)
    current_score = _title_score(current_text, code)
    return candidate_score > current_score


def _title_score(title, code):
    normalized_title = str(title or "").strip()
    normalized_code = str(code or "").strip().upper()
    is_code_only = normalized_title.upper() == normalized_code
    return (0 if is_code_only else 1, len(normalized_title))


def _is_better_text(candidate, current):
    candidate_text = str(candidate or "").strip()
    current_text = str(current or "").strip()
    if not candidate_text:
        return False
    if not current_text:
        return True
    return len(candidate_text) > len(current_text)
