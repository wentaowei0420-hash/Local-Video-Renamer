import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta

from app.backend.service import BackendService
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.detail import ActorDetailLibrary, CodePrefixDetailLibrary
from app.services.library import CodePrefixLibrary
from app.services.video import VIDEO_CATEGORY_SINGLE


class BackendVideoListOptimizationTest(unittest.TestCase):
    def _build_service(self, database, filter_service=None, ladder_service=None):
        service = BackendService.__new__(BackendService)
        service.db = database
        service.video_filter_service = filter_service or _PassThroughFilterService()
        service.video_ladder_tag_service = ladder_service or _PassThroughLadderTagService()
        service.ensure_database_loaded = lambda: None
        return service

    def test_list_videos_without_search_skips_ladder_enrich(self):
        class FakeDatabase:
            def list_videos(self, search_text=''):
                if search_text:
                    raise AssertionError('unexpected searched query')
                return [{'code': 'AAA-001', 'title': 'Video A', 'author': 'Actor A'}]

        class FakeLadderService(_PassThroughLadderTagService):
            def enrich_video_rows(self, rows, medal_maps=None):
                raise AssertionError('no-search listing should not enrich all rows')

        service = self._build_service(FakeDatabase(), ladder_service=FakeLadderService())

        result = BackendService.list_videos(service)

        self.assertEqual([row['code'] for row in result['videos']], ['AAA-001'])

    def test_list_videos_search_expands_only_ladder_matched_candidates(self):
        class FakeDatabase:
            def __init__(self):
                self.actor_queries = []
                self.prefix_queries = []

            def list_videos(self, search_text=''):
                if search_text != 'Top Medal':
                    raise AssertionError(f'unexpected search text: {search_text}')
                return []

            def list_local_videos_by_actor_names(self, actor_names):
                self.actor_queries.append(list(actor_names))
                return [{'code': 'ACT-001', 'title': 'Actor Medal Video', 'author': 'Actor Medal'}]

            def list_local_videos_by_prefixes(self, prefixes):
                self.prefix_queries.append(list(prefixes))
                return [{'code': 'LAD-001', 'title': 'Prefix Medal Video', 'author': 'Other Actor'}]

        class FakeLadderService(_PassThroughLadderTagService):
            def load_medal_maps(self):
                return {
                    'actor_medal_map': {'Actor Medal': ['Top Medal']},
                    'prefix_medal_map': {'LAD': ['Top Medal']},
                }

            def enrich_video_rows(self, rows, medal_maps=None):
                enriched_rows = []
                for row in rows:
                    current = dict(row)
                    current['ladder_tag_text'] = 'Top Medal' if current['code'] in {'ACT-001', 'LAD-001'} else ''
                    enriched_rows.append(current)
                return enriched_rows

            def filter_video_rows(self, rows, search_text=''):
                normalized_search = str(search_text or '').strip().lower()
                if not normalized_search:
                    return list(rows or [])
                return [
                    dict(row or {})
                    for row in (rows or [])
                    if normalized_search in ' '.join(
                        [
                            str((row or {}).get('code', '') or ''),
                            str((row or {}).get('title', '') or ''),
                            str((row or {}).get('author', '') or ''),
                            str((row or {}).get('ladder_tag_text', '') or ''),
                        ]
                    ).lower()
                ]

        database = FakeDatabase()
        service = self._build_service(database, ladder_service=FakeLadderService())

        result = BackendService.list_videos(service, 'Top Medal')

        self.assertEqual([row['code'] for row in result['videos']], ['ACT-001', 'LAD-001'])
        self.assertEqual(database.actor_queries, [['Actor Medal']])
        self.assertEqual(database.prefix_queries, [['LAD']])

    def test_list_videos_passes_sort_and_pagination_to_database(self):
        class FakeDatabase:
            def __init__(self):
                self.calls = []

            def list_videos(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
                self.calls.append((search_text, sort_field, sort_order, limit, offset))
                return [{'code': 'AAA-001', 'title': 'Video A', 'author': 'Actor A'}]

            def count_videos(self, search_text=''):
                self.count_search = search_text
                return 345

        database = FakeDatabase()
        service = self._build_service(database)

        result = BackendService.list_videos(
            service,
            'actor a',
            sort_field='release_date',
            sort_order='desc',
            limit=50,
            offset=100,
        )

        self.assertEqual(
            database.calls,
            [('actor a', 'release_date', 'desc', 50, 100)],
        )
        self.assertEqual(database.count_search, 'actor a')
        self.assertEqual(result['total_count'], 345)
        self.assertEqual(result['offset'], 100)
        self.assertEqual(result['limit'], 50)


class TargetedDetailQueryTest(unittest.TestCase):
    def test_actor_detail_prefers_targeted_local_query(self):
        class FakeDatabase:
            def __init__(self):
                self.refresh_categories = None

            def list_actors(self, search_text=''):
                return [{'name': 'Actor A', 'birthday': '', 'age': '', 'matched': True, 'actor_id': ''}]

            def list_local_videos_by_actor_name(self, actor_name, refresh_categories=True):
                self.actor_name = actor_name
                self.refresh_categories = refresh_categories
                return [{'code': 'AAA-001', 'title': 'Local', 'author': 'Actor A'}]

            def list_videos(self):
                raise AssertionError('actor detail should not scan the full video library')

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

        database = FakeDatabase()
        detail = ActorDetailLibrary(database).get_actor_detail('Actor A')

        self.assertEqual([row['code'] for row in detail['local_videos']], ['AAA-001'])
        self.assertFalse(database.refresh_categories)

    def test_code_prefix_detail_prefers_targeted_local_query(self):
        class FakeDatabase:
            def __init__(self):
                self.refresh_categories = None

            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def list_local_videos_by_prefix(self, prefix, refresh_categories=True):
                self.prefix = prefix
                self.refresh_categories = refresh_categories
                return [{'code': 'NEM-001', 'title': 'Local', 'author': 'Actor A'}]

            def list_videos(self):
                raise AssertionError('prefix detail should not scan the full video library')

            def list_code_prefix_movies(self, prefix):
                return []

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

        database = FakeDatabase()
        detail = CodePrefixDetailLibrary(database).get_prefix_detail('NEM')

        self.assertEqual([row['code'] for row in detail['local_videos']], ['NEM-001'])
        self.assertFalse(database.refresh_categories)


class LibraryListMetadataTest(unittest.TestCase):
    def test_actor_list_attaches_update_status_from_targeted_rows(self):
        recent_date = (date.today() - timedelta(days=90)).isoformat()

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [
                    {
                        'name': 'ActorA',
                        'actor_id': '1',
                        'birthday': '',
                        'age': '',
                        'avfan_enrichment_status': ENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                    }
                ]

            def list_local_videos_by_actor_names(self, actor_names):
                return [
                    {
                        'code': 'AAA-001',
                        'title': 'Recent Video',
                        'author': 'ActorA',
                        'release_date': recent_date,
                        'video_category': VIDEO_CATEGORY_SINGLE,
                    }
                ]

            def list_actor_movies_by_names(self, actor_names):
                return {}

            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [{'entity_name': 'ActorA', 'tier': 'A'}]

        service = BackendService.__new__(BackendService)
        service.db = FakeDatabase()
        service.video_filter_service = _PassThroughFilterService()
        service.ensure_database_loaded = lambda: None

        result = BackendService.list_actors(service)

        self.assertEqual(result['actors'][0]['update_status'], 'active')
        self.assertEqual(result['actors'][0]['ladder_tier'], 'A')
        self.assertEqual(result['actors'][0]['avfan_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(result['actors'][0]['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_list_actors_passes_sort_and_pagination_to_database(self):
        class FakeDatabase:
            def __init__(self):
                self.calls = []

            def list_actors(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
                self.calls.append((search_text, sort_field, sort_order, limit, offset))
                return [
                    {
                        'name': 'ActorA',
                        'actor_id': '1',
                        'birthday': '',
                        'age': '',
                        'avfan_enrichment_status': ENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'binghuo_enrichment_status': ENRICHED_STATUS,
                    }
                ]

            def count_actors(self, search_text=''):
                self.count_search = search_text
                return 222

            def list_local_videos_by_actor_names(self, actor_names):
                return []

            def list_actor_movies_by_names(self, actor_names):
                return {}

            def list_ladder_entries(self, board_key=None, entity_type=None):
                return []

        service = BackendService.__new__(BackendService)
        service.db = FakeDatabase()
        service.video_filter_service = _PassThroughFilterService()
        service.ensure_database_loaded = lambda: None

        result = BackendService.list_actors(
            service,
            'Actor',
            sort_field='age',
            sort_order='desc',
            limit=80,
            offset=160,
        )

        self.assertEqual(
            service.db.calls,
            [('Actor', 'age', 'desc', 80, 160)],
        )
        self.assertEqual(service.db.count_search, 'Actor')
        self.assertEqual(result['total_count'], 222)
        self.assertEqual(result['offset'], 160)
        self.assertEqual(result['limit'], 80)

    def test_list_actors_skips_category_refresh_for_targeted_local_video_query(self):
        class FakeDatabase:
            def __init__(self):
                self.refresh_categories = None

            def list_actors(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
                return [
                    {
                        'name': 'ActorA',
                        'actor_id': '1',
                        'birthday': '',
                        'age': '',
                        'avfan_enrichment_status': ENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'binghuo_enrichment_status': ENRICHED_STATUS,
                    }
                ]

            def count_actors(self, search_text=''):
                return 1

            def list_local_videos_by_actor_names(self, actor_names, refresh_categories=True):
                self.refresh_categories = refresh_categories
                return []

            def list_actor_movies_by_names(self, actor_names):
                return {}

            def list_ladder_entries(self, board_key=None, entity_type=None):
                return []

        service = BackendService.__new__(BackendService)
        service.db = FakeDatabase()
        service.video_filter_service = _PassThroughFilterService()
        service.ensure_database_loaded = lambda: None

        BackendService.list_actors(service)

        self.assertFalse(service.db.refresh_categories)

    def test_code_prefix_list_includes_raw_status_and_update_status(self):
        recent_date = (date.today() - timedelta(days=120)).isoformat()

        class FakeDatabase:
            def list_videos(self):
                return [
                    {
                        'code': 'NEM-001',
                        'title': 'Local Video',
                        'author': 'Actor A',
                        'release_date': recent_date,
                        'video_category': VIDEO_CATEGORY_SINGLE,
                    }
                ]

            def list_code_prefix_enrichment_records(self):
                return {
                    'NEM': {
                        'avfan_enrichment_status': ENRICHED_STATUS,
                        'javtxt_enrichment_status': FAILED_STATUS,
                        'avfan_total_videos': 12,
                    }
                }

            def list_hidden_code_prefixes(self):
                return set()

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {'NEM': []}

            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [{'entity_name': 'NEM', 'tier': 'S'}]

        rows = CodePrefixLibrary(FakeDatabase(), _PassThroughFilterService()).list_prefixes()

        self.assertEqual(rows[0]['prefix'], 'NEM')
        self.assertEqual(rows[0]['ladder_tier'], 'S')
        self.assertEqual(rows[0]['avfan_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(rows[0]['javtxt_enrichment_status'], FAILED_STATUS)
        self.assertEqual(rows[0]['update_status'], 'active')

    def test_code_prefix_list_skips_category_refresh_for_targeted_local_video_query(self):
        class FakeDatabase:
            def __init__(self):
                self.refresh_categories = None

            def list_code_prefix_summaries(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
                return [
                    {
                        'prefix': 'NEM',
                        'video_count': 1,
                        'avfan_enrichment_status': ENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'avfan_total_pages': 0,
                        'avfan_total_videos': 0,
                        'earliest_release_date': '',
                        'latest_release_date': '',
                        'last_enriched_at': '',
                    }
                ]

            def list_local_videos_by_prefixes(self, prefixes, refresh_categories=True):
                self.refresh_categories = refresh_categories
                return []

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {'NEM': []}

            def list_ladder_entries(self, board_key=None, entity_type=None):
                return []

        library = CodePrefixLibrary(FakeDatabase(), _PassThroughFilterService())

        library.list_prefixes()

        self.assertFalse(library.database.refresh_categories)

    def test_list_code_prefixes_passes_sort_and_pagination_to_library(self):
        class FakeCodePrefixLibrary:
            def __init__(self):
                self.calls = []

            def list_prefixes(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
                self.calls.append((search_text, sort_field, sort_order, limit, offset))
                return [{'prefix': 'NEM'}]

            def count_prefixes(self, search_text=''):
                self.count_search = search_text
                return 88

        service = BackendService.__new__(BackendService)
        service.code_prefix_library = FakeCodePrefixLibrary()
        service.ensure_database_loaded = lambda: None

        result = BackendService.list_code_prefixes(
            service,
            'NE',
            sort_field='avfan_total_videos',
            sort_order='desc',
            limit=40,
            offset=80,
        )

        self.assertEqual(
            service.code_prefix_library.calls,
            [('NE', 'avfan_total_videos', 'desc', 40, 80)],
        )
        self.assertEqual(service.code_prefix_library.count_search, 'NE')
        self.assertEqual(result['total_count'], 88)
        self.assertEqual(result['offset'], 80)
        self.assertEqual(result['limit'], 40)


class _PassThroughFilterService:
    @staticmethod
    def filter_video_rows(rows, settings=None):
        return list(rows or [])


class _PassThroughLadderTagService:
    @staticmethod
    def load_medal_maps():
        return {
            'actor_medal_map': {},
            'prefix_medal_map': {},
        }

    @staticmethod
    def enrich_video_rows(rows, medal_maps=None):
        return list(rows or [])

    @staticmethod
    def filter_video_rows(rows, search_text=''):
        return list(rows or [])


if __name__ == '__main__':
    unittest.main()


class DatabaseQueryPushdownIntegrationTest(unittest.TestCase):
    def test_video_database_list_videos_supports_sql_sort_limit_and_offset(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, author, duration, size, storage_location,
                        release_date, maker, publisher,
                        avfan_enrichment_status, javtxt_enrichment_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('AAA-001', 'A', 'Actor A', '1:00:00', '1.0', 'D:/A', '2024-01-01', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                        ('AAA-002', 'B', 'Actor B', '2:00:00', '2.0', 'D:/B', '2024-03-01', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                        ('AAA-003', 'C', 'Actor C', '3:00:00', '3.0', 'D:/C', '2024-02-01', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                    ],
                )
                conn.commit()

            rows = db.list_videos(sort_field='release_date', sort_order='desc', limit=2, offset=1)

            self.assertEqual([row['code'] for row in rows], ['AAA-003', 'AAA-001'])
            self.assertEqual(db.count_videos(), 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_database_list_actors_supports_sql_sort_limit_and_offset(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    [
                        ('Actor A', '2001-01-01', '23'),
                        ('Actor B', '2000-01-01', '30'),
                        ('Actor C', '1999-01-01', '27'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO actor_enrichments (
                        actor_name, avfan_enrichment_status, javtxt_enrichment_status, binghuo_enrichment_status
                    ) VALUES (?, ?, ?, ?)
                    ''',
                    [
                        ('Actor A', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS),
                        ('Actor B', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS),
                        ('Actor C', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS),
                    ],
                )
                conn.commit()

            rows = db.list_actors(sort_field='age', sort_order='desc', limit=2, offset=1)

            self.assertEqual([row['name'] for row in rows], ['Actor C', 'Actor A'])
            self.assertEqual(db.count_actors(), 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_database_list_actors_sorts_by_baomu_birthday_when_primary_birthday_is_placeholder(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    [
                        ('Actor From Baomu', '未知', '未知'),
                        ('Actor Direct', '1990-01-01', '30'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO actor_enrichments (
                        actor_name, avfan_enrichment_status, javtxt_enrichment_status, binghuo_enrichment_status,
                        baomu_enrichment_status, baomu_birthday
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('Actor From Baomu', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, '1984-05-20'),
                        ('Actor Direct', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ''),
                    ],
                )
                conn.commit()

            rows = db.list_actors(sort_field='birthday', sort_order='asc')

            self.assertEqual([row['name'] for row in rows], ['Actor From Baomu', 'Actor Direct'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_database_list_actors_sorts_by_computed_age_from_baomu_birthday_when_primary_age_is_placeholder(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    [
                        ('Actor From Baomu', '未知', '未知'),
                        ('Actor Younger', '1996-01-01', '30'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO actor_enrichments (
                        actor_name, avfan_enrichment_status, javtxt_enrichment_status, binghuo_enrichment_status,
                        baomu_enrichment_status, baomu_birthday
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('Actor From Baomu', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, '1984-05-20'),
                        ('Actor Younger', ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ENRICHED_STATUS, ''),
                    ],
                )
                conn.commit()

            rows = db.list_actors(sort_field='age', sort_order='desc')

            self.assertEqual([row['name'] for row in rows], ['Actor From Baomu', 'Actor Younger'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_database_list_code_prefix_summaries_supports_sql_sort_limit_and_offset(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, author, duration, size, storage_location,
                        release_date, maker, publisher,
                        avfan_enrichment_status, javtxt_enrichment_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('NEM-001', 'A', 'Actor A', '', '', '', '2024-01-01', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                        ('NEM-002', 'B', 'Actor B', '', '', '', '2024-01-02', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                        ('IPX-001', 'C', 'Actor C', '', '', '', '2024-02-01', '', '', ENRICHED_STATUS, ENRICHED_STATUS),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_enrichments (
                        prefix, avfan_enrichment_status, javtxt_enrichment_status, avfan_total_videos
                    ) VALUES (?, ?, ?, ?)
                    ''',
                    [
                        ('NEM', ENRICHED_STATUS, ENRICHED_STATUS, 3),
                        ('IPX', ENRICHED_STATUS, ENRICHED_STATUS, 9),
                        ('ROE', ENRICHED_STATUS, ENRICHED_STATUS, 5),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_movies (prefix, code, release_date)
                    VALUES (?, ?, ?)
                    ''',
                    [
                        ('NEM', 'NEM-001', '2024-01-01'),
                        ('IPX', 'IPX-001', '2024-02-01'),
                        ('ROE', 'ROE-001', '2024-03-01'),
                    ],
                )
                conn.commit()

            rows = db.list_code_prefix_summaries(sort_field='avfan_total_videos', sort_order='desc', limit=2, offset=1)

            self.assertEqual([row['prefix'] for row in rows], ['ROE', 'NEM'])
            self.assertEqual(db.count_code_prefixes(), 3)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
