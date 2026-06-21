import unittest

from app.backend.client import BackendClient
from app.backend.service import BackendService
from app.services.library.canglangge_candidate_service import CanglanggeCandidateService


class CanglanggeCandidateServiceTest(unittest.TestCase):
    def test_collects_candidates_only_from_s_tier_recent_web_movies(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [
                    {'entity_name': 'IPX', 'tier': 'S'},
                    {'entity_name': 'ABC', 'tier': 'A'},
                ]

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                self.prefixes = list(prefixes)
                return {
                    'IPX': [
                        {'code': 'IPX-001', 'author': 'ActorA ActorB', 'release_date': '2021-01-01', 'prefix': 'IPX'},
                        {'code': 'IPX-002', 'author': 'ActorD', 'release_date': '2019-12-31', 'prefix': 'IPX'},
                        {'code': 'IPX-003', 'author': 'ActorE', 'release_date': '', 'prefix': 'IPX'},
                    ],
                    'ABC': [
                        {'code': 'ABC-001', 'author': 'ActorC', 'release_date': '2021-01-01', 'prefix': 'ABC'},
                    ],
                }

            def list_actors(self, search_text=''):
                return [{'name': 'ActorB'}]

            def list_hidden_actors(self):
                return {'ActorZ'}

        database = FakeDatabase()

        rows = CanglanggeCandidateService(database).list_candidates()

        self.assertEqual(database.prefixes, ['IPX'])
        self.assertEqual([row['actor_name'] for row in rows], ['ActorA'])
        self.assertEqual(rows[0]['prefixes'], ['IPX'])
        self.assertEqual(rows[0]['birthday'], '')
        self.assertEqual(rows[0]['age'], '')

    def test_aggregates_multiple_s_prefix_sources_into_one_actor_row(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [
                    {'entity_name': 'IPX', 'tier': 'S'},
                    {'entity_name': 'MIDV', 'tier': 'S'},
                ]

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {
                    'IPX': [
                        {'code': 'IPX-001', 'author': 'ActorA', 'release_date': '2022-01-01', 'prefix': 'IPX'},
                    ],
                    'MIDV': [
                        {'code': 'MIDV-009', 'author': 'ActorA', 'release_date': '2023-02-02', 'prefix': 'MIDV'},
                    ],
                }

            def list_actors(self, search_text=''):
                return []

            def list_hidden_actors(self):
                return set()

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['actor_name'], 'ActorA')
        self.assertEqual(rows[0]['prefixes'], ['IPX', 'MIDV'])

    def test_merges_saved_binghuo_birthday_and_age_into_candidate_rows(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [{'entity_name': 'ROE', 'tier': 'S'}]

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {
                    'ROE': [
                        {'code': 'ROE-001', 'author': 'ActorA', 'release_date': '2022-01-01', 'prefix': 'ROE'},
                    ]
                }

            def list_actors(self, search_text=''):
                return []

            def list_hidden_actors(self):
                return set()

            def list_actor_enrichment_records(self):
                return {
                    'ActorA': {
                        'binghuo_birthday': '2003-09-04',
                        'binghuo_age': '22',
                    }
                }

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual(rows[0]['birthday'], '2003-09-04')
        self.assertEqual(rows[0]['age'], '22')

    def test_excludes_hidden_actors(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [{'entity_name': 'IPX', 'tier': 'S'}]

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {
                    'IPX': [
                        {'code': 'IPX-001', 'author': 'ActorA ActorB', 'release_date': '2022-03-04', 'prefix': 'IPX'},
                    ]
                }

            def list_actors(self, search_text=''):
                return []

            def list_hidden_actors(self):
                return {'ActorB'}

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual([row['actor_name'] for row in rows], ['ActorA'])

    def test_displays_only_source_s_prefix_without_specific_codes(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [{'entity_name': 'ROE', 'tier': 'S'}]

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                return {
                    'ROE': [
                        {'code': 'ROE-001', 'author': 'ActorA', 'release_date': '2021-01-01', 'prefix': 'ROE'},
                        {'code': 'ROE-099', 'author': 'ActorA', 'release_date': '2021-03-01', 'prefix': 'ROE'},
                    ]
                }

            def list_actors(self, search_text=''):
                return []

            def list_hidden_actors(self):
                return set()

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual(len(rows), 1)
        self.assertNotIn('codes', rows[0])
        self.assertEqual(rows[0]['prefixes'], ['ROE'])


class BackendServiceCanglanggeTest(unittest.TestCase):
    def test_lists_canglangge_candidates(self):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service._canglangge_snapshot = None
        service.canglangge_candidate_service = type(
            'CandidateService',
            (),
            {'list_candidates': lambda self: [{'actor_name': 'Actor A'}]},
        )()
        service._snapshot_lock = None
        service._current_snapshot_timestamp = lambda: '2026-06-21 20:00:00'

        result = BackendService.list_canglangge_candidates(service)

        self.assertEqual(
            result,
            {'candidates': [{'actor_name': 'Actor A'}], 'refreshed_at': '2026-06-21 20:00:00'},
        )

    def test_canglangge_snapshot_reuses_cache_until_force_refresh(self):
        class CandidateService:
            def __init__(self):
                self.calls = 0

            def list_candidates(self):
                self.calls += 1
                return [{'actor_name': f'Actor {self.calls}'}]

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service._canglangge_snapshot = None
        service.canglangge_candidate_service = CandidateService()
        service._snapshot_lock = None
        timestamps = iter(['2026-06-21 20:00:00', '2026-06-21 20:05:00'])
        service._current_snapshot_timestamp = lambda: next(timestamps)

        first = BackendService.list_canglangge_candidates(service)
        second = BackendService.list_canglangge_candidates(service)
        refreshed = BackendService.list_canglangge_candidates(service, force_refresh=True)

        self.assertEqual(first['candidates'], [{'actor_name': 'Actor 1'}])
        self.assertEqual(second['candidates'], [{'actor_name': 'Actor 1'}])
        self.assertEqual(refreshed['candidates'], [{'actor_name': 'Actor 2'}])

    def test_admit_candidates_reuses_actor_add_flow(self):
        class FakeAdminService:
            def __init__(self):
                self.calls = []

            def add_actor(self, actor_name, birthday='', age=''):
                self.calls.append((actor_name, birthday, age))
                return 1

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.library_admin_service = FakeAdminService()

        result = BackendService.admit_canglangge_candidates(service, ['Actor A'])

        self.assertEqual(result['admitted_count'], 1)
        self.assertEqual(service.library_admin_service.calls, [('Actor A', '', '')])

    def test_delete_candidates_blacklists_without_touching_actor_library(self):
        class FakeDatabase:
            def __init__(self):
                self.calls = []

            def hide_actor(self, actor_name):
                self.calls.append(actor_name)
                return 1

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.db = FakeDatabase()

        result = BackendService.delete_canglangge_candidates(service, ['Actor A', 'Actor B'])

        self.assertEqual(result['deleted_count'], 2)
        self.assertEqual(service.db.calls, ['Actor A', 'Actor B'])


class BackendClientCanglanggeTest(unittest.TestCase):
    def test_list_candidates_uses_relaxed_timeout_for_initial_database_load(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'candidates': []}

        client._get = fake_get

        result = client.list_canglangge_candidates()

        self.assertEqual(result, [])
        self.assertEqual(calls, [('/canglangge/candidates', 120)])

    def test_list_candidates_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'candidates': [], 'refreshed_at': '2026-06-21 20:00:00'}

        client._get = fake_get

        result = client.list_canglangge_candidates_snapshot(force_refresh=True)

        self.assertEqual(result['refreshed_at'], '2026-06-21 20:00:00')
        self.assertEqual(calls, [('/canglangge/candidates?refresh=1', 120)])


if __name__ == '__main__':
    unittest.main()
