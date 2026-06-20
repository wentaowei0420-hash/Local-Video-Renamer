import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.enrichment.actor_binghuo_enrichment import ActorBinghuoEnrichmentService


class FakeBinghuoScraper:
    def __init__(self, search_results=None, profiles=None):
        self.search_results = dict(search_results or {})
        self.profiles = dict(profiles or {})
        self.opened_targets = []
        self.search_calls = []
        self._current_profile = {}

    @contextmanager
    def session(self):
        yield object()

    def open_search_page(self, _page, actor_name):
        self.search_calls.append(actor_name)
        self._current_actor_name = actor_name
        return actor_name

    def collect_search_results(self, _page):
        return [dict(row) for row in self.search_results.get(self._current_actor_name, [])]

    def open_person_page(self, _page, person_id='', url=''):
        target = str(url or person_id or '').strip()
        self.opened_targets.append(target)
        key = person_id or self.extract_person_id(url)
        self._current_profile = dict(self.profiles.get(str(key), {}))
        return url or f'https://www.fouroursonsinc.com/person/{key}'

    def parse_profile(self, _page):
        return dict(self._current_profile)

    @staticmethod
    def extract_person_id(url):
        return str(url or '').rstrip('/').split('/')[-1]


class FakeCanglanggeCandidateService:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_candidates(self):
        return [dict(row) for row in self.rows]


class FakeLogger:
    def __init__(self):
        self.records = []

    def log(self, level, message, **fields):
        self.records.append(
            {
                'level': level,
                'message': message,
                'fields': dict(fields),
            }
        )


class ActorBinghuoEnrichmentServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
        self.db = VideoDatabase(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_actor(self, name, birthday='', age=''):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                (name, birthday, age),
            )
            conn.commit()

    def test_prioritizes_canglangge_then_missing_birthday_then_missing_binghuo_id(self):
        self._insert_actor('演员B', birthday='', age='')
        self._insert_actor('演员C', birthday='1999-01-01', age='27')
        self._insert_actor('演员D', birthday='', age='')
        self.db.save_binghuo_actor_profile('演员D', NO_SEARCH_RESULTS_STATUS, error='无搜索结果')

        scraper = FakeBinghuoScraper(
            search_results={
                '演员A': [{'title': '演员A,Alias [100%]', 'href': 'https://www.fouroursonsinc.com/person/1'}],
                '演员B': [{'title': '演员B', 'href': 'https://www.fouroursonsinc.com/person/2'}],
                '演员C': [{'title': '演员C', 'href': 'https://www.fouroursonsinc.com/person/3'}],
            },
            profiles={
                '1': {'person_id': '1', 'birthday': '2001-02-03', 'age': '25'},
                '2': {'person_id': '2', 'birthday': '2002-03-04', 'age': '24'},
                '3': {'person_id': '3', 'birthday': '1999-01-01', 'age': '27', 'height': '168'},
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService(
                [
                    {'actor_name': '演员A', 'birthday': '', 'age': '', 'prefixes': ['ROE']},
                    {'actor_name': '演员X', 'birthday': '2000-01-01', 'age': '26', 'prefixes': ['ROE']},
                ]
            ),
        )

        result = service.enrich_next_actors(5)

        self.assertEqual([row['actor_name'] for row in result['results']], ['演员A', '演员B', '演员C'])

    def test_multiple_exact_matches_use_first_exact_result(self):
        self._insert_actor('小坂七香', birthday='', age='')
        scraper = FakeBinghuoScraper(
            search_results={
                '小坂七香': [
                    {'title': '小坂七香,Kosaka Nanaka [100%]', 'href': 'https://www.fouroursonsinc.com/person/5921'},
                    {'title': '小坂七香,Other Alias [100%]', 'href': 'https://www.fouroursonsinc.com/person/7000'},
                ]
            },
            profiles={
                '5921': {'person_id': '5921', 'birthday': '2003-09-04', 'age': '22', 'height': '172'},
                '7000': {'person_id': '7000', 'birthday': '1990-01-01', 'age': '36', 'height': '160'},
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        service.enrich_next_actors(1)

        record = self.db.get_actor_enrichment_record('小坂七香')
        self.assertEqual(record['binghuo_person_id'], '5921')
        self.assertEqual(record['binghuo_birthday'], '2003-09-04')

    def test_numbered_exact_match_result_is_accepted(self):
        self._insert_actor('山口珠理', birthday='', age='')
        scraper = FakeBinghuoScraper(
            search_results={
                '山口珠理': [
                    {'title': '1. 山口珠理,Yamaguchi Juri [100%]', 'href': 'https://www.fouroursonsinc.com/person/916'},
                ]
            },
            profiles={
                '916': {'person_id': '916', 'birthday': '1967-07-02', 'age': '58', 'height': '164', 'bust': '90', 'waist': '64', 'hip': '90'},
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)
        record = self.db.get_actor_enrichment_record('山口珠理')

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(record['binghuo_person_id'], '916')
        self.assertEqual(record['binghuo_birthday'], '1967-07-02')
        self.assertEqual(record['binghuo_height'], '164')
        self.assertEqual(record['binghuo_bust'], '90')
        self.assertEqual(record['binghuo_waist'], '64')
        self.assertEqual(record['binghuo_hip'], '90')

    def test_no_search_result_is_saved_and_skipped_on_next_run(self):
        self._insert_actor('演员Z', birthday='', age='')
        scraper = FakeBinghuoScraper(search_results={'演员Z': []})
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        first = service.enrich_next_actors(1)
        second = service.enrich_next_actors(1)

        self.assertEqual(first['results'][0]['status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(second['processed_count'], 0)
        self.assertEqual(self.db.get_actor_enrichment_record('演员Z')['binghuo_enrichment_status'], NO_SEARCH_RESULTS_STATUS)

    def test_existing_binghuo_id_opens_profile_directly_without_search(self):
        self._insert_actor('演员Y', birthday='', age='')
        self.db.save_binghuo_actor_profile('演员Y', '失败', person_id='8888', error='旧错误')
        scraper = FakeBinghuoScraper(
            profiles={'8888': {'person_id': '8888', 'birthday': '2001-01-01', 'age': '25'}},
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        service.enrich_next_actors(1)

        self.assertEqual(scraper.search_calls, [])
        self.assertEqual(scraper.opened_targets, ['8888'])
        self.assertEqual(self.db.get_actor_enrichment_record('演员Y')['binghuo_birthday'], '2001-01-01')

    def test_missing_birthday_keeps_actor_retryable_and_marks_unenriched(self):
        actor_name = 'Actor Missing Birthday'
        self._insert_actor(actor_name, birthday='', age='')
        scraper = FakeBinghuoScraper(
            search_results={
                actor_name: [
                    {
                        'title': actor_name,
                        'href': 'https://www.fouroursonsinc.com/person/36413',
                    }
                ]
            },
            profiles={
                '36413': {
                    'person_id': '36413',
                    'birthday': '',
                    'age': '30',
                    'height': '175',
                    'bust': '108',
                    'waist': '62',
                    'hip': '91',
                }
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result['results'][0]['status'], UNENRICHED_STATUS)
        self.assertEqual(result['success_count'], 0)
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record['binghuo_person_id'], '36413')
        self.assertEqual(record['binghuo_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['binghuo_birthday'], '')
        self.assertEqual(record['binghuo_height'], '175')
        actor_row = self.db.list_actors(actor_name)[0]
        self.assertEqual(actor_row['birthday'], '')
        self.assertEqual(actor_row['raw_age'], '30')
        self.assertIn(actor_name, [row['actor_name'] for row in service._candidate_actors()])

    def test_logs_actor_level_result_fields_for_partial_binghuo_profile(self):
        actor_name = 'Actor Logged'
        self._insert_actor(actor_name, birthday='', age='')
        scraper = FakeBinghuoScraper(
            search_results={
                actor_name: [
                    {
                        'title': actor_name,
                        'href': 'https://www.fouroursonsinc.com/person/5001',
                    }
                ]
            },
            profiles={
                '5001': {
                    'person_id': '5001',
                    'birthday': '',
                    'age': '29',
                    'height': '168',
                }
            },
        )
        logger = FakeLogger()
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
            logger=logger,
        )

        service.enrich_next_actors(1)

        actor_result_logs = [entry for entry in logger.records if entry['fields'].get('actor_name') == actor_name]
        self.assertTrue(actor_result_logs)
        self.assertEqual(actor_result_logs[-1]['fields']['person_id'], '5001')
        self.assertFalse(actor_result_logs[-1]['fields']['birthday_found'])
        self.assertEqual(actor_result_logs[-1]['fields']['status_written'], UNENRICHED_STATUS)

    def test_existing_person_id_with_missing_birthday_is_retried(self):
        actor_name = '\u307f\u306a\u307f\u7fbd\u7409'
        self._insert_actor(actor_name, birthday='', age='30')
        self.db.save_binghuo_actor_profile(
            actor_name,
            ENRICHED_STATUS,
            person_id='36413',
            birthday='',
            age='30',
            height='175',
            bust='108',
            waist='62',
            hip='91',
        )
        scraper = FakeBinghuoScraper(
            profiles={
                '36413': {
                    'person_id': '36413',
                    'birthday': '1996-06-09',
                    'age': '30',
                    'height': '175',
                    'bust': '108',
                    'waist': '62',
                    'hip': '91',
                }
            }
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual([row['actor_name'] for row in result['results']], [actor_name])
        actor_row = self.db.list_actors(actor_name)[0]
        self.assertEqual(actor_row['birthday'], '1996/6/9')
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record['binghuo_birthday'], '1996-06-09')


if __name__ == '__main__':
    unittest.main()
