from app.core.ladder_board import LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX
from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.video_code import standardize_video_code
from app.services.detail import (
    build_code_prefix_detail_web_url,
    build_video_category_distribution,
    count_uncategorized_video_rows,
    resolve_update_status,
)
from app.services.detail.update_frequency_service import calculate_update_frequency
from app.services.identity import split_actor_names
from app.services.library import extract_code_prefix


class CodePrefixDetailLibrary:
    def __init__(self, database, video_ladder_tag_service=None, video_filter_service=None):
        self.database = database
        self.video_ladder_tag_service = video_ladder_tag_service
        self.video_filter_service = video_filter_service

    def get_prefix_detail(self, prefix):
        prefix = str(prefix or '').strip().upper()
        if not prefix:
            raise ValueError('缺少番号前缀')

        enrichment = self.database.get_code_prefix_enrichment_record(prefix)
        medal_maps = self._load_medal_maps()
        raw_local_videos = self._find_local_prefix_videos(prefix, medal_maps=medal_maps)
        local_videos = self._filter_visible_movies(raw_local_videos)
        raw_movies = self._enrich_rows(self.database.list_code_prefix_movies(prefix), medal_maps=medal_maps)
        movies = self._filter_visible_movies(self._filter_eligible_movies(raw_movies))
        eligible_movies = list(movies)
        earliest_release_date, latest_release_date = self._collect_date_range(movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in movies]
        )
        movie_summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        ladder_entry = self.database.get_ladder_entry(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, prefix)

        return {
            'prefix': prefix,
            'web_url': build_code_prefix_detail_web_url(prefix),
            'ladder_tier': str((ladder_entry or {}).get('tier', '') or '').strip().upper(),
            'update_status': resolve_update_status(local_videos + eligible_movies),
            'video_count': len(local_videos),
            'eligible_video_count': len(eligible_movies),
            'eligible_enriched_video_count': movie_summary['enriched_count'],
            'enrichment_status': self._build_live_enrichment_status(enrichment, movies, cache_rows),
            'avfan_total_pages': enrichment.get('avfan_total_pages', 0),
            'avfan_total_videos': enrichment.get('avfan_total_videos', 0),
            'last_enriched_at': enrichment.get('last_enriched_at', ''),
            'update_frequency': calculate_update_frequency(eligible_movies),
            'earliest_release_date': earliest_release_date,
            'latest_release_date': latest_release_date,
            'year_distribution': self._build_year_distribution(eligible_movies),
            'top_actors': self._build_top_actors(eligible_movies),
            'video_category_distribution': build_video_category_distribution(eligible_movies),
            'uncategorized_eligible_video_count': count_uncategorized_video_rows(eligible_movies),
            'local_videos': local_videos,
            'movies': movies,
            'eligible_movies': eligible_movies,
            'raw_local_video_count': len(raw_local_videos),
            'raw_video_count': len(raw_movies),
        }

    def _find_local_prefix_videos(self, prefix, medal_maps=None):
        if hasattr(self.database, 'list_local_videos_by_prefix'):
            try:
                local_rows = self.database.list_local_videos_by_prefix(prefix, refresh_categories=False)
            except TypeError:
                local_rows = self.database.list_local_videos_by_prefix(prefix)
            return self._enrich_rows(
                local_rows,
                medal_maps=medal_maps,
            )
        matched = []
        for row in self._enrich_rows(self.database.list_videos(), medal_maps=medal_maps):
            if extract_code_prefix(row.get('code', '')) == prefix:
                matched.append(row)
        return matched

    def _filter_eligible_movies(self, movies):
        return [movie for movie in (movies or []) if self._is_eligible_movie(movie)]

    def _filter_visible_movies(self, movies):
        if self.video_filter_service is None:
            return list(movies or [])
        return self.video_filter_service.filter_video_rows(movies)

    def _load_medal_maps(self):
        if self.video_ladder_tag_service is None:
            return None
        return self.video_ladder_tag_service.load_medal_maps()

    def _enrich_rows(self, rows, medal_maps=None):
        if self.video_ladder_tag_service is None:
            return list(rows or [])
        return self.video_ladder_tag_service.enrich_video_rows(rows, medal_maps=medal_maps)

    def _build_live_enrichment_status(self, enrichment, movies, cache_rows):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '')).strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '')).strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(movies, cache_rows=cache_rows)

        return build_library_enrichment_status_text(avfan_status, javtxt_status)

    def _collect_date_range(self, movies):
        dates = sorted(
            movie.get('release_date', '').strip()
            for movie in movies
            if str(movie.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    def _build_year_distribution(self, movies):
        grouped = {}
        for movie in movies:
            release_date = str(movie.get('release_date', '')).strip()
            year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else '未知'
            grouped[year] = grouped.get(year, 0) + 1

        known_items = [(year, count) for year, count in grouped.items() if year != '未知']
        unknown_items = [(year, count) for year, count in grouped.items() if year == '未知']
        known_items.sort(key=lambda item: (-int(item[0]), -item[1], item[0]))
        ordered = known_items + unknown_items
        return [{'year': year, 'video_count': count} for year, count in ordered]

    def _build_top_actors(self, movies):
        grouped = {}
        for movie in movies:
            author = str(movie.get('author', '')).strip()
            if not author:
                continue
            actor_names = split_actor_names(author) or [author]
            for actor_name in actor_names:
                normalized = str(actor_name or '').strip()
                if not normalized:
                    continue
                grouped[normalized] = grouped.get(normalized, 0) + 1

        ordered = sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        return [{'name': name, 'video_count': count} for name, count in ordered[:14]]

    @staticmethod
    def _is_eligible_movie(movie):
        return is_javtxt_eligible_movie(movie)
