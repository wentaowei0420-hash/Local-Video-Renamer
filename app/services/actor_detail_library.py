import re

from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.services.actor_identifier import split_actor_names
from app.services.code_prefix_library import extract_code_prefix


YEAR_RE = re.compile(r'(19|20)\d{2}')


class ActorDetailLibrary:
    def __init__(self, database):
        self.database = database

    def get_actor_detail(self, actor_name):
        actor_name = str(actor_name or '').strip()
        if not actor_name:
            raise ValueError('缺少演员姓名')

        actor_row = self._find_actor(actor_name)
        local_videos = self._find_local_actor_videos(actor_name)
        web_movies = self.database.list_actor_movies(actor_name)
        eligible_web_movies = self._filter_eligible_movies(web_movies)
        web_record = self.database.get_actor_enrichment_record(actor_name)
        web_earliest, web_latest = self._collect_date_range(web_movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [str((movie or {}).get('code', '') or '').strip().upper() for movie in web_movies]
        )
        web_summary = summarize_javtxt_movies(web_movies, cache_rows=cache_rows)

        return {
            'name': actor_name,
            'birthday': actor_row.get('birthday', ''),
            'age': actor_row.get('age', ''),
            'matched': bool(actor_row.get('matched')),
            'actor_id': actor_row.get('actor_id', '') or web_record.get('actor_id', ''),
            'local_video_count': len(local_videos),
            'local_prefix_distribution': self._build_prefix_distribution(local_videos),
            'local_year_distribution': self._build_year_distribution(local_videos),
            'web_enrichment_status': self._build_live_web_enrichment_status(web_record, web_movies, cache_rows),
            'web_total_pages': web_record.get('avfan_total_pages', 0),
            'web_total_videos': web_record.get('avfan_total_videos', 0),
            'eligible_video_count': len(eligible_web_movies),
            'eligible_enriched_video_count': web_summary['enriched_count'],
            'web_last_enriched_at': web_record.get('last_enriched_at', ''),
            'web_earliest_release_date': web_earliest,
            'web_latest_release_date': web_latest,
            'web_prefix_distribution': self._build_prefix_distribution(eligible_web_movies),
            'web_year_distribution': self._build_year_distribution(eligible_web_movies),
            'local_videos': local_videos,
            'web_movies': web_movies,
            'eligible_web_movies': eligible_web_movies,
        }

    def _find_actor(self, actor_name):
        for row in self.database.list_actors(actor_name):
            if str(row.get('name', '')).strip() == actor_name:
                return row
        return {
            'name': actor_name,
            'birthday': '',
            'age': '',
            'matched': False,
        }

    def _find_local_actor_videos(self, actor_name):
        matched = []
        for row in self.database.list_videos():
            actor_names = split_actor_names(row.get('author', ''))
            if actor_name in actor_names:
                matched.append(row)
        return matched

    def _filter_eligible_movies(self, rows):
        return [row for row in (rows or []) if self._is_eligible_movie(row)]

    def _build_live_web_enrichment_status(self, enrichment, movies, cache_rows):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '')).strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '')).strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(movies, cache_rows=cache_rows)

        return build_library_enrichment_status_text(avfan_status, javtxt_status)

    def _build_prefix_distribution(self, rows):
        grouped = {}
        for row in rows:
            prefix = extract_code_prefix(row.get('code', '')) or '未知'
            grouped[prefix] = grouped.get(prefix, 0) + 1

        return [
            {'prefix': prefix, 'video_count': count}
            for prefix, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _build_year_distribution(self, rows):
        grouped = {}
        for row in rows:
            year = self._extract_year(row.get('release_date', ''))
            grouped[year] = grouped.get(year, 0) + 1

        known_items = [(year, count) for year, count in grouped.items() if year != '未知']
        unknown_items = [(year, count) for year, count in grouped.items() if year == '未知']
        known_items.sort(key=lambda item: (-int(item[0]), -item[1], item[0]))
        ordered = known_items + unknown_items
        return [{'year': year, 'video_count': count} for year, count in ordered]

    def _collect_date_range(self, rows):
        dates = sorted(
            str(row.get('release_date', '')).strip()
            for row in rows
            if str(row.get('release_date', '')).strip()
        )
        if not dates:
            return '', ''
        return dates[0], dates[-1]

    @staticmethod
    def _extract_year(release_date_text):
        text = str(release_date_text or '').strip()
        match = YEAR_RE.search(text)
        if not match:
            return '未知'
        return match.group(0)

    @staticmethod
    def _is_eligible_movie(movie):
        return is_javtxt_eligible_movie(movie)
