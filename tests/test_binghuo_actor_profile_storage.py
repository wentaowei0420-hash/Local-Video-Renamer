import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.library import LibraryAdminService


class BinghuoActorProfileStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
        self.db = VideoDatabase(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_binghuo_profile_persists_fields_and_syncs_actor_birthday_age(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                ('演员A', '', ''),
            )
            conn.commit()

        self.db.save_binghuo_actor_profile(
            '演员A',
            ENRICHED_STATUS,
            person_id='5921',
            birthday='2003-09-04',
            age='22',
            height='172',
            bust='85',
            cup='E',
            measurements_raw='B:85(E) W:60 H:88',
            waist='60',
            hip='88',
        )

        record = self.db.get_actor_enrichment_record('演员A')
        actor_row = self.db.list_actors('演员A')[0]

        self.assertEqual(record['binghuo_person_id'], '5921')
        self.assertEqual(record['binghuo_enrichment_status'], ENRICHED_STATUS)
        self.assertEqual(record['binghuo_birthday'], '2003-09-04')
        self.assertEqual(record['binghuo_age'], '22')
        self.assertEqual(record['binghuo_height'], '172')
        self.assertEqual(record['binghuo_bust'], '85')
        self.assertEqual(record['binghuo_cup'], 'E')
        self.assertEqual(record['binghuo_measurements_raw'], 'B:85(E) W:60 H:88')
        self.assertEqual(record['binghuo_waist'], '60')
        self.assertEqual(record['binghuo_hip'], '88')
        self.assertEqual(actor_row['birthday'], '2003/9/4')
        self.assertEqual(actor_row['raw_age'], '22')

    def test_save_binghuo_profile_normalizes_slash_birthday_to_iso(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                ('演员Slash', '', ''),
            )
            conn.commit()

        self.db.save_binghuo_actor_profile(
            '演员Slash',
            ENRICHED_STATUS,
            person_id='8001',
            birthday='2002/9/18',
            age='23',
        )

        record = self.db.get_actor_enrichment_record('演员Slash')
        actor_row = self.db.list_actors('演员Slash')[0]
        with sqlite3.connect(self.db_path) as conn:
            stored_birthday = conn.execute(
                "SELECT birthday FROM actors WHERE name = ?",
                ('演员Slash',),
            ).fetchone()[0]

        self.assertEqual(record['binghuo_birthday'], '2002-09-18')
        self.assertEqual(stored_birthday, '2002-09-18')
        self.assertEqual(actor_row['birthday'], '2002/9/18')

    def test_save_partial_binghuo_profile_updates_age_without_filling_missing_birthday(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                ('演员Partial', '', ''),
            )
            conn.commit()

        self.db.save_binghuo_actor_profile(
            '演员Partial',
            UNENRICHED_STATUS,
            person_id='7001',
            birthday='',
            age='29',
            height='168',
            bust='86',
            waist='59',
            hip='88',
        )

        record = self.db.get_actor_enrichment_record('演员Partial')
        actor_row = self.db.list_actors('演员Partial')[0]

        self.assertEqual(record['binghuo_person_id'], '7001')
        self.assertEqual(record['binghuo_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(record['binghuo_birthday'], '')
        self.assertEqual(record['binghuo_age'], '29')
        self.assertEqual(actor_row['birthday'], '')
        self.assertEqual(actor_row['raw_age'], '29')

    def test_library_admin_add_actor_reuses_saved_binghuo_birthday_and_age(self):
        self.db.save_binghuo_actor_profile(
            '演员B',
            ENRICHED_STATUS,
            person_id='6001',
            birthday='2000-01-02',
            age='26',
        )

        created_count = LibraryAdminService(self.db).add_actor('演员B')

        actor_row = self.db.list_actors('演员B')[0]
        self.assertEqual(created_count, 1)
        self.assertEqual(actor_row['birthday'], '2000/1/2')
        self.assertEqual(actor_row['raw_age'], '26')

    def test_missing_binghuo_result_is_stored_for_future_skip(self):
        self.db.save_binghuo_actor_profile(
            '演员C',
            NO_SEARCH_RESULTS_STATUS,
            error='无搜索结果',
        )

        record = self.db.get_actor_enrichment_record('演员C')

        self.assertEqual(record['binghuo_enrichment_status'], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(record['binghuo_last_error'], '无搜索结果')
        self.assertEqual(record['avfan_enrichment_status'], UNENRICHED_STATUS)


if __name__ == '__main__':
    unittest.main()
