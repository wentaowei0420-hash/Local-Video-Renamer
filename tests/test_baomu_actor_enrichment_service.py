import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.enrichment.actor_baomu_enrichment import ActorBaomuEnrichmentService


class FakeBaomuScraper:
    def __init__(self, profiles=None, missing_names=None, errors=None):
        self.profiles = dict(profiles or {})
        self.missing_names = set(missing_names or [])
        self.errors = dict(errors or {})
        self.open_calls = []
        self._current_name = ""

    @contextmanager
    def session(self):
        yield object()

    def open_actor_page(self, _page, actor_name):
        self.open_calls.append(actor_name)
        self._current_name = actor_name
        if actor_name in self.errors:
            raise RuntimeError(self.errors[actor_name])
        return f"https://netflav.com/all?actress={actor_name}"

    def parse_profile(self, _page):
        if self._current_name in self.missing_names:
            return {}
        return dict(self.profiles.get(self._current_name, {}))


class FakeCanglanggeCandidateService:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_candidates(self):
        return [dict(row) for row in self.rows]


class ActorBaomuEnrichmentServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "video_database.db"
        self.db = VideoDatabase(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_actor(self, name, birthday="", age=""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                (name, birthday, age),
            )
            conn.commit()

    def test_candidates_require_prior_binghuo_attempt_and_prioritize_canglangge(self):
        self._insert_actor("Actor Library Missing", birthday="", age="")
        self._insert_actor("Actor Never Attempted", birthday="", age="")
        self._insert_actor("Actor Complete", birthday="2000-01-02", age="26")
        self._insert_actor("Actor Missing Cup", birthday="1999-03-04", age="27")
        self.db.save_binghuo_actor_profile("Actor Library Missing", ENRICHED_STATUS, birthday="2001-02-03", age="25", height="", bust="84", waist="58", hip="86")
        self.db.save_binghuo_actor_profile("Actor Complete", ENRICHED_STATUS, birthday="2000-01-02", age="26", height="168", bust="85", cup="C", waist="59", hip="87")
        self.db.save_binghuo_actor_profile("Actor Missing Cup", ENRICHED_STATUS, birthday="1999-03-04", age="27", height="165", bust="86", cup="", waist="58", hip="88")

        service = ActorBaomuEnrichmentService(
            self.db,
            scraper=FakeBaomuScraper(),
            candidate_service=FakeCanglanggeCandidateService(
                [
                    {"actor_name": "Actor Canglangge Missing", "birthday": "", "age": "", "prefixes": ["ROE"]},
                    {"actor_name": "Actor Library Missing", "birthday": "", "age": "", "prefixes": ["ROE"]},
                ]
            ),
        )
        self.db.save_binghuo_actor_profile("Actor Canglangge Missing", ENRICHED_STATUS, birthday="", age="24", height="166", bust="82", waist="", hip="85")

        candidates = service._candidate_actors()

        self.assertEqual(
            [row["actor_name"] for row in candidates],
            ["Actor Canglangge Missing", "Actor Library Missing", "Actor Missing Cup"],
        )

    def test_success_persists_baomu_profile_fields(self):
        actor_name = "一松愛梨"
        self._insert_actor(actor_name, birthday="", age="")
        self.db.save_binghuo_actor_profile(actor_name, ENRICHED_STATUS, birthday="1984-05-20", age="42", height="", bust="", waist="", hip="")
        scraper = FakeBaomuScraper(
            profiles={
                actor_name: {
                    "birthday": "1984-05-20",
                    "height": "171",
                    "bust": "101",
                    "cup": "G",
                    "measurements_raw": "breast=101cm; waist=63cm; hip=93cm; cup=G",
                    "waist": "63",
                    "hip": "93",
                }
            }
        )
        service = ActorBaomuEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result["success_count"], 1)
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record["baomu_enrichment_status"], ENRICHED_STATUS)
        self.assertEqual(record["baomu_birthday"], "1984-05-20")
        self.assertEqual(record["baomu_height"], "171")
        self.assertEqual(record["baomu_bust"], "101")
        self.assertEqual(record["baomu_cup"], "G")
        self.assertEqual(record["baomu_measurements_raw"], "breast=101cm; waist=63cm; hip=93cm; cup=G")
        self.assertEqual(record["baomu_waist"], "63")
        self.assertEqual(record["baomu_hip"], "93")

    def test_partial_baomu_success_is_skipped_on_later_batches(self):
        actor_name = "Actor Partial Baomu"
        self._insert_actor(actor_name, birthday="", age="")
        self.db.save_binghuo_actor_profile(actor_name, ENRICHED_STATUS, birthday="", age="31", height="", bust="", waist="", hip="")
        scraper = FakeBaomuScraper(
            profiles={
                actor_name: {
                    "height": "160",
                }
            }
        )
        service = ActorBaomuEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        first = service.enrich_next_actors(1)
        second = service.enrich_next_actors(1)

        self.assertEqual(first["results"][0]["status"], ENRICHED_STATUS)
        self.assertEqual(first["results"][0]["height"], "160")
        self.assertEqual(second["processed_count"], 0)
        self.assertEqual(scraper.open_calls, [actor_name])
        self.assertNotIn(actor_name, [row["actor_name"] for row in service._candidate_actors()])

    def test_no_profile_result_is_terminal_for_baomu(self):
        actor_name = "Actor No Baomu"
        self._insert_actor(actor_name, birthday="", age="")
        self.db.save_binghuo_actor_profile(actor_name, ENRICHED_STATUS, birthday="", age="29", height="", bust="", waist="", hip="")
        service = ActorBaomuEnrichmentService(
            self.db,
            scraper=FakeBaomuScraper(missing_names={actor_name}),
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        first = service.enrich_next_actors(1)
        second = service.enrich_next_actors(1)

        self.assertEqual(first["results"][0]["status"], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(second["processed_count"], 0)

    def test_failures_are_skipped_until_manual_reset_for_baomu(self):
        actor_name = "Actor Broken Baomu"
        self._insert_actor(actor_name, birthday="", age="")
        self.db.save_binghuo_actor_profile(actor_name, ENRICHED_STATUS, birthday="", age="29", height="", bust="", waist="", hip="")
        service = ActorBaomuEnrichmentService(
            self.db,
            scraper=FakeBaomuScraper(errors={actor_name: "boom"}),
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        first = service.enrich_next_actors(1)
        second = service.enrich_next_actors(1)
        record = self.db.get_actor_enrichment_record(actor_name)

        self.assertEqual(first["results"][0]["status"], FAILED_STATUS)
        self.assertEqual(record["baomu_enrichment_status"], FAILED_STATUS)
        self.assertEqual(second["processed_count"], 0)
        self.assertNotIn(actor_name, [row["actor_name"] for row in service._candidate_actors()])


if __name__ == "__main__":
    unittest.main()
