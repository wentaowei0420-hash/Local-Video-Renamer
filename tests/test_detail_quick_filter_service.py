import unittest

from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.services.detail_quick_filter_service import (
    DETAIL_FILTER_ACTIVE,
    DETAIL_FILTER_AVFAN_FAILED,
    DETAIL_FILTER_JAVTXT_PENDING,
    DETAIL_FILTER_ENRICHED,
    DETAIL_FILTER_FAILED,
    DETAIL_FILTER_INACTIVE,
    DETAIL_FILTER_MISSING_AGE,
    DETAIL_FILTER_MISSING_BIRTHDAY,
    DETAIL_FILTER_PENDING,
    DETAIL_FILTER_SUSPECT,
    DETAIL_FILTER_TIER_A,
    DETAIL_FILTER_TIER_S,
    filter_library_rows,
)


class DetailQuickFilterServiceTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                'name': 'Pending Actor',
                'avfan_enrichment_status': UNENRICHED_STATUS,
                'javtxt_enrichment_status': ENRICHED_STATUS,
                'update_status': 'active',
                'ladder_tier': 'S',
                'birthday': '',
                'raw_age': '',
            },
            {
                'name': 'Failed Actor',
                'avfan_enrichment_status': FAILED_STATUS,
                'javtxt_enrichment_status': ENRICHED_STATUS,
                'update_status': 'suspect',
                'ladder_tier': 'A',
                'birthday': '1995-07-18',
                'raw_age': '29',
            },
            {
                'name': 'Done Actor',
                'avfan_enrichment_status': ENRICHED_STATUS,
                'javtxt_enrichment_status': UNENRICHED_STATUS,
                'update_status': 'inactive',
                'ladder_tier': 'B',
                'birthday': '1992-08-09',
                'raw_age': '',
            },
            {
                'name': 'Full Actor',
                'avfan_enrichment_status': ENRICHED_STATUS,
                'javtxt_enrichment_status': ENRICHED_STATUS,
                'update_status': 'inactive',
                'ladder_tier': 'C',
                'birthday': '1990-01-01',
                'raw_age': '35',
            }
        ]

    def test_pending_filter_matches_any_unenriched_source(self):
        rows = filter_library_rows(self.rows, DETAIL_FILTER_PENDING)

        self.assertEqual([row['name'] for row in rows], ['Pending Actor', 'Done Actor'])

    def test_failed_filter_matches_any_failed_source(self):
        rows = filter_library_rows(self.rows, DETAIL_FILTER_FAILED)

        self.assertEqual([row['name'] for row in rows], ['Failed Actor'])

    def test_enriched_filter_requires_both_sources_completed(self):
        rows = filter_library_rows(self.rows, DETAIL_FILTER_ENRICHED)

        self.assertEqual([row['name'] for row in rows], ['Full Actor'])

    def test_update_status_filters_match_current_status(self):
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_ACTIVE)],
            ['Pending Actor'],
        )
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_SUSPECT)],
            ['Failed Actor'],
        )
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_INACTIVE)],
            ['Done Actor', 'Full Actor'],
        )

    def test_source_specific_filters_match_individual_source_status(self):
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_AVFAN_FAILED)],
            ['Failed Actor'],
        )
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_JAVTXT_PENDING)],
            ['Done Actor'],
        )

    def test_tier_filters_match_ladder_tier(self):
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_TIER_S)],
            ['Pending Actor'],
        )
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_TIER_A)],
            ['Failed Actor'],
        )

    def test_actor_profile_completeness_filters_match_missing_fields(self):
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_MISSING_BIRTHDAY)],
            ['Pending Actor'],
        )
        self.assertEqual(
            [row['name'] for row in filter_library_rows(self.rows, DETAIL_FILTER_MISSING_AGE)],
            ['Pending Actor', 'Done Actor'],
        )


if __name__ == '__main__':
    unittest.main()
