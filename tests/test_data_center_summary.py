import gc
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, BINGHUO_ACTOR_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.data.database_handler import VideoDatabase
from app.services.library import DataCenterService
from app.services.video import VideoFilterService


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

    def test_actor_javtxt_summary_deduplicates_same_video_code_across_multiple_actors(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Resolved Video",
                author="Actor A Actor B",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
            )

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [("Actor A",), ("Actor B",)],
                )
                conn.commit()

            shared_movie = self._build_library_movie(
                "AAA-001",
                "Resolved Video",
                "Actor A Actor B",
                "2024-01-01",
                ENRICHED_STATUS,
                "m1",
                "https://example.com/1",
            )
            db.replace_actor_movies("Actor A", [shared_movie])
            db.replace_actor_movies("Actor B", [shared_movie])

            summary = DataCenterService(db).get_summary()
            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]

            self.assertEqual(actor_summary["total_count"], 1)
            self.assertEqual(actor_summary["success_count"], 1)
            self.assertEqual(actor_summary["pending_count"], 0)

            del summary
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_filtered_videos_are_excluded_from_video_based_data_center_stats(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            self._seed_processed_video(
                db_path,
                code="AAA-001",
                title="Visible Video",
                author="Actor A",
                release_date="2024-01-01",
                status=ENRICHED_STATUS,
                movie_id="m1",
                url="https://example.com/1",
                avfan_status=ENRICHED_STATUS,
            )
            self._seed_processed_video(
                db_path,
                code="AAA-002",
                title="Filtered Collection",
                author="Actor A",
                release_date="2024-01-02",
                status=ENRICHED_STATUS,
                movie_id="m2",
                url="https://example.com/2",
                avfan_status=ENRICHED_STATUS,
            )

            movies = [
                self._build_library_movie("AAA-001", "Visible Video", "Actor A", "2024-01-01", ENRICHED_STATUS, "m1", "https://example.com/1"),
                self._build_library_movie("AAA-002", "Filtered Collection", "Actor A", "2024-01-02", ENRICHED_STATUS, "m2", "https://example.com/2"),
            ]
            db.replace_code_prefix_movies("AAA", movies)

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ("Actor A",),
                )
                conn.commit()

            db.replace_actor_movies("Actor A", movies)

            filter_service = VideoFilterService(
                settings_loader=lambda: {
                    "rules": {
                        "code": [],
                        "title": ["Collection"],
                        "javtxt_tags": [],
                    }
                }
            )
            summary = DataCenterService(db, video_filter_service=filter_service).get_summary()

            video_avfan_summary = summary["video_library"]["sources"][AVFAN_VIDEO_SOURCE]
            self.assertEqual(video_avfan_summary["total_count"], 1)
            self.assertEqual(video_avfan_summary["success_count"], 1)

            video_javtxt_summary = summary["video_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(video_javtxt_summary["total_count"], 1)
            self.assertEqual(video_javtxt_summary["success_count"], 1)

            code_prefix_summary = summary["code_prefix_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(code_prefix_summary["total_count"], 1)
            self.assertEqual(code_prefix_summary["success_count"], 1)

            actor_summary = summary["actor_library"]["sources"][JAVTXT_VIDEO_SOURCE]
            self.assertEqual(actor_summary["total_count"], 1)
            self.assertEqual(actor_summary["success_count"], 1)

            del summary
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_binghuo_summary_counts_incomplete_profiles_as_no_detail(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [
                        ("Actor Success",),
                        ("Actor Partial",),
                        ("Actor No Search",),
                        ("Actor Failed",),
                        ("Actor Pending",),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_enrichment_status,
                        binghuo_person_id,
                        binghuo_birthday,
                        binghuo_height
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor Success", ENRICHED_STATUS, "1001", "1990-01-01", "168"),
                        ("Actor Partial", NO_VIDEO_DETAIL_STATUS, "", "", "170"),
                        ("Actor No Search", NO_SEARCH_RESULTS_STATUS, "", "", ""),
                        ("Actor Failed", FAILED_STATUS, "", "", ""),
                    ],
                )
                conn.commit()

            summary = DataCenterService(db).get_summary_snapshot()["summary"]
            binghuo_summary = summary["actor_library"]["sources"][BINGHUO_ACTOR_SOURCE]

            self.assertEqual(binghuo_summary["total_count"], 5)
            self.assertEqual(binghuo_summary["success_count"], 1)
            self.assertEqual(binghuo_summary["no_search_count"], 1)
            self.assertEqual(binghuo_summary["no_detail_count"], 1)
            self.assertEqual(binghuo_summary["failed_count"], 1)
            self.assertEqual(binghuo_summary["pending_count"], 1)
            self.assertEqual(binghuo_summary["enriched_count"], 3)
            self.assertEqual(binghuo_summary["progress_percent"], 60.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_summary_cache_only_rebuilds_on_manual_refresh(self):
        service = DataCenterService(database=None)
        built_values = [{"version": 1}, {"version": 2}]

        with patch.object(service, "_load_filter_settings", return_value=None), patch.object(
            service,
            "_build_summary",
            side_effect=built_values,
        ) as build_summary_mock, patch.object(
            service,
            "_current_cache_timestamp",
            side_effect=["2026-06-21 10:00:00", "2026-06-21 10:05:00"],
        ):
            first = service.get_summary_snapshot()
            second = service.get_summary_snapshot()
            refreshed = service.get_summary_snapshot(force_refresh=True)

        self.assertEqual(build_summary_mock.call_count, 2)
        self.assertEqual(first["summary"]["version"], 1)
        self.assertEqual(second["summary"]["version"], 1)
        self.assertEqual(refreshed["summary"]["version"], 2)
        self.assertEqual(first["refreshed_at"], "2026-06-21 10:00:00")
        self.assertEqual(second["refreshed_at"], "2026-06-21 10:00:00")
        self.assertEqual(refreshed["refreshed_at"], "2026-06-21 10:05:00")

    def test_actor_metric_analysis_builds_distribution_and_top_rankings(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "video_database.db"
            db = VideoDatabase(db_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', ?, 0)",
                    [
                        ("Actor A", "70"),
                        ("Actor B", "69"),
                        ("Actor C", ""),
                        ("Actor D", "70"),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO actor_enrichments (
                        actor_name,
                        binghuo_height,
                        binghuo_bust,
                        binghuo_waist,
                        binghuo_hip
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Actor A", "179", "90", "60", "92"),
                        ("Actor B", "168", "84", "58", "88"),
                        ("Actor D", "175", "", "", ""),
                    ],
                )
                conn.commit()

            service = DataCenterService(db)

            age_analysis = service.get_actor_metric_analysis_snapshot("age")
            self.assertEqual(
                age_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "70岁", "count": 2},
                    {"label": "69岁", "count": 1},
                    {"label": "无数据", "count": 1},
                ],
            )
            self.assertEqual(
                age_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "70岁", "numeric_value": 70},
                    {"actor_name": "Actor D", "display_value": "70岁", "numeric_value": 70},
                    {"actor_name": "Actor B", "display_value": "69岁", "numeric_value": 69},
                ],
            )

            height_analysis = service.get_actor_metric_analysis_snapshot("height")
            self.assertEqual(
                height_analysis["analysis"]["distribution_rows"],
                [
                    {"label": "179 cm", "count": 1},
                    {"label": "175 cm", "count": 1},
                    {"label": "168 cm", "count": 1},
                    {"label": "无数据", "count": 1},
                ],
            )
            self.assertEqual(
                height_analysis["analysis"]["ranking_rows"][:3],
                [
                    {"actor_name": "Actor A", "display_value": "179 cm", "numeric_value": 179},
                    {"actor_name": "Actor D", "display_value": "175 cm", "numeric_value": 175},
                    {"actor_name": "Actor B", "display_value": "168 cm", "numeric_value": 168},
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _seed_processed_video(
        db_path,
        code,
        title,
        author,
        release_date,
        status,
        movie_id="",
        url="",
        avfan_status=UNENRICHED_STATUS,
        javtxt_tags="",
    ):
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    code,
                    title,
                    author,
                    release_date,
                    release_date,
                    UNENRICHED_STATUS,
                    avfan_status,
                    status,
                    movie_id,
                    url,
                    author if status == ENRICHED_STATUS else "",
                    author if status == ENRICHED_STATUS else "",
                    javtxt_tags,
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
