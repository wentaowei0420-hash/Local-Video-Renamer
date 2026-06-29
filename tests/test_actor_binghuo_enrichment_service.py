import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS
from app.data.database_handler import VideoDatabase
from app.services.enrichment.actor_binghuo_enrichment import ActorBinghuoEnrichmentService


class FakeBinghuoScraper:
    def __init__(self, search_results=None, profiles=None):
        self.search_results = dict(search_results or {})
        self.profiles = dict(profiles or {})
        self.opened_targets = []
        self.search_calls = []
        self._current_profile = {}

    @contextmanager
    def session(self):
        yield object()

    def open_search_page(self, _page, actor_name):
        self.search_calls.append(actor_name)
        self._current_actor_name = actor_name
        return actor_name

    def collect_search_results(self, _page):
        return [dict(row) for row in self.search_results.get(self._current_actor_name, [])]

    def open_person_page(self, _page, person_id="", url=""):
        target = str(url or person_id or "").strip()
        self.opened_targets.append(target)
        key = person_id or self.extract_person_id(url)
        self._current_profile = dict(self.profiles.get(str(key), {}))
        return url or f"https://www.fouroursonsinc.com/person/{key}"

    def parse_profile(self, _page):
        return dict(self._current_profile)

    @staticmethod
    def extract_person_id(url):
        return str(url or "").rstrip("/").split("/")[-1]


class FakeCanglanggeCandidateService:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_candidates(self):
        return [dict(row) for row in self.rows]


class FakeLogger:
    def __init__(self):
        self.records = []

    def log(self, level, message, **fields):
        self.records.append(
            {
                "level": level,
                "message": message,
                "fields": dict(fields),
            }
        )


