import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.library_status_sync_service import LibraryStatusSyncService


class LibraryStatusSyncServiceTest(unittest.TestCase):
    def test_sync_copies_resolved_video_state_between_libraries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / "video_database.db")
            db.import_local_videos(
                [
                    {
                        "code": "ABP-123",
                        "storage_location": "D:\\videos",
                        "size": "1GB",
                    }
                ]
            )
            db.save_code_prefix_enrichment("ABP", ENRICHED_STATUS, total_pages=1, total_videos=1, source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("演员A", ENRICHED_STATUS, total_pages=1, total_videos=1, actor_id="actor-a", source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("演员A", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.save_code_prefix_enrichment("ABP", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.replace_actor_movies(
                "演员A",
                [
                    {
                        "code": "ABP-123",
                        "title": "完整标题",
                        "author": "演员A",
                        "author_raw": "演员A",
                        "release_date": "2025-02-01",
                        "avfan_url": "https://example.com/actor/abp-123",
                        "javtxt_enrichment_status": ENRICHED_STATUS,
                        "javtxt_movie_id": "mid-123",
                        "javtxt_url": "https://example.com/javtxt/abp-123",
                        "javtxt_tags": "标签1 标签2",
                        "javtxt_release_date": "2025-02-01",
                    }
                ],
            )
            db.replace_code_prefix_movies(
                "ABP",
                [
                    {
                        "code": "ABP-123",
                        "title": "ABP-123",
                        "author": "",
                        "author_raw": "",
                        "release_date": "",
                        "avfan_url": "",
                        "javtxt_enrichment_status": UNENRICHED_STATUS,
                        "javtxt_movie_id": "",
                        "javtxt_url": "",
                        "javtxt_tags": "",
                    }
                ],
            )

            result = LibraryStatusSyncService(db).sync()

            prefix_movie = db.list_code_prefix_movies("ABP")[0]
            prefix_record = db.get_code_prefix_enrichment_record("ABP")
            del db

        self.assertEqual(result["shared_code_count"], 1)
        self.assertEqual(result["updated_code_prefix_movie_count"], 1)
        self.assertEqual(prefix_movie["title"], "完整标题")
        self.assertEqual(prefix_movie["author"], "演员A")
        self.assertEqual(prefix_movie["release_date"], "2025-02-01")
        self.assertEqual(prefix_movie["javtxt_movie_id"], "mid-123")
        self.assertEqual(prefix_movie["javtxt_enrichment_status"], ENRICHED_STATUS)
        self.assertEqual(prefix_record["javtxt_enrichment_status"], ENRICHED_STATUS)

    def test_sync_applies_no_result_cache_to_other_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / "video_database.db")
            db.import_local_videos(
                [
                    {
                        "code": "IPX-456",
                        "storage_location": "D:\\videos",
                        "size": "1GB",
                    }
                ]
            )
            db.save_code_prefix_enrichment("IPX", ENRICHED_STATUS, total_pages=1, total_videos=1, source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("演员B", ENRICHED_STATUS, total_pages=1, total_videos=1, actor_id="actor-b", source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("演员B", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.replace_code_prefix_movies(
                "IPX",
                [
                    {
                        "code": "IPX-456",
                        "title": "缓存标题",
                        "author": "",
                        "author_raw": "",
                        "release_date": "2025-03-01",
                        "avfan_url": "https://example.com/prefix/ipx-456",
                        "javtxt_enrichment_status": NO_SEARCH_RESULTS_STATUS,
                        "javtxt_movie_id": "",
                        "javtxt_url": "",
                        "javtxt_tags": "",
                        "javtxt_release_date": "2025-03-01",
                    }
                ],
            )
            db.replace_actor_movies(
                "演员B",
                [
                    {
                        "code": "IPX-456",
                        "title": "IPX-456",
                        "author": "",
                        "author_raw": "",
                        "release_date": "2025-03-01",
                        "avfan_url": "",
                        "javtxt_enrichment_status": UNENRICHED_STATUS,
                        "javtxt_movie_id": "",
                        "javtxt_url": "",
                        "javtxt_tags": "",
                    }
                ],
            )
            db.save_javtxt_cache_for_video(
                "IPX-456",
                {
                    "javtxt_movie_id": "",
                    "javtxt_url": "",
                    "javtxt_title": "",
                    "javtxt_actors": "",
                    "javtxt_actors_raw": "",
                    "javtxt_tags": "",
                    "release_date": "2025-03-01",
                },
                status=NO_SEARCH_RESULTS_STATUS,
            )

            result = LibraryStatusSyncService(db).sync()

            actor_movie = db.list_actor_movies("演员B")[0]
            actor_record = db.get_actor_enrichment_record("演员B")
            del db

        self.assertEqual(result["synced_code_count"], 1)
        self.assertEqual(actor_movie["javtxt_enrichment_status"], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(actor_record["javtxt_enrichment_status"], ENRICHED_STATUS)

    def test_sync_skips_and_clears_ineligible_old_video_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / "video_database.db")
            db.import_local_videos(
                [
                    {
                        "code": "NSPS-693",
                        "storage_location": "D:\\videos",
                        "size": "1GB",
                    }
                ]
            )
            db.save_code_prefix_enrichment("NSPS", ENRICHED_STATUS, total_pages=1, total_videos=1, source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("演员C", ENRICHED_STATUS, total_pages=1, total_videos=1, actor_id="actor-c", source_key=AVFAN_VIDEO_SOURCE)
            db.save_code_prefix_enrichment("NSPS", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.save_actor_enrichment("演员C", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.replace_code_prefix_movies(
                "NSPS",
                [
                    {
                        "code": "NSPS-693",
                        "title": "旧片",
                        "author": "演员C",
                        "author_raw": "演员C",
                        "release_date": "2018-04-08",
                        "avfan_url": "https://example.com/prefix/nsps-693",
                        "javtxt_enrichment_status": ENRICHED_STATUS,
                        "javtxt_movie_id": "old-693",
                        "javtxt_url": "https://example.com/javtxt/nsps-693",
                        "javtxt_tags": "标签",
                    }
                ],
            )
            db.bulk_update_code_prefix_movies(
                [
                    {
                        "prefix": "NSPS",
                        "code": "NSPS-693",
                        "title": "旧片",
                        "author": "演员C",
                        "author_raw": "演员C",
                        "release_date": "2018-04-08",
                        "avfan_url": "https://example.com/prefix/nsps-693",
                        "javtxt_enrichment_status": ENRICHED_STATUS,
                        "javtxt_movie_id": "old-693",
                        "javtxt_url": "https://example.com/javtxt/nsps-693",
                        "javtxt_tags": "标签",
                    }
                ]
            )
            db.replace_actor_movies(
                "演员C",
                [
                    {
                        "code": "NSPS-693",
                        "title": "旧片",
                        "author": "演员C",
                        "author_raw": "演员C",
                        "release_date": "2018-04-08",
                        "avfan_url": "https://example.com/actor/nsps-693",
                        "javtxt_enrichment_status": ENRICHED_STATUS,
                        "javtxt_movie_id": "old-693",
                        "javtxt_url": "https://example.com/javtxt/nsps-693",
                        "javtxt_tags": "标签",
                    }
                ],
            )
            db.bulk_update_actor_movies(
                [
                    {
                        "actor_name": "演员C",
                        "code": "NSPS-693",
                        "title": "旧片",
                        "author": "演员C",
                        "author_raw": "演员C",
                        "release_date": "2018-04-08",
                        "avfan_url": "https://example.com/actor/nsps-693",
                        "javtxt_enrichment_status": ENRICHED_STATUS,
                        "javtxt_movie_id": "old-693",
                        "javtxt_url": "https://example.com/javtxt/nsps-693",
                        "javtxt_tags": "标签",
                    }
                ]
            )

            result = LibraryStatusSyncService(db).sync()

            prefix_movie = db.list_code_prefix_movies("NSPS")[0]
            actor_movie = db.list_actor_movies("演员C")[0]
            prefix_record = db.get_code_prefix_enrichment_record("NSPS")
            actor_record = db.get_actor_enrichment_record("演员C")
            del db

        self.assertEqual(result["synced_code_count"], 1)
        self.assertEqual(prefix_movie["javtxt_enrichment_status"], UNENRICHED_STATUS)
        self.assertEqual(prefix_movie["javtxt_movie_id"], "")
        self.assertEqual(prefix_movie["javtxt_url"], "")
        self.assertEqual(actor_movie["javtxt_enrichment_status"], UNENRICHED_STATUS)
        self.assertEqual(actor_movie["javtxt_movie_id"], "")
        self.assertEqual(actor_movie["javtxt_url"], "")
        self.assertEqual(prefix_record["javtxt_enrichment_status"], UNENRICHED_STATUS)
        self.assertEqual(actor_record["javtxt_enrichment_status"], UNENRICHED_STATUS)

    def test_sync_does_not_propagate_actor_state_without_detail_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {
                        "code": "AGMX-151",
                        "storage_location": "D:\\videos",
                        "size": "1GB",
                    }
                ]
            )
            db.save_code_prefix_enrichment("AGMX", ENRICHED_STATUS, total_pages=1, total_videos=1, source_key=AVFAN_VIDEO_SOURCE)
            db.save_actor_enrichment("婕斿憳D", ENRICHED_STATUS, total_pages=1, total_videos=1, actor_id="actor-d", source_key=AVFAN_VIDEO_SOURCE)
            db.save_code_prefix_enrichment("AGMX", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.save_actor_enrichment("婕斿憳D", UNENRICHED_STATUS, total_videos=1, source_key=JAVTXT_VIDEO_SOURCE)
            db.replace_code_prefix_movies(
                "AGMX",
                [
                    {
                        "code": "AGMX-151",
                        "title": "AGMX-151",
                        "author": "",
                        "author_raw": "",
                        "release_date": "2025-01-01",
                        "avfan_url": "https://example.com/prefix/agmx-151",
                        "javtxt_enrichment_status": UNENRICHED_STATUS,
                        "javtxt_movie_id": "",
                        "javtxt_url": "",
                        "javtxt_tags": "",
                        "javtxt_release_date": "2025-01-01",
                    }
                ],
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        "婕斿憳D",
                        "AGMX-151",
                        "polluted title",
                        "婕斿憳鐢?婕斿憳涔?",
                        "2025-01-01",
                        "https://example.com/actor/agmx-151",
                        1,
                        ENRICHED_STATUS,
                        "",
                        "",
                        "",
                        "2025-01-01",
                        "婕斿憳鐢?婕斿憳涔?",
                        "",
                    ),
                )
                conn.commit()

            LibraryStatusSyncService(db).sync()

            prefix_movie = db.list_code_prefix_movies("AGMX")[0]
            actor_movie = db.list_actor_movies("婕斿憳D")[0]
            del db

        self.assertEqual(prefix_movie["author"], "")
        self.assertEqual(prefix_movie["author_raw"], "")
        self.assertEqual(prefix_movie["javtxt_enrichment_status"], UNENRICHED_STATUS)
        self.assertEqual(actor_movie["author"], "")
        self.assertEqual(actor_movie["author_raw"], "")
        self.assertEqual(actor_movie["javtxt_enrichment_status"], UNENRICHED_STATUS)


if __name__ == "__main__":
    unittest.main()
