import re

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
        matched_videos = self._find_actor_videos(actor_name)
        prefix_distribution = self._build_prefix_distribution(matched_videos)
        year_distribution = self._build_year_distribution(matched_videos)

        return {
            'name': actor_name,
            'birthday': actor_row.get('birthday', ''),
            'age': actor_row.get('age', ''),
            'matched': bool(actor_row.get('matched')),
            'video_count': len(matched_videos),
            'prefix_distribution': prefix_distribution,
            'year_distribution': year_distribution,
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

    def _find_actor_videos(self, actor_name):
        matched = []
        for row in self.database.list_videos():
            actor_names = split_actor_names(row.get('author', ''))
            if actor_name in actor_names:
                matched.append(row)
        return matched

    def _build_prefix_distribution(self, rows):
        grouped = {}
        for row in rows:
            prefix = extract_code_prefix(row.get('code', ''))
            if not prefix:
                prefix = '未知'
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

        def sort_key(item):
            year, count = item
            if year == '未知':
                return (1, year)
            return (0, f'{9999 - int(year):04d}')

        ordered = sorted(grouped.items(), key=sort_key)
        return [
            {'year': year, 'video_count': count}
            for year, count in ordered
        ]

    def _extract_year(self, release_date_text):
        text = str(release_date_text or '').strip()
        match = YEAR_RE.search(text)
        if not match:
            return '未知'
        return match.group(0)

