import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.core.filename_rules import extract_code_from_filename
from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.video_code import compact_video_code, has_supported_video_code, standardize_video_code
from app.data.database_handler import VideoDatabase
from app.scraper.javtxt_scraper import extract_page_code
from app.services.code_prefix_entry_parser import extract_code


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
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('actor', '168BOUZ-004', 'title', '', '2025-04-29', 'done', '506760', 'https://javtxt.top/v/506760'),
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


if __name__ == '__main__':
    unittest.main()
