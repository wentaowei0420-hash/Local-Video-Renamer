from threading import Lock
from time import monotonic

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_video_state import summarize_javtxt_movies
from app.core.video_code import standardize_video_code
from app.services.code_prefix_library import CodePrefixLibrary


class DataCenterService:
    SUMMARY_CACHE_TTL_SECONDS = 5.0

    def __init__(self, database):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)
        self._summary_cache = None
        self._summary_cache_expires_at = 0.0
        self._summary_cache_lock = Lock()

    def get_summary(self):
        now = monotonic()
        if self._summary_cache is not None and now < self._summary_cache_expires_at:
            return self._summary_cache

        with self._summary_cache_lock:
            now = monotonic()
            if self._summary_cache is not None and now < self._summary_cache_expires_at:
                return self._summary_cache

            summary = self._build_summary()
            self._summary_cache = summary
            self._summary_cache_expires_at = now + self.SUMMARY_CACHE_TTL_SECONDS
            return summary

    def _build_summary(self):
        return {
            'video_library': {
                'label': '视频库',
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_video_source_summary(AVFAN_VIDEO_SOURCE),
                    JAVTXT_VIDEO_SOURCE: self._build_video_source_summary(JAVTXT_VIDEO_SOURCE),
                },
            },
            'code_prefix_library': {
                'label': '番号库',
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_code_prefix_source_summary(AVFAN_VIDEO_SOURCE),
                    JAVTXT_VIDEO_SOURCE: self._build_code_prefix_source_summary(JAVTXT_VIDEO_SOURCE),
                },
            },
            'actor_library': {
                'label': '演员库',
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_actor_source_summary(AVFAN_VIDEO_SOURCE),
                    JAVTXT_VIDEO_SOURCE: self._build_actor_source_summary(JAVTXT_VIDEO_SOURCE),
                },
            },
        }

    def _build_video_source_summary(self, source_key):
        summary = self.database.get_video_enrichment_summary(source_key)
        total_count = int(summary.get('total_count', 0) or 0)
        enriched_count = int(summary.get('enriched_count', 0) or 0)
        success_count = int(summary.get('success_count', enriched_count) or 0)
        pending_count = int(summary.get('pending_count', summary.get('unenriched_count', 0)) or 0)
        result = {
            'label': f'视频库 · {get_video_enrichment_source_label(source_key)}',
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': '已完成',
        }
        result['failed_count'] = int(summary.get('failed_count', 0) or 0)
        result['no_search_count'] = int(summary.get('no_search_count', 0) or 0)
        result['no_detail_count'] = int(summary.get('no_detail_count', 0) or 0)
        return result

    def _build_code_prefix_source_summary(self, source_key):
        if source_key == JAVTXT_VIDEO_SOURCE:
            prefixes = [
                str(row.get('prefix', '')).strip().upper()
                for row in self.code_prefix_library.list_prefixes()
                if str(row.get('prefix', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                f'番号库 · {get_video_enrichment_source_label(source_key)}',
                self.database.list_code_prefix_movies_by_prefixes(prefixes),
            )

        records = self.database.list_code_prefix_enrichment_records()
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in self.code_prefix_library.list_prefixes()
            if row.get('prefix')
        ]
        return self._build_status_summary(
            f'番号库 · {get_video_enrichment_source_label(source_key)}',
            statuses,
        )

    def _build_actor_source_summary(self, source_key):
        if source_key == JAVTXT_VIDEO_SOURCE:
            actor_names = [
                str(row.get('name', '')).strip()
                for row in self.database.list_actors()
                if str(row.get('name', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                f'演员库 · {get_video_enrichment_source_label(source_key)}',
                self.database.list_actor_movies_by_names(actor_names),
            )

        records = self.database.list_actor_enrichment_records()
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in self.database.list_actors()
            if str(row.get('name', '')).strip()
        ]
        return self._build_status_summary(
            f'演员库 · {get_video_enrichment_source_label(source_key)}',
            statuses,
        )

    def _build_status_summary(self, label, statuses):
        total_count = len(statuses)
        success_count = sum(1 for status in statuses if status == ENRICHED_STATUS)
        failed_count = sum(1 for status in statuses if status == FAILED_STATUS)
        no_search_count = sum(1 for status in statuses if status == NO_SEARCH_RESULTS_STATUS)
        no_detail_count = sum(1 for status in statuses if status == NO_VIDEO_DETAIL_STATUS)
        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': '已完成',
        }

    def _build_javtxt_library_video_summary(self, label, movies_by_group):
        eligible_movies = [
            movie
            for movies in (movies_by_group or {}).values()
            for movie in (movies or [])
        ]
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in eligible_movies]
        )
        summary = summarize_javtxt_movies(eligible_movies, cache_rows=cache_rows)
        return {
            'label': label,
            'total_count': summary['total_count'],
            'enriched_count': summary['enriched_count'],
            'success_count': summary['success_count'],
            'pending_count': summary['pending_count'],
            'failed_count': summary['failed_count'],
            'no_search_count': summary['no_search_count'],
            'no_detail_count': summary['no_detail_count'],
            'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
            'count_label': '已完成视频',
            'pending_label': '待补全视频',
        }

    @staticmethod
    def _get_source_status(record, source_key):
        key = 'javtxt_enrichment_status' if source_key == JAVTXT_VIDEO_SOURCE else 'avfan_enrichment_status'
        return str((record or {}).get(key, '') or '').strip() or UNENRICHED_STATUS


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
