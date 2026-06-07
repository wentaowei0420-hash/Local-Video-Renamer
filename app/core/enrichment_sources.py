from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
)


AVFAN_VIDEO_SOURCE = 'avfan'
JAVTXT_VIDEO_SOURCE = 'javtxt'
DEFAULT_VIDEO_ENRICHMENT_SOURCE = AVFAN_VIDEO_SOURCE


VIDEO_ENRICHMENT_SOURCE_LABELS = {
    AVFAN_VIDEO_SOURCE: '天陨阁',
    JAVTXT_VIDEO_SOURCE: '辛聚谷',
}


def normalize_video_enrichment_source(source_key):
    if source_key in VIDEO_ENRICHMENT_SOURCE_LABELS:
        return source_key
    return DEFAULT_VIDEO_ENRICHMENT_SOURCE


def get_video_enrichment_source_label(source_key):
    return VIDEO_ENRICHMENT_SOURCE_LABELS[normalize_video_enrichment_source(source_key)]


def build_video_enrichment_status_text(avfan_status, javtxt_status):
    normalized_avfan = normalize_video_enrichment_status(avfan_status)
    normalized_javtxt = normalize_video_enrichment_status(javtxt_status)
    return (
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[AVFAN_VIDEO_SOURCE]}: {normalized_avfan} | '
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[JAVTXT_VIDEO_SOURCE]}: {normalized_javtxt}'
    )


def build_library_enrichment_status_text(avfan_status, javtxt_status):
    normalized_avfan = normalize_video_enrichment_status(avfan_status)
    normalized_javtxt = normalize_video_enrichment_status(javtxt_status)
    return (
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[AVFAN_VIDEO_SOURCE]}: {normalized_avfan} | '
        f'{VIDEO_ENRICHMENT_SOURCE_LABELS[JAVTXT_VIDEO_SOURCE]}: {normalized_javtxt}'
    )


def normalize_video_enrichment_status(status):
    text = str(status or '').strip()
    return text or UNENRICHED_STATUS


def build_video_remaining_label(source_key):
    return f'剩余未用{get_video_enrichment_source_label(source_key)}补全视频'


def is_effective_video_success_status(status):
    return normalize_video_enrichment_status(status) == ENRICHED_STATUS


def is_effective_video_pending_status(status):
    return normalize_video_enrichment_status(status) in (UNENRICHED_STATUS, FAILED_STATUS)


def is_effective_video_terminal_status(status):
    normalized_status = normalize_video_enrichment_status(status)
    return normalized_status == ENRICHED_STATUS or is_no_result_status(normalized_status)