class ActorBinghuoEnrichmentServiceTest(unittest.TestCase):
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

    def test_prioritizes_canglangge_then_missing_birthday_then_missing_binghuo_id(self):
        self._insert_actor("Actor B", birthday="", age="")
        self._insert_actor("Actor C", birthday="1999-01-01", age="27")
        self._insert_actor("Actor D", birthday="", age="")
        self.db.save_binghuo_actor_profile("Actor D", NO_SEARCH_RESULTS_STATUS, error="No Results")

        scraper = FakeBinghuoScraper(
            search_results={
                "Actor A": [{"title": "Actor A,Alias [100%]", "href": "https://www.fouroursonsinc.com/person/1"}],
                "Actor B": [{"title": "Actor B", "href": "https://www.fouroursonsinc.com/person/2"}],
                "Actor C": [{"title": "Actor C", "href": "https://www.fouroursonsinc.com/person/3"}],
                "Actor X": [{"title": "Actor X", "href": "https://www.fouroursonsinc.com/person/4"}],
            },
            profiles={
                "1": {"person_id": "1", "birthday": "2001-02-03", "age": "25"},
                "2": {"person_id": "2", "birthday": "2002-03-04", "age": "24"},
                "3": {"person_id": "3", "birthday": "1999-01-01", "age": "27", "height": "168"},
                "4": {
                    "person_id": "4",
                    "birthday": "2000-01-01",
                    "age": "26",
                    "height": "166",
                    "bust": "85",
                    "waist": "59",
                    "hip": "87",
                },
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService(
                [
                    {"actor_name": "Actor A", "birthday": "", "age": "", "prefixes": ["ROE"]},
                    {"actor_name": "Actor X", "birthday": "2000-01-01", "age": "26", "prefixes": ["ROE"]},
                ]
            ),
        )

        result = service.enrich_next_actors(5)

        self.assertEqual(
            [row["actor_name"] for row in result["results"]],
            ["Actor A", "Actor X", "Actor B", "Actor C"],
        )

    def test_multiple_exact_matches_use_first_exact_result(self):
        self._insert_actor("Actor Multi Match", birthday="", age="")
        scraper = FakeBinghuoScraper(
            search_results={
                "Actor Multi Match": [
                    {
                        "title": "Actor Multi Match,Kosaka Nanaka [100%]",
                        "href": "https://www.fouroursonsinc.com/person/5921",
                    },
                    {
                        "title": "Actor Multi Match,Other Alias [100%]",
                        "href": "https://www.fouroursonsinc.com/person/7000",
                    },
                ]
            },
            profiles={
                "5921": {"person_id": "5921", "birthday": "2003-09-04", "age": "22", "height": "172"},
                "7000": {"person_id": "7000", "birthday": "1990-01-01", "age": "36", "height": "160"},
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        service.enrich_next_actors(1)

        record = self.db.get_actor_enrichment_record("Actor Multi Match")
        self.assertEqual(record["binghuo_person_id"], "5921")
        self.assertEqual(record["binghuo_birthday"], "2003-09-04")

    def test_numbered_exact_match_result_is_accepted(self):
        self._insert_actor("Actor Numbered Match", birthday="", age="")
        scraper = FakeBinghuoScraper(
            search_results={
                "Actor Numbered Match": [
                    {
                        "title": "1. Actor Numbered Match,Yamaguchi Juri [100%]",
                        "href": "https://www.fouroursonsinc.com/person/916",
                    },
                ]
            },
            profiles={
                "916": {
                    "person_id": "916",
                    "birthday": "1967-07-02",
                    "age": "58",
                    "height": "164",
                    "bust": "90",
                    "cup": "F",
                    "measurements_raw": "B90(F) W64 H90",
                    "waist": "64",
                    "hip": "90",
                },
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)
        record = self.db.get_actor_enrichment_record("Actor Numbered Match")

        self.assertEqual(result["success_count"], 1)
        self.assertEqual(record["binghuo_person_id"], "916")
        self.assertEqual(record["binghuo_birthday"], "1967-07-02")
        self.assertEqual(record["binghuo_height"], "164")
        self.assertEqual(record["binghuo_bust"], "90")
        self.assertEqual(record["binghuo_cup"], "F")
        self.assertEqual(record["binghuo_measurements_raw"], "B90(F) W64 H90")
        self.assertEqual(record["binghuo_waist"], "64")
        self.assertEqual(record["binghuo_hip"], "90")

    def test_no_search_result_is_saved_and_skipped_on_next_run(self):
        self._insert_actor("Actor No Search", birthday="", age="")
        scraper = FakeBinghuoScraper(search_results={"Actor No Search": []})
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        first = service.enrich_next_actors(1)
        second = service.enrich_next_actors(1)

        self.assertEqual(first["results"][0]["status"], NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(second["processed_count"], 0)
        self.assertEqual(
            self.db.get_actor_enrichment_record("Actor No Search")["binghuo_enrichment_status"],
            NO_SEARCH_RESULTS_STATUS,
        )

    def test_existing_binghuo_id_opens_profile_directly_without_search(self):
        self._insert_actor("Actor Existing Id", birthday="", age="")
        self.db.save_binghuo_actor_profile("Actor Existing Id", "失败", person_id="8888", error="Old Error")
        scraper = FakeBinghuoScraper(
            profiles={"8888": {"person_id": "8888", "birthday": "2001-01-01", "age": "25"}},
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        service.enrich_next_actors(1)

        self.assertEqual(scraper.search_calls, [])
        self.assertEqual(scraper.opened_targets, ["8888"])
        self.assertEqual(
            self.db.get_actor_enrichment_record("Actor Existing Id")["binghuo_birthday"],
            "2001-01-01",
        )

    def test_local_birthday_with_empty_binghuo_profile_is_reset_and_retried(self):
        actor_name = "Actor Existing Profile Only"
        self._insert_actor(actor_name, birthday="1998-01-01", age="28")
        self.db.save_binghuo_actor_profile(
            actor_name,
            ENRICHED_STATUS,
            person_id="1955",
            birthday="",
            age="",
            height="",
            bust="",
            waist="",
            hip="",
        )
        scraper = FakeBinghuoScraper(
            profiles={
                "1955": {
                    "person_id": "1955",
                    "birthday": "1998-01-01",
                    "age": "28",
                    "height": "168",
                    "bust": "86",
                    "waist": "58",
                    "hip": "88",
                }
            }
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(scraper.search_calls, [])
        self.assertEqual(scraper.opened_targets, ["1955"])
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record["binghuo_enrichment_status"], ENRICHED_STATUS)
        self.assertEqual(record["binghuo_birthday"], "1998-01-01")
        self.assertEqual(record["binghuo_height"], "168")

    def test_canglangge_candidate_with_saved_birthday_is_retried_for_missing_measurements(self):
        actor_name = "Actor Candidate Profile"
        self.db.save_binghuo_actor_profile(
            actor_name,
            ENRICHED_STATUS,
            person_id="6001",
            birthday="2000-01-02",
            age="26",
            height="",
            bust="",
            waist="",
            hip="",
        )
        scraper = FakeBinghuoScraper(
            profiles={
                "6001": {
                    "person_id": "6001",
                    "birthday": "2000-01-02",
                    "age": "26",
                    "height": "169",
                    "bust": "88",
                    "waist": "60",
                    "hip": "89",
                }
            }
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService(
                [
                    {"actor_name": actor_name, "birthday": "2000-01-02", "age": "26", "prefixes": ["ROE"]},
                ]
            ),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(scraper.search_calls, [])
        self.assertEqual(scraper.opened_targets, ["6001"])
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record["binghuo_enrichment_status"], ENRICHED_STATUS)
        self.assertEqual(record["binghuo_height"], "169")
        self.assertEqual(record["binghuo_bust"], "88")
        self.assertEqual(record["binghuo_waist"], "60")
        self.assertEqual(record["binghuo_hip"], "89")

    def test_missing_birthday_is_marked_no_detail_and_not_retryable(self):
        actor_name = "Actor Missing Birthday"
        self._insert_actor(actor_name, birthday="", age="")
        scraper = FakeBinghuoScraper(
            search_results={
                actor_name: [
                    {
                        "title": actor_name,
                        "href": "https://www.fouroursonsinc.com/person/36413",
                    }
                ]
            },
            profiles={
                "36413": {
                    "person_id": "36413",
                    "birthday": "",
                    "age": "30",
                    "height": "175",
                    "bust": "108",
                    "waist": "62",
                    "hip": "91",
                }
            },
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result["results"][0]["status"], NO_VIDEO_DETAIL_STATUS)
        self.assertEqual(result["success_count"], 0)
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record["binghuo_person_id"], "36413")
        self.assertEqual(record["binghuo_enrichment_status"], NO_VIDEO_DETAIL_STATUS)
        self.assertEqual(record["binghuo_birthday"], "")
        self.assertEqual(record["binghuo_height"], "175")
        actor_row = self.db.list_actors(actor_name)[0]
        self.assertEqual(actor_row["birthday"], "")
        self.assertEqual(actor_row["raw_age"], "30")
        self.assertNotIn(actor_name, [row["actor_name"] for row in service._candidate_actors()])

    def test_logs_actor_level_result_fields_for_partial_binghuo_profile(self):
        actor_name = "Actor Logged"
        self._insert_actor(actor_name, birthday="", age="")
        scraper = FakeBinghuoScraper(
            search_results={
                actor_name: [
                    {
                        "title": actor_name,
                        "href": "https://www.fouroursonsinc.com/person/5001",
                    }
                ]
            },
            profiles={
                "5001": {
                    "person_id": "5001",
                    "birthday": "",
                    "age": "29",
                    "height": "168",
                }
            },
        )
        logger = FakeLogger()
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
            logger=logger,
        )

        service.enrich_next_actors(1)

        actor_result_logs = [entry for entry in logger.records if entry["fields"].get("actor_name") == actor_name]
        self.assertTrue(actor_result_logs)
        self.assertEqual(actor_result_logs[-1]["fields"]["person_id"], "5001")
        self.assertFalse(actor_result_logs[-1]["fields"]["birthday_found"])
        self.assertEqual(actor_result_logs[-1]["fields"]["status_written"], NO_VIDEO_DETAIL_STATUS)

    def test_existing_partial_binghuo_profile_is_not_retried(self):
        actor_name = "Actor Partial Stored"
        self._insert_actor(actor_name, birthday="", age="30")
        self.db.save_binghuo_actor_profile(
            actor_name,
            NO_VIDEO_DETAIL_STATUS,
            person_id="36413",
            birthday="",
            age="30",
            height="175",
            bust="108",
            waist="62",
            hip="91",
        )
        scraper = FakeBinghuoScraper(
            profiles={
                "36413": {
                    "person_id": "36413",
                    "birthday": "1996-06-09",
                    "age": "30",
                    "height": "175",
                    "bust": "108",
                    "waist": "62",
                    "hip": "91",
                }
            }
        )
        service = ActorBinghuoEnrichmentService(
            self.db,
            scraper=scraper,
            candidate_service=FakeCanglanggeCandidateService([]),
        )

        result = service.enrich_next_actors(1)

        self.assertEqual(result["processed_count"], 0)
        actor_row = self.db.list_actors(actor_name)[0]
        self.assertEqual(actor_row["birthday"], "")
        record = self.db.get_actor_enrichment_record(actor_name)
        self.assertEqual(record["binghuo_birthday"], "")


if __name__ == "__main__":
    unittest.main()
