import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import UNENRICHED_STATUS
from app.core.video_filter_rules import DEFAULT_VIDEO_FILTER_SETTINGS, matches_filter_keywords
from app.data.database_handler import VideoDatabase
from app.services.video_filter_service import VideoFilterService


class VideoFilterServiceTest(unittest.TestCase):
    def test_javtxt_pre_enrichment_filter_skips_code_and_title_keywords(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            self._seed_processed_video(db_path, 'AAA-001', '普通标题', '2024-01-01')
            self._seed_processed_video(db_path, 'BBB-002', '要跳过的标题', '2024-01-02')
            self._seed_processed_video(db_path, 'SKIP-003', '另一条普通标题', '2024-01-03')

            service = VideoFilterService(settings_loader=lambda: {
                'rules': {
                    'code': ['skip-'],
                    'title': ['跳过'],
                    'javtxt_tags': [],
                }
            })
            candidate_filter = service.build_pre_enrichment_filter()

            rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE, candidate_filter=candidate_filter)
            pending_count = db.count_pending_video_enrichments(JAVTXT_VIDEO_SOURCE, candidate_filter=candidate_filter)

            self.assertEqual([row['code'] for row in rows], ['AAA-001'])
            self.assertEqual(pending_count, 1)

            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_library_hide_filter_only_uses_javtxt_tags(self):
        service = VideoFilterService(settings_loader=lambda: {
            'rules': {
                'code': ['aaa'],
                'title': ['普通'],
                'javtxt_tags': ['隐藏标签'],
            }
        })

        visible_rows = service.filter_library_rows(
            [
                {'code': 'CCC-001', 'title': '别的标题', 'javtxt_tags': '公开标签'},
                {'code': 'BBB-002', 'title': '别的标题', 'javtxt_tags': '隐藏标签 其他标签'},
            ]
        )

        self.assertEqual([row['code'] for row in visible_rows], ['CCC-001'])

    def test_post_enrichment_hide_uses_code_and_title_but_not_for_unenriched_rows(self):
        service = VideoFilterService(settings_loader=lambda: {
            'rules': {
                'code': ['skip'],
                'title': ['合集'],
                'javtxt_tags': [],
            }
        })

        visible_rows = service.filter_video_rows(
            [
                {'code': 'SKIP-001', 'title': '普通标题', 'javtxt_enrichment_status': UNENRICHED_STATUS},
                {'code': 'SKIP-002', 'title': '普通标题', 'javtxt_enrichment_status': '已补全'},
                {'code': 'AAA-003', 'title': '合集作品', 'javtxt_url': 'https://example.com/3'},
            ]
        )

        self.assertEqual([row['code'] for row in visible_rows], ['SKIP-001'])

    def test_default_filter_settings_include_legacy_title_and_tag_keywords(self):
        self.assertIn('VR', DEFAULT_VIDEO_FILTER_SETTINGS['rules']['title'])
        self.assertIn('合集', DEFAULT_VIDEO_FILTER_SETTINGS['rules']['title'])
        self.assertIn('精选合集', DEFAULT_VIDEO_FILTER_SETTINGS['rules']['javtxt_tags'])

    def test_vr_keyword_matches_legacy_spaced_marker(self):
        self.assertTrue(matches_filter_keywords('这是一个 V R 作品', ['VR']))

    @staticmethod
    def _seed_processed_video(db_path, code, title, release_date):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    release_date,
                    javtxt_release_date,
                    enrichment_status,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_actors,
                    javtxt_actors_raw,
                    javtxt_tags,
                    video_category
                )
                VALUES (?, ?, '', ?, ?, ?, ?, ?, '', '', '', '', '', '')
                """,
                (
                    code,
                    title,
                    release_date,
                    release_date,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                ),
            )
            conn.commit()


if __name__ == '__main__':
    unittest.main()
