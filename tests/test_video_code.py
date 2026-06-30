import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app.core.filename_rules import extract_code_from_filename
from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_video_state import is_javtxt_eligible_movie, summarize_javtxt_movies
from app.core.video_code import compact_video_code, has_supported_video_code, standardize_video_code
from app.data.database_handler import STARTUP_MAINTENANCE_META_KEY, VideoDatabase
from app.scraper.javtxt_scraper import extract_page_code, is_not_found_detail_page
from app.services.parsers import extract_code
from app.services.resolvers import MovieAuthorResolver
from app.services.video import (
    MANUAL_CATEGORY_TIER_FIRST,
    MANUAL_CATEGORY_TIER_SECOND,
    MANUAL_CATEGORY_TIER_THIRD,
    VIDEO_CATEGORY_CO_STAR,
    classify_manual_category_tier,
    detect_video_category,
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_SINGLE,
)


class VideoCodeStandardizationTest(unittest.TestCase):
    def test_strips_leading_numeric_vendor_prefix(self):
        samples = {
            '168BOU001': 'BOU-001',
            '168BOU-001': 'BOU-001',
            '360MBMH058': 'MBMH-058',
            '360MBMH-058': 'MBMH-058',
            '013ONEZ075': 'ONEZ-075',
            '013ONEZ-075': 'ONEZ-075',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_keeps_real_numeric_or_alphanumeric_prefixes_when_standardizing(self):
        samples = {
            '010216-061': '010216-061',
            'T28-123': 'T28-123',
            'S2MBD-123': 'S2MBD-123',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_pure_numeric_prefix_codes_are_not_supported_for_web_lookup(self):
        self.assertFalse(has_supported_video_code('010216-061'))
        self.assertFalse(
            is_javtxt_eligible_movie(
                {
                    'code': '010216-061',
                    'title': 'sample',
                    'release_date': '2025-01-01',
                }
            )
        )
        self.assertEqual(extract_code('010216-061 sample'), '')
        self.assertIsNone(extract_code_from_filename('010216-061 sample'))

    def test_compact_code_uses_standardized_form_for_lookup(self):
        self.assertEqual(compact_video_code('168BOU-001'), 'BOU001')
        self.assertEqual(compact_video_code('BOU-001'), 'BOU001')

    def test_filename_and_card_parsers_return_standard_code(self):
        self.assertEqual(extract_code_from_filename('168BOU001 title'), 'BOU-001')
        self.assertEqual(extract_code('360MBMH-058 熟年同窓会'), 'MBMH-058')

    def test_javtxt_page_code_extraction_matches_standard_lookup_code(self):
        self.assertEqual(extract_page_code(['番号', 'bou-001 (h_113bou00001)']), 'BOU001')

    def test_javtxt_not_found_detail_page_is_detected(self):
        class _FakePage:
            def title(self):
                return 'Not Found'

        self.assertTrue(is_not_found_detail_page(_FakePage(), ['Not Found']))
        self.assertFalse(is_not_found_detail_page(_FakePage(), ['番号', 'STARS-225']))

    def test_manual_category_tier_classification(self):
        self.assertEqual(classify_manual_category_tier('甲 乙 丙 丁 戊', '甲 乙 丙 丁 戊'), MANUAL_CATEGORY_TIER_FIRST)
        self.assertEqual(classify_manual_category_tier('甲 乙 丙', '甲 乙 丙'), MANUAL_CATEGORY_TIER_SECOND)
        self.assertEqual(classify_manual_category_tier('', '未公开'), MANUAL_CATEGORY_TIER_THIRD)

    def test_detects_collection_category_from_long_duration_tags(self):
        self.assertEqual(detect_video_category('16时间以上作品 独家分发 熟女', ''), VIDEO_CATEGORY_COLLECTION)
        self.assertEqual(detect_video_category('16小时以上作品 精选合集', '甲 乙'), VIDEO_CATEGORY_COLLECTION)

    def test_vrtm_prefix_is_not_misclassified_as_vr_marker(self):
        self.assertTrue(
            is_javtxt_eligible_movie(
                {
                    'code': 'VRTM-518',
                    'title': 'あぶない放課後 新・女教師スペシャル つかもと友希 VRTM-518',
                    'release_date': '2020-09-11',
                }
            )
        )

    def test_detect_video_category_supports_forced_single_or_co_star_classification(self):
        self.assertEqual(detect_video_category('', '婕斿憳A', force_single_or_co_star=True), VIDEO_CATEGORY_SINGLE)
        self.assertEqual(detect_video_category('', '婕斿憳A 婕斿憳B', force_single_or_co_star=True), VIDEO_CATEGORY_CO_STAR)
        self.assertEqual(detect_video_category('', '', force_single_or_co_star=True), VIDEO_CATEGORY_CO_STAR)

    def test_javtxt_summary_separates_success_no_result_and_no_detail(self):
        summary = summarize_javtxt_movies(
            [
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'author': '演员A',
                    'javtxt_actors': '演员A',
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                    'javtxt_movie_id': '123',
                    'javtxt_url': 'https://javtxt.top/v/123',
                },
                {
                    'code': 'ABP-124',
                    'title': 'ABP-124',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                },
                {
                    'code': 'ABP-125',
                    'title': 'ABP-125',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': NO_VIDEO_DETAIL_STATUS,
                },
                {
                    'code': 'ABP-126',
                    'title': 'ABP-126',
                    'release_date': '2025-02-01',
                    'javtxt_release_date': '2025-02-01',
                    'javtxt_enrichment_status': '补全失败',
                },
            ]
        )

        self.assertEqual(summary['total_count'], 4)
        self.assertEqual(summary['enriched_count'], 3)
        self.assertEqual(summary['completed_count'], 3)
        self.assertEqual(summary['success_count'], 1)
        self.assertEqual(summary['pending_count'], 0)
        self.assertEqual(summary['failed_count'], 1)
        self.assertEqual(summary['no_search_count'], 1)
        self.assertEqual(summary['no_detail_count'], 1)


class VideoCodeDatabaseMigrationTest(unittest.TestCase):
    @staticmethod
    def _run_startup_maintenance(db_path):
        db = VideoDatabase(db_path)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute('DELETE FROM app_runtime_meta WHERE key = ?', (STARTUP_MAINTENANCE_META_KEY,))
            conn.commit()
        db.ensure_startup_maintenance()
        return db

    def test_database_init_normalizes_existing_actor_movie_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('actor', '168BOUZ-004', 'title', '', '2025-04-29', 'done', '506760', 'https://javtxt.top/v/506760', '2025-04-29'),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code, javtxt_movie_id, javtxt_url
                    FROM actor_movies
                    WHERE actor_name = ?
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('BOUZ-004', '506760', 'https://javtxt.top/v/506760')])

    def test_database_init_removes_duplicate_numeric_prefixed_actor_movie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('actor', '168BOU-001', 'title 1', '', '2025-04-28', 'done', '503611', 'https://javtxt.top/v/503611'),
                        ('actor', 'BOU-001', 'title 2', '', '2025-04-10', 'done', '503611', 'https://javtxt.top/v/503611'),
                    ],
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code
                    FROM actor_movies
                    WHERE actor_name = ?
                    ORDER BY code
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('BOU-001',)])

    def test_database_init_clears_numeric_only_web_lookup_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('actor', '010216-061', 'numeric only', '', '2025-01-01', 'done', '999', 'https://javtxt.top/v/999', 'tag'),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code, javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM actor_movies
                    WHERE actor_name = ?
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('010216-061', UNENRICHED_STATUS, '', '', '')])

    def test_database_init_converts_ineligible_processed_video_javtxt_state_to_terminal_no_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO processed_videos (
                        code, title, author, release_date,
                        javtxt_title, javtxt_actors, javtxt_actors_raw,
                        javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_enrichment_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'SQTE-241',
                        'old title',
                        '',
                        '2019-01-27',
                        'javtxt title',
                        'actor',
                        'actor',
                        '286795',
                        'https://javtxt.top/v/286795',
                        'tag',
                        '已补全',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('SQTE-241',),
                ).fetchall()

        self.assertEqual(rows, [(NO_SEARCH_RESULTS_STATUS, '', '', 'tag')])

    def test_database_init_clears_legacy_web_movie_javtxt_state_without_trusted_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'NSPS',
                        'NSPS-702',
                        'legacy movie',
                        '',
                        '2020-12-22',
                        ENRICHED_STATUS,
                        '272298',
                        'https://javtxt.top/v/272298',
                        'tag',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM code_prefix_movies
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('NSPS', 'NSPS-702'),
                ).fetchall()

        self.assertEqual(rows, [(UNENRICHED_STATUS, '', '', '')])

    def test_database_init_preserves_web_movie_no_result_without_javtxt_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'ACZD',
                        'ACZD-036',
                        'ACZD-036',
                        '',
                        '2022-05-13',
                        NO_SEARCH_RESULTS_STATUS,
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'Actor A',
                        'ACZD-036',
                        'ACZD-036',
                        '',
                        '2022-05-13',
                        NO_SEARCH_RESULTS_STATUS,
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.commit()

            db = VideoDatabase(db_path)
            db.sanitize_ineligible_javtxt_state()
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT
                        (SELECT javtxt_enrichment_status FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_enrichment_status FROM actor_movies WHERE actor_name = ? AND code = ?)
                    ''',
                    ('ACZD', 'ACZD-036', 'Actor A', 'ACZD-036'),
                ).fetchone()

        self.assertEqual(rows, (NO_SEARCH_RESULTS_STATUS, NO_SEARCH_RESULTS_STATUS))

    def test_database_init_converts_ineligible_web_movie_state_to_terminal_no_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'CEMD',
                        'CEMD-046',
                        '羽月希22時間03分ベスト',
                        '演员A',
                        '2021-08-07',
                        'https://example.com/movies/cemd-046',
                        1,
                        ENRICHED_STATUS,
                        '381297',
                        'https://javtxt.top/v/381297',
                        '16小时以上作品 女优精选集',
                        '2021-08-07',
                        '演员A',
                        '',
                    ),
                )
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        '演员A',
                        'CEMD-046',
                        '羽月希22時間03分ベスト',
                        '演员A',
                        '2021-08-07',
                        'https://example.com/movies/cemd-046',
                        1,
                        ENRICHED_STATUS,
                        '381297',
                        'https://javtxt.top/v/381297',
                        '16小时以上作品 女优精选集',
                        '2021-08-07',
                        '演员A',
                        '',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT
                        (SELECT javtxt_enrichment_status FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_movie_id FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_url FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT author FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_tags FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_enrichment_status FROM actor_movies WHERE actor_name = ? AND code = ?),
                        (SELECT javtxt_movie_id FROM actor_movies WHERE actor_name = ? AND code = ?),
                        (SELECT javtxt_url FROM actor_movies WHERE actor_name = ? AND code = ?),
                        (SELECT author FROM actor_movies WHERE actor_name = ? AND code = ?),
                        (SELECT javtxt_tags FROM actor_movies WHERE actor_name = ? AND code = ?)
                    ''',
                    (
                        'CEMD', 'CEMD-046',
                        'CEMD', 'CEMD-046',
                        'CEMD', 'CEMD-046',
                        'CEMD', 'CEMD-046',
                        'CEMD', 'CEMD-046',
                        '演员A', 'CEMD-046',
                        '演员A', 'CEMD-046',
                        '演员A', 'CEMD-046',
                        '演员A', 'CEMD-046',
                        '演员A', 'CEMD-046',
                    ),
                ).fetchone()

        self.assertEqual(
            rows,
            (
                NO_SEARCH_RESULTS_STATUS,
                '',
                '',
                '',
                '16小时以上作品 女优精选集',
                NO_SEARCH_RESULTS_STATUS,
                '',
                '',
                '',
                '16小时以上作品 女优精选集',
            ),
        )

    def test_database_init_clears_web_movie_actor_state_without_javtxt_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, author_raw,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'actor',
                        'AGMX-151',
                        'title',
                        '演员甲 演员乙',
                        '2025-01-01',
                        '演员甲 演员乙',
                        UNENRICHED_STATUS,
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT author, author_raw, javtxt_enrichment_status, javtxt_url
                    FROM actor_movies
                    WHERE actor_name = ? AND code = ?
                    ''',
                    ('actor', 'AGMX-151'),
                ).fetchall()

        self.assertEqual(rows, [('', '', UNENRICHED_STATUS, '')])

    def test_database_init_clears_processed_video_actor_state_without_javtxt_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO processed_videos (
                        code, title, release_date, javtxt_title, javtxt_actors, javtxt_actors_raw,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'AGMX-151',
                        'title',
                        '2025-01-01',
                        'title',
                        '演员甲 演员乙',
                        '演员甲 演员乙',
                        ENRICHED_STATUS,
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_actors, javtxt_actors_raw, javtxt_enrichment_status, javtxt_url
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('AGMX-151',),
                ).fetchall()

        self.assertEqual(rows, [('', '', UNENRICHED_STATUS, '')])

    def test_database_init_propagates_existing_web_movie_javtxt_state_by_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            self._run_startup_maintenance(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'AGMX', 'AGMX-151', 'prefix row', '婕斿憳鐢?', '2025-01-01',
                        'https://avfan.example/prefix/agmx-151', 1, ENRICHED_STATUS,
                        '151', 'https://javtxt.top/v/151', '浜哄', '2025-01-01',
                        '婕斿憳鐢?', '',
                    ),
                )
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'Actor A', 'AGMX-151', 'actor row', '', '2025-01-01',
                        'https://avfan.example/actor/agmx-151', 1, UNENRICHED_STATUS,
                        '', '', '', '', '', '',
                    ),
                )
                conn.commit()

            self._run_startup_maintenance(db_path)
            movie = self._run_startup_maintenance(db_path).list_actor_movies('Actor A')[0]

        self.assertEqual(movie['avfan_url'], 'https://avfan.example/actor/agmx-151')
        self.assertEqual(movie['javtxt_movie_id'], '151')
        self.assertEqual(movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(movie['author'], '婕斿憳鐢?')
        self.assertEqual(movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_javtxt_video_library_candidates_skip_ineligible_old_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = self._run_startup_maintenance(db_path)
            db.import_local_videos(
                [
                    {'code': 'SQTE-241', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'ABP-123', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "UPDATE processed_videos SET release_date = ? WHERE code = ?",
                    ('2019-01-27', 'SQTE-241'),
                )
                conn.execute(
                    "UPDATE processed_videos SET release_date = ? WHERE code = ?",
                    ('2025-02-01', 'ABP-123'),
                )
                conn.commit()

            rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE)

        self.assertEqual([row['code'] for row in rows], ['ABP-123'])

    def test_collection_tag_movies_are_classified_and_not_left_pending_for_javtxt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'CEMD-046', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )

            db.update_video_enrichment(
                'CEMD-046',
                {
                    'found': True,
                    'title': '叶月希 22 小时 03 分钟最佳',
                    'javtxt_title': '叶月希 22 小时 03 分钟最佳',
                    'author': '叶月希 朝仓琴美 大槻响',
                    'javtxt_actors': '叶月希 朝仓琴美 大槻响',
                    'javtxt_actors_raw': '叶月希 朝仓琴美 大槻响',
                    'release_date': '2021-08-07',
                    'javtxt_tags': '16时间以上作品 独家分发 熟女 女优精选集',
                    'javtxt_movie_id': 'cemd00046',
                    'javtxt_url': 'https://javtxt.example/v/cemd00046',
                },
                ENRICHED_STATUS,
                JAVTXT_VIDEO_SOURCE,
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT video_category, javtxt_enrichment_status, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('CEMD-046',),
                ).fetchone()

            pending_rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE)
            pending_count = db.count_pending_video_enrichments(JAVTXT_VIDEO_SOURCE)

        self.assertEqual(row[0], VIDEO_CATEGORY_COLLECTION)
        self.assertEqual(row[1], ENRICHED_STATUS)
        self.assertEqual(pending_rows, [])
        self.assertEqual(pending_count, 0)

    def test_manual_category_candidates_skip_ineligible_old_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, release_date, javtxt_title, javtxt_url,
                        javtxt_actors, javtxt_actors_raw, javtxt_tags,
                        javtxt_enrichment_status, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('SQTE-241', 'old processed', '2019-01-27', 'old processed', 'https://javtxt.top/v/286795', '演员旧', '演员旧', 'tag', ENRICHED_STATUS, '', ''),
                        ('ABP-123', 'new processed', '2025-02-01', 'new processed', 'https://javtxt.top/v/123', '演员甲 演员乙', '演员甲 演员乙', 'tag', ENRICHED_STATUS, '', '2025-02-01'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, javtxt_url,
                        javtxt_tags, author_raw, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('NSPS', 'NSPS-648', 'old web movie', '演员旧', '2017-11-19', 'https://javtxt.top/v/260682', '人妻', '演员旧', '', ''),
                        ('MIDV', 'MIDV-001', 'new web movie', '演员新', '2025-01-01', 'https://javtxt.top/v/456', '人妻', '演员新', '', '2025-01-01'),
                    ],
                )
                conn.commit()

            db = self._run_startup_maintenance(db_path)
            rows = db.list_videos_requiring_manual_category()['videos']
            with closing(sqlite3.connect(db_path)) as conn:
                processed_row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_url
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('SQTE-241',),
                ).fetchone()
                prefix_row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_url
                    FROM code_prefix_movies
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('NSPS', 'NSPS-648'),
                ).fetchone()

        self.assertEqual([row['code'] for row in rows], ['ABP-123'])
        self.assertEqual(processed_row, (NO_SEARCH_RESULTS_STATUS, ''))
        self.assertEqual(prefix_row, (UNENRICHED_STATUS, ''))

    def test_manual_category_candidates_include_manual_tiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, javtxt_url,
                        javtxt_tags, author_raw, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('ABCD', 'ABCD-001', 'five actors', '甲 乙 丙 丁 戊', '2025-01-01', 'https://javtxt.top/v/1', '人妻', '甲 乙 丙 丁 戊', '', '2025-01-01'),
                        ('EFGH', 'EFGH-002', 'three actors', '甲 乙 丙', '2025-01-01', 'https://javtxt.top/v/2', '人妻', '甲 乙 丙', '', '2025-01-01'),
                        ('IJKL', 'IJKL-003', 'unpublished', '', '2025-01-01', 'https://javtxt.top/v/3', '人妻', '未公开', '', '2025-01-01'),
                    ],
                )
                conn.commit()

            rows = db.list_videos_requiring_manual_category()['videos']
            tier_by_code = {row['code']: row['manual_tier'] for row in rows}

        self.assertEqual(tier_by_code['ABCD-001'], MANUAL_CATEGORY_TIER_FIRST)
        self.assertEqual(tier_by_code['EFGH-002'], MANUAL_CATEGORY_TIER_SECOND)
        self.assertEqual(tier_by_code['IJKL-003'], MANUAL_CATEGORY_TIER_THIRD)

    @patch(
        'app.data.database_handler.load_video_filter_settings',
        return_value={
            'rules': {
                'code': [],
                'title': [],
                'javtxt_tags': [],
                'co_star_code': ['MIDV-', 'ABP-'],
            }
        },
    )
    def test_co_star_code_keywords_auto_classify_videos_and_skip_manual_category_queue(self, _load_settings):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO processed_videos (
                        code, title, release_date, javtxt_title, javtxt_url,
                        javtxt_actors, javtxt_actors_raw, javtxt_tags,
                        javtxt_enrichment_status, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('MIDV-001', 'keyword no actor', '2025-02-01', 'keyword no actor', 'https://javtxt.top/v/1', '', '', 'tag', ENRICHED_STATUS, '', '2025-02-01'),
                )
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, javtxt_url,
                        javtxt_tags, author_raw, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('ABP', 'ABP-123', 'keyword single actor', '婕斿憳A', '2025-02-01', 'https://javtxt.top/v/2', 'tag', '婕斿憳A', '', '2025-02-01'),
                )
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, '', 1, ?, '', ?, ?, ?, ?, ?)
                    ''',
                    ('婕斿憳A', 'ABP-123', 'keyword single actor', '婕斿憳A', '2025-02-01', ENRICHED_STATUS, 'https://javtxt.top/v/2', 'tag', '2025-02-01', '婕斿憳A', ''),
                )
                conn.commit()

            rows = db.list_videos_requiring_manual_category()['videos']

            with closing(sqlite3.connect(db_path)) as conn:
                processed_category = conn.execute(
                    'SELECT video_category FROM processed_videos WHERE code = ?',
                    ('MIDV-001',),
                ).fetchone()
                prefix_category = conn.execute(
                    'SELECT video_category FROM code_prefix_movies WHERE prefix = ? AND code = ?',
                    ('ABP', 'ABP-123'),
                ).fetchone()
                actor_category = conn.execute(
                    'SELECT video_category FROM actor_movies WHERE actor_name = ? AND code = ?',
                    ('婕斿憳A', 'ABP-123'),
                ).fetchone()

        self.assertEqual(rows, [])
        self.assertEqual(processed_category, (VIDEO_CATEGORY_CO_STAR,))
        self.assertEqual(prefix_category, (VIDEO_CATEGORY_SINGLE,))
        self.assertEqual(actor_category, (VIDEO_CATEGORY_SINGLE,))

    def test_replace_code_prefix_movies_preserves_processed_video_no_result_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'ACZD-050', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?, javtxt_release_date = ?, javtxt_enrichment_status = ?, javtxt_enrichment_error = ?
                    WHERE code = ?
                    ''',
                    ('2025-02-01', '2025-02-01', '无搜索结果', '未搜索到匹配影片', 'ACZD-050'),
                )
                conn.commit()

            db.replace_code_prefix_movies(
                'ACZD',
                [
                    {
                        'code': 'ACZD-050',
                        'title': 'ACZD-050',
                        'author': '',
                        'release_date': '2025-02-01',
                        'avfan_url': 'https://example.com/movies/aczd-050',
                    }
                ],
            )

            movie = db.list_code_prefix_movies('ACZD')[0]

        self.assertEqual(movie['javtxt_enrichment_status'], '无搜索结果')

    def test_replace_code_prefix_movies_preserves_ineligible_processed_video_no_result_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'CEMD-046', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?, javtxt_release_date = ?, javtxt_enrichment_status = ?, javtxt_enrichment_error = ?, javtxt_tags = ?
                    WHERE code = ?
                    ''',
                    ('2021-08-07', '2021-08-07', NO_SEARCH_RESULTS_STATUS, 'JAVTXT 页面不满足补全条件', '16時間以上作品 女优精选集', 'CEMD-046'),
                )
                conn.commit()

            db.replace_code_prefix_movies(
                'CEMD',
                [
                    {
                        'code': 'CEMD-046',
                        'title': '羽月希22時間03分ベスト',
                        'author': '',
                        'release_date': '2021-08-07',
                        'avfan_url': 'https://example.com/movies/cemd-046',
                    }
                ],
            )

            movie = db.list_code_prefix_movies('CEMD')[0]

        self.assertEqual(movie['javtxt_enrichment_status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(movie['javtxt_tags'], '16時間以上作品 女优精选集')

    def test_replace_actor_movies_preserves_processed_video_no_result_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'ACZD-050', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?, javtxt_release_date = ?, javtxt_enrichment_status = ?, javtxt_enrichment_error = ?
                    WHERE code = ?
                    ''',
                    ('2025-02-01', '2025-02-01', '无搜索结果', '未搜索到匹配影片', 'ACZD-050'),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'ACZD-050',
                        'title': 'ACZD-050',
                        'author': '',
                        'release_date': '2025-02-01',
                        'avfan_url': 'https://example.com/movies/aczd-050',
                    }
                ],
            )

            movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(movie['javtxt_enrichment_status'], '无搜索结果')

    def test_save_javtxt_cache_for_video_propagates_no_result_state_to_web_movie_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'ACZD-072', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            db.replace_code_prefix_movies(
                'ACZD',
                [
                    {
                        'code': 'ACZD-072',
                        'title': 'ACZD-072',
                        'author': '',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-072',
                    }
                ],
            )
            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'ACZD-072',
                        'title': 'ACZD-072',
                        'author': '',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-072',
                    }
                ],
            )

            db.save_javtxt_cache_for_video(
                'ACZD-072',
                {
                    'title': 'ACZD-072',
                    'release_date': '2022-12-09',
                },
                status=NO_SEARCH_RESULTS_STATUS,
                error='未搜索到匹配影片',
            )

            prefix_movie = db.list_code_prefix_movies('ACZD')[0]
            actor_movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(prefix_movie['javtxt_enrichment_status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(actor_movie['javtxt_enrichment_status'], NO_SEARCH_RESULTS_STATUS)

    def test_save_javtxt_cache_for_video_refreshes_library_parent_statuses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'ACZD-072', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            db.replace_code_prefix_movies(
                'ACZD',
                [
                    {
                        'code': 'ACZD-072',
                        'title': 'ACZD-072',
                        'author': '',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-072',
                    }
                ],
            )
            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'ACZD-072',
                        'title': 'ACZD-072',
                        'author': '',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-072',
                    }
                ],
            )

            db.save_javtxt_cache_for_video(
                'ACZD-072',
                {
                    'title': 'ACZD-072',
                    'release_date': '2022-12-09',
                },
                status=NO_SEARCH_RESULTS_STATUS,
                error='未搜索到匹配影片',
            )

            prefix_record = db.get_code_prefix_enrichment_record('ACZD')
            actor_record = db.get_actor_enrichment_record('Actor A')

        self.assertEqual(prefix_record['javtxt_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(actor_record['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_save_javtxt_cache_for_video_with_no_detail_status_skips_future_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'STARS-225', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?
                    WHERE code = ?
                    ''',
                    ('2020-04-07', 'STARS-225'),
                )
                conn.commit()

            db.save_javtxt_cache_for_video(
                'STARS-225',
                {
                    'title': 'STARS-225',
                    'release_date': '2020-04-07',
                },
                status=NO_VIDEO_DETAIL_STATUS,
                error='无视频详情',
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_enrichment_error
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('STARS-225',),
                ).fetchone()

            pending_rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE)
            pending_count = db.count_pending_video_enrichments(JAVTXT_VIDEO_SOURCE)
            summary = db.get_video_enrichment_summary(JAVTXT_VIDEO_SOURCE)

        self.assertEqual(row, (NO_VIDEO_DETAIL_STATUS, '无视频详情'))
        self.assertEqual(pending_rows, [])
        self.assertEqual(pending_count, 0)
        self.assertEqual(summary['enriched_count'], 1)
        self.assertEqual(summary['success_count'], 0)
        self.assertEqual(summary['no_search_count'], 0)
        self.assertEqual(summary['no_detail_count'], 1)

    def test_save_javtxt_cache_for_video_ineligible_result_skips_future_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'NSPS-702', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?
                    WHERE code = ?
                    ''',
                    ('2020-12-22', 'NSPS-702'),
                )
                conn.commit()

            db.save_javtxt_cache_for_video(
                'NSPS-702',
                {
                    'title': 'legacy movie',
                    'javtxt_title': 'old movie',
                    'javtxt_actors': '演员A',
                    'javtxt_actors_raw': '演员A',
                    'release_date': '2018-05-13',
                    'javtxt_tags': '人妻',
                    'javtxt_movie_id': '272298',
                    'javtxt_url': 'https://javtxt.top/v/272298',
                },
                status=NO_SEARCH_RESULTS_STATUS,
                error='JAVTXT 页面不满足补全条件',
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_enrichment_error, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('NSPS-702',),
                ).fetchone()

            pending_rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE)
            pending_count = db.count_pending_video_enrichments(JAVTXT_VIDEO_SOURCE)
            summary = db.get_video_enrichment_summary(JAVTXT_VIDEO_SOURCE)

        self.assertEqual(row, (NO_SEARCH_RESULTS_STATUS, 'JAVTXT 页面不满足补全条件', '', '', '人妻'))
        self.assertEqual(pending_rows, [])
        self.assertEqual(pending_count, 0)
        self.assertEqual(summary['enriched_count'], 0)
        self.assertEqual(summary['success_count'], 0)
        self.assertEqual(summary['no_search_count'], 0)
        self.assertEqual(summary['no_detail_count'], 0)

    def test_replace_code_prefix_movies_refreshes_javtxt_parent_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.save_code_prefix_enrichment('ACZD', ENRICHED_STATUS, source_key=JAVTXT_VIDEO_SOURCE)

            db.replace_code_prefix_movies(
                'ACZD',
                [
                    {
                        'code': 'ACZD-073',
                        'title': 'ACZD-073',
                        'author': '',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-073',
                    }
                ],
            )

            record = db.get_code_prefix_enrichment_record('ACZD')

        self.assertEqual(record['javtxt_enrichment_status'], UNENRICHED_STATUS)

    def test_replace_actor_movies_refreshes_javtxt_parent_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.save_actor_enrichment('Actor A', UNENRICHED_STATUS, source_key=JAVTXT_VIDEO_SOURCE)

            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'ACZD-073',
                        'title': 'ACZD-073',
                        'author': 'Actor A',
                        'author_raw': 'Actor A',
                        'release_date': '2022-12-09',
                        'avfan_url': 'https://example.com/movies/aczd-073',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '123456',
                        'javtxt_url': 'https://javtxt.top/v/123456',
                        'javtxt_release_date': '2022-12-09',
                    }
                ],
            )

            record = db.get_actor_enrichment_record('Actor A')

        self.assertEqual(record['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_sanitize_ineligible_javtxt_state_restores_processed_video_no_result_state_to_web_movie_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'ACZD-072', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET release_date = ?, javtxt_enrichment_status = ?, javtxt_enrichment_error = ?
                    WHERE code = ?
                    ''',
                    ('2022-12-09', NO_SEARCH_RESULTS_STATUS, '未搜索到匹配影片', 'ACZD-072'),
                )
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'ACZD',
                        'ACZD-072',
                        'ACZD-072',
                        '',
                        '2022-12-09',
                        'https://example.com/movies/aczd-072',
                        1,
                        UNENRICHED_STATUS,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'Actor A',
                        'ACZD-072',
                        'ACZD-072',
                        '',
                        '2022-12-09',
                        'https://example.com/movies/aczd-072',
                        1,
                        UNENRICHED_STATUS,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.commit()

            db.sanitize_ineligible_javtxt_state()

            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT
                        (SELECT javtxt_enrichment_status FROM code_prefix_movies WHERE prefix = ? AND code = ?),
                        (SELECT javtxt_enrichment_status FROM actor_movies WHERE actor_name = ? AND code = ?)
                    ''',
                    ('ACZD', 'ACZD-072', 'Actor A', 'ACZD-072'),
                ).fetchone()

        self.assertEqual(rows, (NO_SEARCH_RESULTS_STATUS, NO_SEARCH_RESULTS_STATUS))

    def test_sanitize_ineligible_javtxt_state_refreshes_stale_library_parent_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.save_code_prefix_enrichment('AARM', ENRICHED_STATUS, source_key=JAVTXT_VIDEO_SOURCE)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'AARM',
                        'AARM-001',
                        'AARM-001',
                        '',
                        '2022-12-09',
                        'https://example.com/movies/aarm-001',
                        1,
                        UNENRICHED_STATUS,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                    ),
                )
                conn.commit()

            db.sanitize_ineligible_javtxt_state()
            record = db.get_code_prefix_enrichment_record('AARM')

        self.assertEqual(record['javtxt_enrichment_status'], UNENRICHED_STATUS)

    def test_reset_actor_enrichments_binghuo_clears_only_binghuo_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.save_actor_enrichment('Actor Binghuo', ENRICHED_STATUS, actor_id='actor-1')
            db.save_binghuo_actor_profile(
                'Actor Binghuo',
                ENRICHED_STATUS,
                person_id='bh-1',
                birthday='1990-01-01',
                age='35',
                height='168',
                bust='88',
                waist='60',
                hip='90',
                error='old error',
            )

            reset_count = db.reset_actor_enrichments(['Actor Binghuo'], source_key=BINGHUO_ACTOR_SOURCE)
            record = db.get_actor_enrichment_record('Actor Binghuo')

        self.assertEqual(reset_count, 1)
        self.assertEqual(record['actor_id'], 'actor-1')
        self.assertEqual(record['avfan_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(record['binghuo_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['binghuo_person_id'], '')
        self.assertEqual(record['binghuo_birthday'], '')
        self.assertEqual(record['binghuo_age'], '')
        self.assertEqual(record['binghuo_height'], '')
        self.assertEqual(record['binghuo_bust'], '')
        self.assertEqual(record['binghuo_waist'], '')
        self.assertEqual(record['binghuo_hip'], '')

    def test_reset_actor_enrichments_baomu_resets_status_without_clearing_saved_profile_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.save_actor_enrichment('Actor Baomu', ENRICHED_STATUS, actor_id='actor-1')
            db.save_binghuo_actor_profile(
                'Actor Baomu',
                ENRICHED_STATUS,
                person_id='bh-1',
                birthday='1990-01-01',
                age='35',
                height='168',
                bust='88',
                cup='F',
                waist='60',
                hip='90',
            )
            db.save_baomu_actor_profile(
                'Actor Baomu',
                FAILED_STATUS,
                birthday='1991-02-03',
                height='169',
                bust='89',
                cup='G',
                waist='61',
                hip='91',
                error='old error',
            )

            reset_count = db.reset_actor_enrichments(['Actor Baomu'], source_key=BAOMU_ACTOR_SOURCE)
            record = db.get_actor_enrichment_record('Actor Baomu')

        self.assertEqual(reset_count, 1)
        self.assertEqual(record['actor_id'], 'actor-1')
        self.assertEqual(record['binghuo_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(record['binghuo_height'], '168')
        self.assertEqual(record['binghuo_cup'], 'F')
        self.assertEqual(record['baomu_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['baomu_last_error'], '')
        self.assertEqual(record['baomu_birthday'], '1991-02-03')
        self.assertEqual(record['baomu_height'], '169')
        self.assertEqual(record['baomu_bust'], '89')
        self.assertEqual(record['baomu_cup'], 'G')
        self.assertEqual(record['baomu_waist'], '61')
        self.assertEqual(record['baomu_hip'], '91')

    def test_reopen_database_sanitizes_legacy_actor_avfan_status_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        enrichment_status,
                        avfan_enrichment_status,
                        javtxt_enrichment_status,
                        binghuo_enrichment_status
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        'Actor Legacy',
                        '天陨阁: 未补全 | 辛聚阁: 未补全 | 并火: 无视频详情',
                        '天陨阁: 未补全 | 辛聚阁: 未补全',
                        UNENRICHED_STATUS,
                        NO_VIDEO_DETAIL_STATUS,
                    ),
                )
                conn.commit()

            reopened = VideoDatabase(db_path)
            record = reopened.get_actor_enrichment_record('Actor Legacy')

        self.assertEqual(record['avfan_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['javtxt_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['binghuo_enrichment_status'], NO_VIDEO_DETAIL_STATUS)

    def test_sanitize_ineligible_javtxt_state_converts_processed_video_state_to_terminal_no_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'CEMD-046', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE processed_videos
                    SET title = ?,
                        release_date = ?,
                        javtxt_release_date = ?,
                        javtxt_title = ?,
                        javtxt_actors = ?,
                        javtxt_actors_raw = ?,
                        javtxt_tags = ?,
                        javtxt_movie_id = ?,
                        javtxt_url = ?,
                        javtxt_enrichment_status = ?
                    WHERE code = ?
                    ''',
                    (
                        '羽月希22時間03分ベスト',
                        '2021-08-07',
                        '2021-08-07',
                        '羽月希22時間03分ベスト',
                        '演员A',
                        '演员A',
                        '16小时以上作品 女优精选集',
                        '381297',
                        'https://javtxt.top/v/381297',
                        ENRICHED_STATUS,
                        'CEMD-046',
                    ),
                )
                conn.commit()

            db.sanitize_ineligible_javtxt_state()

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_actors, javtxt_actors_raw, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('CEMD-046',),
                ).fetchone()

        self.assertEqual(
            row,
            (
                NO_SEARCH_RESULTS_STATUS,
                '',
                '',
                '',
                '',
                '16小时以上作品 女优精选集',
            ),
        )

    def test_replace_code_prefix_movies_clears_actor_state_without_javtxt_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                'AGMX',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'AGMX-151',
                        'author': '婕斿憳鐢?婕斿憳涔?',
                        'author_raw': '婕斿憳鐢?婕斿憳涔?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://example.com/movies/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            movie = db.list_code_prefix_movies('AGMX')[0]

        self.assertEqual(movie['author'], '')
        self.assertEqual(movie['author_raw'], '')
        self.assertEqual(movie['javtxt_enrichment_status'], UNENRICHED_STATUS)

    def test_replace_actor_movies_clears_actor_state_without_javtxt_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'AGMX-151',
                        'author': '婕斿憳鐢?婕斿憳涔?',
                        'author_raw': '婕斿憳鐢?婕斿憳涔?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://example.com/movies/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(movie['author'], '')
        self.assertEqual(movie['author_raw'], '')
        self.assertEqual(movie['javtxt_enrichment_status'], UNENRICHED_STATUS)

    def test_save_javtxt_cache_for_video_rejects_enriched_actor_state_without_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'AGMX-151', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "UPDATE processed_videos SET release_date = ?, javtxt_release_date = ? WHERE code = ?",
                    ('2025-01-01', '2025-01-01', 'AGMX-151'),
                )
                conn.commit()

            db.save_javtxt_cache_for_video(
                'AGMX-151',
                {
                    'javtxt_title': 'AGMX-151 title',
                    'javtxt_actors': '婕斿憳鐢?婕斿憳涔?',
                    'javtxt_actors_raw': '婕斿憳鐢?婕斿憳涔?',
                    'release_date': '2025-01-01',
                },
                status=ENRICHED_STATUS,
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT javtxt_actors, javtxt_actors_raw, javtxt_enrichment_status, javtxt_movie_id, javtxt_url
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('AGMX-151',),
                ).fetchone()

        self.assertEqual(row[:3], ('', '', UNENRICHED_STATUS))
        self.assertFalse(row[3])
        self.assertFalse(row[4])

    def test_replace_code_prefix_movies_preserves_existing_javtxt_state_during_avfan_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.replace_code_prefix_movies(
                'AGMX',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'old title',
                        'author': '婕斿憳鐢?',
                        'author_raw': '婕斿憳鐢?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/old/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '151',
                        'javtxt_url': 'https://javtxt.top/v/151',
                        'javtxt_tags': '浜哄',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            db.replace_code_prefix_movies(
                'AGMX',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'fresh avfan title',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/new/agmx-151',
                        'javtxt_enrichment_status': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_release_date': '',
                    }
                ],
            )

            movie = db.list_code_prefix_movies('AGMX')[0]

        self.assertEqual(movie['avfan_url'], 'https://avfan.example/new/agmx-151')
        self.assertEqual(movie['javtxt_movie_id'], '151')
        self.assertEqual(movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(movie['author'], '婕斿憳鐢?')
        self.assertEqual(movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_replace_actor_movies_preserves_existing_javtxt_state_during_avfan_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'old title',
                        'author': '婕斿憳鐢?',
                        'author_raw': '婕斿憳鐢?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/old/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '151',
                        'javtxt_url': 'https://javtxt.top/v/151',
                        'javtxt_tags': '浜哄',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'fresh avfan title',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/new/agmx-151',
                        'javtxt_enrichment_status': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_release_date': '',
                    }
                ],
            )

            movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(movie['avfan_url'], 'https://avfan.example/new/agmx-151')
        self.assertEqual(movie['javtxt_movie_id'], '151')
        self.assertEqual(movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(movie['author'], '婕斿憳鐢?')
        self.assertEqual(movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_replace_code_prefix_movies_propagates_javtxt_state_to_actor_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'actor row',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/actor/agmx-151',
                    }
                ],
            )

            db.replace_code_prefix_movies(
                'AGMX',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'prefix row',
                        'author': '婕斿憳鐢?',
                        'author_raw': '婕斿憳鐢?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/prefix/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '151',
                        'javtxt_url': 'https://javtxt.top/v/151',
                        'javtxt_tags': '浜哄',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            actor_movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(actor_movie['avfan_url'], 'https://avfan.example/actor/agmx-151')
        self.assertEqual(actor_movie['javtxt_movie_id'], '151')
        self.assertEqual(actor_movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(actor_movie['author'], '婕斿憳鐢?')
        self.assertEqual(actor_movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_replace_actor_movies_propagates_javtxt_state_to_code_prefix_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.replace_code_prefix_movies(
                'AGMX',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'prefix row',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/prefix/agmx-151',
                    }
                ],
            )

            db.replace_actor_movies(
                'Actor A',
                [
                    {
                        'code': 'AGMX-151',
                        'title': 'actor row',
                        'author': '婕斿憳鐢?',
                        'author_raw': '婕斿憳鐢?',
                        'release_date': '2025-01-01',
                        'avfan_url': 'https://avfan.example/actor/agmx-151',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': '151',
                        'javtxt_url': 'https://javtxt.top/v/151',
                        'javtxt_tags': '浜哄',
                        'javtxt_release_date': '2025-01-01',
                    }
                ],
            )

            prefix_movie = db.list_code_prefix_movies('AGMX')[0]

        self.assertEqual(prefix_movie['avfan_url'], 'https://avfan.example/prefix/agmx-151')
        self.assertEqual(prefix_movie['javtxt_movie_id'], '151')
        self.assertEqual(prefix_movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(prefix_movie['author'], '婕斿憳鐢?')
        self.assertEqual(prefix_movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_list_code_prefix_movies_returns_javtxt_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'ACZD', 'ACZD-050', 'ACZD-050', '', '2025-02-01', 'https://example.com/movies/aczd-050', 1,
                        NO_SEARCH_RESULTS_STATUS, '', '', '', '2025-02-01', '', '',
                    ),
                )
                conn.commit()

            movie = db.list_code_prefix_movies('ACZD')[0]

        self.assertEqual(movie['javtxt_release_date'], '2025-02-01')

    def test_list_actor_movies_returns_javtxt_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                        javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'Actor A', 'ACZD-050', 'ACZD-050', '', '2025-02-01', 'https://example.com/movies/aczd-050', 1,
                        NO_SEARCH_RESULTS_STATUS, '', '', '', '2025-02-01', '', '',
                    ),
                )
                conn.commit()

            movie = db.list_actor_movies('Actor A')[0]

        self.assertEqual(movie['javtxt_release_date'], '2025-02-01')


