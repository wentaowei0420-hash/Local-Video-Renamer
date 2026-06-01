import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import contextmanager
from pathlib import Path

from app.core.filename_rules import extract_code_from_filename
from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.video_code import compact_video_code, has_supported_video_code, standardize_video_code
from app.data.database_handler import VideoDatabase
from app.scraper.javtxt_scraper import extract_page_code
from app.services.code_prefix_entry_parser import extract_code
from app.services.movie_author_resolver import MovieAuthorResolver
from app.services.video_category_service import (
    MANUAL_CATEGORY_TIER_FIRST,
    MANUAL_CATEGORY_TIER_SECOND,
    MANUAL_CATEGORY_TIER_THIRD,
    classify_manual_category_tier,
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

    def test_manual_category_tier_classification(self):
        self.assertEqual(classify_manual_category_tier('甲 乙 丙 丁 戊', '甲 乙 丙 丁 戊'), MANUAL_CATEGORY_TIER_FIRST)
        self.assertEqual(classify_manual_category_tier('甲 乙 丙', '甲 乙 丙'), MANUAL_CATEGORY_TIER_SECOND)
        self.assertEqual(classify_manual_category_tier('', '未公开'), MANUAL_CATEGORY_TIER_THIRD)


class VideoCodeDatabaseMigrationTest(unittest.TestCase):
    def test_database_init_normalizes_existing_actor_movie_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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

    def test_database_init_clears_ineligible_processed_video_javtxt_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('SQTE-241',),
                ).fetchall()

        self.assertEqual(rows, [(UNENRICHED_STATUS, '', '', '')])

    def test_database_init_clears_legacy_web_movie_javtxt_state_without_trusted_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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

    def test_database_init_clears_web_movie_actor_state_without_javtxt_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
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
            VideoDatabase(db_path)
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

            VideoDatabase(db_path)
            movie = VideoDatabase(db_path).list_actor_movies('Actor A')[0]

        self.assertEqual(movie['avfan_url'], 'https://avfan.example/actor/agmx-151')
        self.assertEqual(movie['javtxt_movie_id'], '151')
        self.assertEqual(movie['javtxt_url'], 'https://javtxt.top/v/151')
        self.assertEqual(movie['author'], '婕斿憳鐢?')
        self.assertEqual(movie['javtxt_enrichment_status'], ENRICHED_STATUS)

    def test_javtxt_video_library_candidates_skip_ineligible_old_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
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

        self.assertEqual([row['code'] for row in rows], ['ABP-123', 'MIDV-001'])
        self.assertEqual(processed_row, (UNENRICHED_STATUS, ''))
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
        self.assertEqual(entry['javtxt_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(entry['javtxt_movie_id'], '272298')
        self.assertEqual(entry['javtxt_url'], 'https://javtxt.top/v/272298')

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
