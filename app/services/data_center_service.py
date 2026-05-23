from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.services.code_prefix_library import CodePrefixLibrary


class DataCenterService:
    def __init__(self, database):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)

    def get_summary(self):
        return {
            'video_library': {
                'label': '视频库',
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_video_source_summary(AVFAN_VIDEO_SOURCE),
                    JAVTXT_VIDEO_SOURCE: self._build_video_source_summary(JAVTXT_VIDEO_SOURCE),
                },
            },
            'code_prefix_library': self._build_code_prefix_summary(),
            'actor_library': self._build_actor_summary(),
        }

    def _build_video_source_summary(self, source_key):
        summary = self.database.get_video_enrichment_summary(source_key)
        total_count = int(summary.get('total_count', 0) or 0)
        enriched_count = int(summary.get('enriched_count', 0) or 0)
        pending_count = int(summary.get('unenriched_count', 0) or 0)
        return {
            'label': VIDEO_SOURCE_LABELS.get(source_key, source_key),
            'total_count': total_count,
            'enriched_count': enriched_count,
            'pending_count': pending_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
        }

    def _build_code_prefix_summary(self):
        rows = self.code_prefix_library.list_prefixes()
        statuses = [str(row.get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS for row in rows]
        return self._build_status_summary('番号库', statuses)

    def _build_actor_summary(self):
        rows = self.database.list_actors()
        statuses = [str(row.get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS for row in rows]
        return self._build_status_summary('作者库', statuses)

    def _build_status_summary(self, label, statuses):
        total_count = len(statuses)
        enriched_count = sum(1 for status in statuses if status == ENRICHED_STATUS)
        failed_count = sum(1 for status in statuses if status == FAILED_STATUS)
        no_search_count = sum(1 for status in statuses if status == NO_SEARCH_RESULTS_STATUS)
        pending_count = max(total_count - enriched_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
        }


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)


VIDEO_SOURCE_LABELS = {
    AVFAN_VIDEO_SOURCE: '天陨阁',
    JAVTXT_VIDEO_SOURCE: '辛聚谷',
}