class _StubDatabase:
    def get_javtxt_actor_cache_by_codes(self, codes):
        return {}

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        return 0


class _StubCacheDatabase(_StubDatabase):
    def __init__(self, cache_rows):
        self.cache_rows = dict(cache_rows or {})

    def get_javtxt_actor_cache_by_codes(self, codes):
        results = {}
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            row = self.cache_rows.get(normalized_code)
            if row:
                results[normalized_code] = dict(row)
        return results


class _StubScraper:
    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        return {
            'code': code,
            'found': True,
            'title': 'old movie',
            'javtxt_title': 'old movie',
            'author': '演员A',
            'javtxt_actors': '演员A',
            'javtxt_actors_raw': '演员A',
            'release_date': '2018-05-13',
            'javtxt_tags': '人妻',
            'javtxt_movie_id': '272298',
            'javtxt_url': 'https://javtxt.top/v/272298',
        }


class _EligibleStubScraper:
    def __init__(self):
        self.fetch_count = 0

    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        self.fetch_count += 1
        return {
            'code': code,
            'found': True,
            'title': 'new movie',
            'javtxt_title': 'new movie',
            'author': '婕斿憳A',
            'javtxt_actors': '婕斿憳A',
            'javtxt_actors_raw': '婕斿憳A',
            'release_date': '2025-05-13',
            'javtxt_tags': '浜哄',
            'javtxt_movie_id': '502298',
            'javtxt_url': 'https://javtxt.top/v/502298',
        }


class _FailOnFetchScraper:
    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        raise AssertionError(f'fetch_by_code should not be called for {code}')


class MovieAuthorResolverEligibilityTest(unittest.TestCase):
    def test_javtxt_result_with_old_release_date_is_downgraded(self):
        resolver = MovieAuthorResolver(_StubDatabase(), scraper=_StubScraper())
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'NSPS-702',
                    'title': 'legacy movie',
                    'author': '',
                    'release_date': '2020-12-22',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(entry['release_date'], '2018-05-13')
        self.assertEqual(entry['javtxt_enrichment_status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(entry['javtxt_movie_id'], '')
        self.assertEqual(entry['javtxt_url'], '')

    def test_cached_no_result_with_release_date_is_not_retried(self):
        resolver = MovieAuthorResolver(
            _StubCacheDatabase(
                {
                    'ACZD-072': {
                        'code': 'ACZD-072',
                        'javtxt_actors': '',
                        'javtxt_actors_raw': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                        'javtxt_release_date': '',
                        'release_date': '2022-12-09',
                    }
                }
            ),
            scraper=_FailOnFetchScraper(),
        )
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'ACZD072',
                    'title': 'ACZD-072',
                    'author': '',
                    'release_date': '2022-12-09',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(result['processed_video_count'], 0)
        self.assertEqual(result['pending_video_count'], 0)
        self.assertEqual(entry['code'], 'ACZD072')

    def test_cached_no_detail_with_release_date_is_not_retried(self):
        resolver = MovieAuthorResolver(
            _StubCacheDatabase(
                {
                    'STARS-225': {
                        'code': 'STARS-225',
                        'javtxt_actors': '',
                        'javtxt_actors_raw': '',
                        'javtxt_movie_id': '',
                        'javtxt_url': '',
                        'javtxt_tags': '',
                        'javtxt_enrichment_status': NO_VIDEO_DETAIL_STATUS,
                        'javtxt_release_date': '',
                        'release_date': '2020-04-07',
                    }
                }
            ),
            scraper=_FailOnFetchScraper(),
        )
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'STARS225',
                    'title': 'STARS-225',
                    'author': '',
                    'release_date': '2020-04-07',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(result['processed_video_count'], 0)
        self.assertEqual(result['pending_video_count'], 0)
        self.assertEqual(entry['code'], 'STARS225')

    def test_same_batch_cached_result_applies_javtxt_detail_fields_to_duplicate_code(self):
        scraper = _EligibleStubScraper()
        resolver = MovieAuthorResolver(_StubDatabase(), scraper=scraper)
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123',
                    'author': '',
                    'release_date': '2025-05-13',
                },
                {
                    'code': 'ABP-123',
                    'title': 'ABP-123 duplicate',
                    'author': '',
                    'release_date': '2025-05-13',
                },
            ]
        )

        self.assertEqual(scraper.fetch_count, 1)
        self.assertEqual(result['entries'][0]['javtxt_url'], 'https://javtxt.top/v/502298')
        self.assertEqual(result['entries'][1]['javtxt_url'], 'https://javtxt.top/v/502298')
        self.assertEqual(result['entries'][1]['javtxt_movie_id'], '502298')


if __name__ == '__main__':
    unittest.main()
