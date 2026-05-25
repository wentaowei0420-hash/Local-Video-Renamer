from datetime import datetime

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.services.code_prefix_library import CodePrefixLibrary
from app.services.movie_author_resolver import JAVTXT_AUTHOR_MIN_RELEASE_DATE


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
        pending_count = int(summary.get('unenriched_count', 0) or 0)
        return {
            'label': f'视频库·{get_video_enrichment_source_label(source_key)}',
            'total_count': total_count,
            'enriched_count': enriched_count,
            'pending_count': pending_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
        }

    def _build_code_prefix_source_summary(self, source_key):
        if source_key == JAVTXT_VIDEO_SOURCE:
            movies = []
            for row in self.code_prefix_library.list_prefixes():
                prefix = str(row.get('prefix', '')).strip().upper()
                if not prefix:
                    continue
                movies.extend(self.database.list_code_prefix_movies(prefix))
            return self._build_javtxt_movie_summary(
                f'番号库·{get_video_enrichment_source_label(source_key)}',
                movies,
            )

        records = self.database.list_code_prefix_enrichment_records()
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in self.code_prefix_library.list_prefixes()
            if row.get('prefix')
        ]
        return self._build_status_summary(
            f'番号库·{get_video_enrichment_source_label(source_key)}',
            statuses,
        )

    def _build_actor_source_summary(self, source_key):
        if source_key == JAVTXT_VIDEO_SOURCE:
            movies = []
            for row in self.database.list_actors():
                actor_name = str(row.get('name', '')).strip()
                if not actor_name:
                    continue
                movies.extend(self.database.list_actor_movies(actor_name))
            return self._build_javtxt_movie_summary(
                f'演员库·{get_video_enrichment_source_label(source_key)}',
                movies,
            )

        records = self.database.list_actor_enrichment_records()
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in self.database.list_actors()
            if str(row.get('name', '')).strip()
        ]
        return self._build_status_summary(
            f'演员库·{get_video_enrichment_source_label(source_key)}',
            statuses,
        )

    def _build_status_summary(self, label, statuses):
        total_count = len(statuses)
        enriched_count = sum(1 for status in statuses if status == ENRICHED_STATUS)
        failed_count = sum(1 for status in statuses if status == FAILED_STATUS)
        no_search_count = sum(1 for status in statuses if status == NO_SEARCH_RESULTS_STATUS)
        pending_count = max(total_count - enriched_count - failed_count - no_search_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
        }

    def _build_javtxt_movie_summary(self, label, movies):
        eligible_movies = [movie for movie in movies if self._is_javtxt_eligible_movie(movie)]
        total_count = len(eligible_movies)
        enriched_count = sum(
            1
            for movie in eligible_movies
            if normalize_second_source_actor_text((movie or {}).get('author', ''))
        )
        failed_count = 0
        no_search_count = 0
        pending_count = max(total_count - enriched_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': '已补全视频',
            'pending_label': '待补全视频',
        }

    @staticmethod
    def _get_source_status(record, source_key):
        key = 'javtxt_enrichment_status' if source_key == JAVTXT_VIDEO_SOURCE else 'avfan_enrichment_status'
        return str((record or {}).get(key, '') or '').strip() or UNENRICHED_STATUS

    @staticmethod
    def _is_javtxt_eligible_movie(movie):
        code = str((movie or {}).get('code', '') or '').strip().upper()
        if not code:
            return False
        release_date_text = str((movie or {}).get('release_date', '') or '').strip()
        if not release_date_text:
            return False
        try:
            release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
        except ValueError:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
