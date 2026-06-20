import unittest
from types import SimpleNamespace

from app.backend.service import BackendService
from app.core.backend_protocol import BACKEND_API_REVISION
from app.core.enrichment_status import ENRICHED_STATUS
from app.core.project_paths import PROJECT_ROOT
from app.gui.main_window import VidNormApp
from app.services.video import VIDEO_CATEGORY_SINGLE


class BackendReuseDecisionTest(unittest.TestCase):
    def test_backend_revision_marks_binghuo_status_and_backend_guard_change(self):
        self.assertIn('binghuo', BACKEND_API_REVISION)
        self.assertIn('backend-guard', BACKEND_API_REVISION)
        self.assertIn('actor-update-status', BACKEND_API_REVISION)

    def test_backend_revision_marks_actor_library_status_payload_change(self):
        self.assertIn('actor-library-status', BACKEND_API_REVISION)

    def test_backend_revision_marks_actor_detail_payload_change(self):
        self.assertIn('actor-detail', BACKEND_API_REVISION)

    def test_reuses_same_project_compatible_backend(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'existing-token',
        }

        self.assertTrue(VidNormApp.is_reusable_backend_instance(health))

    def test_does_not_reuse_different_project_backend(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'project_root': str(PROJECT_ROOT.parent),
            'backend_instance_token': 'existing-token',
        }

        self.assertFalse(VidNormApp.is_reusable_backend_instance(health))

    def test_does_not_reuse_incompatible_backend(self):
        health = {
            'backend_revision': 'old-revision',
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'existing-token',
        }

        self.assertFalse(VidNormApp.is_reusable_backend_instance(health))

    def test_extract_backend_pid_reads_numeric_health_pid(self):
        self.assertEqual(
            VidNormApp._extract_backend_pid({'backend_process_id': 4321}),
            '4321',
        )

    def test_extract_backend_pid_rejects_invalid_pid(self):
        self.assertEqual(VidNormApp._extract_backend_pid({'backend_process_id': 'abc'}), '')

    def test_network_guard_revalidates_backend_instance_before_probe(self):
        calls = []
        stub = SimpleNamespace(
            ensure_backend_running=lambda: calls.append('ensure'),
            network_guard_service=SimpleNamespace(
                probe=lambda: {'is_online': True, 'reachable_target': 'https://example.com'},
            ),
            network_guard_failure_count=2,
            network_stop_requested=True,
            network_last_probe_online=None,
            update_network_status_label=lambda probe_result=None: calls.append(('update', probe_result)),
            _has_active_enrichment_plan=lambda: False,
            handle_network_disconnect=lambda probe_result=None: calls.append(('disconnect', probe_result)),
        )

        VidNormApp.check_network_guard(stub)

        self.assertEqual(calls[0], 'ensure')
        self.assertEqual(stub.network_guard_failure_count, 0)
        self.assertFalse(stub.network_stop_requested)
        self.assertTrue(stub.network_last_probe_online)

    def test_attach_actor_update_status_loads_filter_settings_once(self):
        class FakeDatabase:
            @staticmethod
            def list_local_videos_by_actor_names(actor_names):
                return [
                    {
                        'author': 'Alpha',
                        'release_date': '2026-01-01',
                        'video_category': VIDEO_CATEGORY_SINGLE,
                    }
                ]

            @staticmethod
            def list_actor_movies_by_names(actor_names):
                return {
                    'Alpha': [
                        {
                            'code': 'ROE-001',
                            'release_date': '2026-01-02',
                            'javtxt_release_date': '2026-01-02',
                            'javtxt_enrichment_status': ENRICHED_STATUS,
                            'video_category': VIDEO_CATEGORY_SINGLE,
                        }
                    ],
                    'Beta': [],
                }

        class CountingFilterService:
            def __init__(self):
                self.load_calls = 0
                self.settings_refs = []

            def load_settings(self):
                self.load_calls += 1
                return {'loaded': self.load_calls}

            def filter_video_rows(self, rows, settings=None):
                if settings is None:
                    settings = self.load_settings()
                self.settings_refs.append(settings)
                return list(rows)

        rows = [{'name': 'Alpha'}, {'name': 'Beta'}]
        filter_service = CountingFilterService()
        stub = SimpleNamespace(db=FakeDatabase(), video_filter_service=filter_service)

        BackendService._attach_actor_update_status(stub, rows)

        self.assertEqual(filter_service.load_calls, 1)
        self.assertEqual(len(filter_service.settings_refs), 2)
        self.assertTrue(all(settings == {'loaded': 1} for settings in filter_service.settings_refs))


if __name__ == '__main__':
    unittest.main()
