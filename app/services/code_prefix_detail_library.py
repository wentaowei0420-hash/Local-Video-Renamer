from datetime import datetime

from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.services.actor_identifier import split_actor_names
from app.services.movie_author_resolver import JAVTXT_AUTHOR_MIN_RELEASE_DATE


class CodePrefixDetailLibrary:
    def __init__(self, database):
        self.database = database

    def get_prefix_detail(self, prefix):
        prefix = str(prefix or '').strip().upper()
        if not prefix:
            raise ValueError('缺少番号前缀')

        enrichment = self.database.get_code_prefix_enrichment_record(prefix)
        movies = self.database.list_code_prefix_movies(prefix)
        eligible_movies = self._filter_eligible_movies(movies)
        enriched_eligible_count = self._count_enriched_eligible_movies(eligible_movies)
        earliest_release_date, latest_release_date = self._collect_date_range(movies)

        return {
            'prefix': prefix,
            'video_count': len(movies),
            'eligible_video_count': len(eligible_movies),
            'eligible_enriched_video_count': enriched_eligible_count,
            'enrichment_status': enrichment.get('enrichment_status', ''),
            'avfan_total_pages': enrichment.get('avfan_total_pages', 0),
            'avfan_total_videos': enrichment.get('avfan_total_videos', 0),
            'last_enriched_at': enrichment.get('last_enriched_at', ''),
            'earliest_release_date': earliest_release_date,
            'latest_release_date': latest_release_date,
            'year_distribution': self._build_year_distribution(eligible_movies),
            'top_actors': self._build_top_actors(eligible_movies),
            'movies': movies,
            'eligible_movies': eligible_movies,
        }

    def _filter_eligible_movies(self, movies):
        return [movie for movie in (movies or []) if self._is_eligible_movie(movie)]

    def _count_enriched_eligible_movies(self, movies):
        return sum(
            1
            for movie in (movies or [])
            if normalize_second_source_actor_text((movie or {}).get('author', ''))
        )

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
        return [{'name': name, 'video_count': count} for name, count in ordered[:10]]

    @staticmethod
    def _is_eligible_movie(movie):
        release_date_text = str((movie or {}).get('release_date', '') or '').strip()
        if not release_date_text:
            return False
        try:
            release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
        except ValueError:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE
