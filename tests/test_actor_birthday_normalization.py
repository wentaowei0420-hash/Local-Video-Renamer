import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.services.detail import ActorDetailLibrary


class ActorBirthdayNormalizationTest(unittest.TestCase):
    def test_list_actors_normalizes_birthday_display_to_slash_format(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    ('Actor Slash', '2002/9/18', '23'),
                )
                conn.commit()

            rows = db.list_actors('Actor Slash')

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['birthday'], '2002/9/18')
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_detail_normalizes_birthday_display_to_slash_format(self):
        actor_row = {
            'name': 'Actor Slash',
            'birthday': '2002/9/18',
            'age': '23',
            'matched': True,
            'actor_id': '',
        }

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [actor_row] if str(search_text or '').strip() in ('', 'Actor Slash') else []

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_videos(self):
                return []

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('Actor Slash')

        self.assertEqual(detail['birthday'], '2002/9/18')


if __name__ == '__main__':
    unittest.main()
