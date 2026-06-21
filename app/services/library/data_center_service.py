import re
from datetime import datetime
from threading import Lock

from app.core.actor_data_analysis import ACTOR_ANALYSIS_METRIC_MAP
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_video_state import summarize_javtxt_movies
from app.core.video_code import standardize_video_code
from app.services.library import CodePrefixLibrary, build_merged_movie_snapshot
from app.services.video import VideoFilterService


VIDEO_LIBRARY_LABEL = '\u89c6\u9891\u5e93'
CODE_PREFIX_LIBRARY_LABEL = '\u756a\u53f7\u5e93'
ACTOR_LIBRARY_LABEL = '\u6f14\u5458\u5e93'
COMPLETED_LABEL = '\u5df2\u5b8c\u6210'
COMPLETED_VIDEO_LABEL = '\u5df2\u5b8c\u6210\u89c6\u9891'
PENDING_VIDEO_LABEL = '\u5f85\u8865\u5168\u89c6\u9891'


class DataCenterService:
    def __init__(self, database, video_filter_service=None):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)
        self.video_filter_service = video_filter_service or VideoFilterService()
        self._summary_cache = None
        self._summary_cache_refreshed_at = ''
        self._summary_cache_lock = Lock()
        self._analysis_cache = {}
        self._analysis_cache_lock = Lock()

    def get_summary(self, force_refresh=False):
        return self.get_summary_snapshot(force_refresh=force_refresh)['summary']

    def get_summary_snapshot(self, force_refresh=False):
        with self._summary_cache_lock:
            if self._summary_cache is not None and not force_refresh:
                return {
                    'summary': self._summary_cache,
                    'refreshed_at': self._summary_cache_refreshed_at,
                }

            filter_settings = self._load_filter_settings()
            summary = self._build_summary(filter_settings=filter_settings)
            self._summary_cache = summary
            self._summary_cache_refreshed_at = self._current_cache_timestamp()
            return {
                'summary': summary,
                'refreshed_at': self._summary_cache_refreshed_at,
            }

    def get_actor_metric_analysis(self, metric_key, force_refresh=False):
        return self.get_actor_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)['analysis']

    def get_actor_metric_analysis_snapshot(self, metric_key, force_refresh=False):
        config = self._get_actor_metric_config(metric_key)
        metric_key = config['key']
        with self._analysis_cache_lock:
            cached = self._analysis_cache.get(metric_key)
            if cached is not None and not force_refresh:
                return dict(cached)

            payload = {
                'analysis': self._build_actor_metric_analysis(config),
                'refreshed_at': self._current_cache_timestamp(),
            }
            self._analysis_cache[metric_key] = payload
            return dict(payload)

    def _build_summary(self, filter_settings=None):
        return {
            'video_library': {
                'label': VIDEO_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_video_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_video_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
            'code_prefix_library': {
                'label': CODE_PREFIX_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
            'actor_library': {
                'label': ACTOR_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_actor_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_actor_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    BINGHUO_ACTOR_SOURCE: self._build_actor_source_summary(
                        BINGHUO_ACTOR_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
        }

    def _build_video_source_summary(self, source_key, filter_settings=None):
        label = self._build_source_label(VIDEO_LIBRARY_LABEL, source_key)
        visible_rows = self._list_visible_video_summary_rows(filter_settings=filter_settings)
        if source_key == JAVTXT_VIDEO_SOURCE:
            summary = summarize_javtxt_movies(visible_rows)
            return {
                'label': label,
                'total_count': summary['total_count'],
                'enriched_count': summary['enriched_count'],
                'success_count': summary['success_count'],
                'pending_count': summary['pending_count'],
                'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
                'count_label': COMPLETED_LABEL,
                'failed_count': summary['failed_count'],
                'no_search_count': summary['no_search_count'],
                'no_detail_count': summary['no_detail_count'],
            }
        return self._build_video_status_summary(label, visible_rows, 'avfan_enrichment_status')

    def _build_video_status_summary(self, label, rows, status_field):
        statuses = [str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS for row in rows or []]
        summary = self._build_status_summary(label, statuses)
        summary['count_label'] = COMPLETED_LABEL
        return summary

    def _build_code_prefix_source_summary(self, source_key, filter_settings=None):
        if source_key == JAVTXT_VIDEO_SOURCE:
            prefixes = [
                str(row.get('prefix', '')).strip().upper()
                for row in self.code_prefix_library.list_prefixes()
                if str(row.get('prefix', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key),
                self.database.list_code_prefix_movies_by_prefixes(prefixes),
                filter_settings=filter_settings,
            )

        records = self.database.list_code_prefix_enrichment_records()
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in self.code_prefix_library.list_prefixes()
            if row.get('prefix')
        ]
        return self._build_status_summary(self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key), statuses)

    def _build_actor_source_summary(self, source_key, filter_settings=None):
        if source_key == BINGHUO_ACTOR_SOURCE:
            return self._build_actor_binghuo_source_summary()
        if source_key == JAVTXT_VIDEO_SOURCE:
            actor_names = [
                str(row.get('name', '')).strip()
                for row in self.database.list_actors()
                if str(row.get('name', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(ACTOR_LIBRARY_LABEL, source_key),
                self.database.list_actor_movies_by_names(actor_names),
                filter_settings=filter_settings,
            )

        records = self.database.list_actor_enrichment_records()
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in self.database.list_actors()
            if str(row.get('name', '')).strip()
        ]
        return self._build_status_summary(self._build_source_label(ACTOR_LIBRARY_LABEL, source_key), statuses)

    def _build_actor_binghuo_source_summary(self):
        records = self.database.list_actor_enrichment_records()
        total_count = 0
        success_count = 0
        failed_count = 0
        no_search_count = 0
        no_detail_count = 0

        for row in self.database.list_actors():
            actor_name = str((row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            total_count += 1
            record = records.get(actor_name, {})
            status = str((record or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            if self._is_complete_binghuo_profile(record):
                success_count += 1
            elif status == NO_SEARCH_RESULTS_STATUS:
                no_search_count += 1
            elif status == NO_VIDEO_DETAIL_STATUS or self._is_incomplete_binghuo_profile(record):
                no_detail_count += 1
            elif status == FAILED_STATUS:
                failed_count += 1

        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': self._build_source_label(ACTOR_LIBRARY_LABEL, BINGHUO_ACTOR_SOURCE),
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': COMPLETED_LABEL,
        }

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
            'count_label': COMPLETED_LABEL,
        }

    def _build_javtxt_library_video_summary(self, label, movies_by_group, filter_settings=None):
        visible_movies = self._filter_visible_movies(
            [
                movie
                for movies in (movies_by_group or {}).values()
                for movie in (movies or [])
            ],
            filter_settings=filter_settings,
        )
        merged_movies = self._merge_movies_by_code(visible_movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in merged_movies]
        )
        summary = summarize_javtxt_movies(merged_movies, cache_rows=cache_rows)
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
            'count_label': COMPLETED_VIDEO_LABEL,
            'pending_label': PENDING_VIDEO_LABEL,
        }

    def _load_filter_settings(self):
        if self.video_filter_service is None:
            return None
        return self.video_filter_service.load_settings()

    def _build_actor_metric_analysis(self, config):
        distribution_counts = {}
        ranking_rows = []
        unknown_count = 0
        enrichment_records = self.database.list_actor_enrichment_records()

        for actor_row in self.database.list_actors():
            actor_name = str((actor_row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            numeric_value, display_value = self._resolve_actor_metric_value(
                config,
                actor_row,
                enrichment_records.get(actor_name, {}),
            )
            if numeric_value is None:
                unknown_count += 1
                continue
            distribution_counts[display_value] = distribution_counts.get(display_value, 0) + 1
            ranking_rows.append(
                {
                    'actor_name': actor_name,
                    'display_value': display_value,
                    'numeric_value': numeric_value,
                }
            )

        distribution_rows = [
            {'label': label, 'count': count}
            for label, count in sorted(
                distribution_counts.items(),
                key=lambda item: (-self._parse_metric_number(item[0]), item[0]),
            )
        ]
        if unknown_count > 0:
            distribution_rows.append({'label': '无数据', 'count': unknown_count})

        ranking_rows.sort(key=lambda item: (-item['numeric_value'], item['actor_name']))
        return {
            'metric_key': config['key'],
            'distribution_rows': distribution_rows,
            'ranking_rows': ranking_rows[:50],
        }

    @staticmethod
    def _resolve_actor_metric_value(config, actor_row, enrichment_record):
        source_name = str(config.get('source', '') or '').strip()
        field_name = str(config.get('field', '') or '').strip()
        suffix = str(config.get('suffix', '') or '')
        if source_name == 'enrichment':
            raw_value = str((enrichment_record or {}).get(field_name, '') or '').strip()
        else:
            raw_value = str(
                (actor_row or {}).get(f'raw_{field_name}', (actor_row or {}).get(field_name, '')) or ''
            ).strip()
        numeric_value = DataCenterService._parse_metric_number(raw_value)
        if numeric_value is None:
            return None, ''
        return numeric_value, f'{numeric_value}{suffix}'

    @staticmethod
    def _parse_metric_number(value):
        match = re.search(r'\d+', str(value or '').strip())
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _has_binghuo_physical_data(record):
        current = dict(record or {})
        return any(
            str(current.get(field_name, '') or '').strip()
            for field_name in ('binghuo_height', 'binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @classmethod
    def _is_complete_binghuo_profile(cls, record):
        current = dict(record or {})
        birthday = str(current.get('binghuo_birthday', '') or '').strip()
        return bool(birthday) and cls._has_binghuo_physical_data(current)

    @classmethod
    def _is_incomplete_binghuo_profile(cls, record):
        current = dict(record or {})
        has_any_profile_data = any(
            str(current.get(field_name, '') or '').strip()
            for field_name in (
                'binghuo_birthday',
                'binghuo_age',
                'binghuo_height',
                'binghuo_bust',
                'binghuo_waist',
                'binghuo_hip',
            )
        )
        return has_any_profile_data and not cls._is_complete_binghuo_profile(current)

    @staticmethod
    def _current_cache_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _get_actor_metric_config(metric_key):
        normalized_key = str(metric_key or '').strip()
        config = ACTOR_ANALYSIS_METRIC_MAP.get(normalized_key)
        if config is None:
            raise ValueError(f'Unknown actor analysis metric: {normalized_key}')
        return dict(config)

    def _list_visible_video_summary_rows(self, filter_settings=None):
        return self._filter_visible_movies(
            self.database.list_video_summary_rows(),
            filter_settings=filter_settings,
        )

    def _filter_visible_movies(self, rows, filter_settings=None):
        if self.video_filter_service is None:
            return list(rows or [])
        return self.video_filter_service.filter_video_rows(rows, settings=filter_settings)

    @staticmethod
    def _build_source_label(library_label, source_key):
        return f'{library_label} \u00b7 {get_video_enrichment_source_label(source_key)}'

    @staticmethod
    def _merge_movies_by_code(movies):
        movies_by_code = {}
        for movie in movies or []:
            normalized_code = standardize_video_code((movie or {}).get('code', ''))
            if not normalized_code:
                continue
            movies_by_code.setdefault(normalized_code, []).append(dict(movie or {}))

        merged_movies = []
        for normalized_code, rows in movies_by_code.items():
            merged_snapshot = build_merged_movie_snapshot(normalized_code, rows)
            if merged_snapshot:
                merged_movies.append(merged_snapshot)
            else:
                merged_movies.append(dict(rows[0] or {}))
        return merged_movies

    @staticmethod
    def _get_source_status(record, source_key):
        key = 'javtxt_enrichment_status' if source_key == JAVTXT_VIDEO_SOURCE else 'avfan_enrichment_status'
        return str((record or {}).get(key, '') or '').strip() or UNENRICHED_STATUS


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
