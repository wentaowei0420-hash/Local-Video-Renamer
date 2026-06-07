import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.data_center_service import DataCenterService


class DataCenterSummarySplitCountsTest(unittest.TestCase):
    def test_javtxt_summary_keeps_no_detail_separate_from_no_search(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Resolved Video",
                author="Actor A",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="No Search Video",
                author="Actor A",
                release_date="2024-01-02",
                status=NO_SEARCH_RESULTS_STATUS,
            )
            self._seed_processed_video(
                db_path,
                code="AAA-003",
                title="No Detail Video",
                author="Actor A",
                release_date="2024-01-03",
                status=NO_VIDEO_DETAIL_STATUS,
            )

            db.replace_code_prefix_movies(
                "AAA",
                [
                    self._build_library_movie("AAA-001", "Resolved Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "Actor A", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie("AAA-003", "No Detail Video", "Actor A", "2024-01-03", NO_VIDEO_DETAIL_STATUS),
                ],
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies(
                "Actor A",
                [
                    self._build_library_movie("AAA-001", "Resolved Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                    self._build_library_movie("AAA-002", "No Search Video", "Actor A", "2024-01-02", NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie("AAA-003", "No Detail Video", "Actor A", "2024-01-03", NO_VIDEO_DETAIL_STATUS),
                ],
            )

            service = DataCenterService(db)
            summary = service.get_summary()

            video_summary = summary["video_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(video_summary["success_count"], 1)
            self.assertEqual(video_summary["no_search_count"], 1)
            self.assertEqual(video_summary["no_detail_count"], 1)

            code_prefix_summary = summary["code_prefix_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(code_prefix_summary["success_count"], 1)
            self.assertEqual(code_prefix_summary["no_search_count"], 1)
            self.assertEqual(code_prefix_summary["no_detail_count"], 1)

            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(actor_summary["success_count"], 1)
            self.assertEqual(actor_summary["no_search_count"], 1)
            self.assertEqual(actor_summary["no_detail_count"], 1)

            del summary
            del service
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _seed_processed_video(db_path, code, title, author, release_date, status, movie_id="", url=""):
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')
                """,
                (
                    code,
                    title,
                    author,
                    release_date,
                    release_date,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    status,
                    movie_id,
                    url,
                    author if status == ENRICHED_STATUS else "",
                    author if status == ENRICHED_STATUS else "",
                ),
            )
            conn.commit()

    @staticmethod
    def _build_library_movie(code, title, author, release_date, status, movie_id="", url=""):
        return {
            "code": code,
            "title": title,
            "author": author if status == ENRICHED_STATUS else "",
            "author_raw": author if status == ENRICHED_STATUS else "",
            "release_date": release_date,
            "avfan_url": "",
            "page_number": 1,
            "javtxt_enrichment_status": status,
            "javtxt_movie_id": movie_id,
            "javtxt_url": url,
            "javtxt_tags": "",
            "javtxt_release_date": release_date,
            "video_category": "",
        }


if __name__ == "__main__":
    unittest.main()
