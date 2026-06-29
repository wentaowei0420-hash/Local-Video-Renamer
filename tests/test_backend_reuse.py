import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch
import subprocess

from app.backend.service import BackendService
from app.core.backend_protocol import BACKEND_API_REVISION, BACKEND_PROCESS_CODE_FINGERPRINT
from app.core.enrichment_status import ENRICHED_STATUS
from app.core.project_paths import PROJECT_ROOT
from app.gui.i18n import tr
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
        self.assertIn('birthday-display', BACKEND_API_REVISION)
        self.assertIn('data-center-analysis-cache', BACKEND_API_REVISION)
        self.assertIn('binghuo-no-detail', BACKEND_API_REVISION)
        self.assertIn('manual-snapshot', BACKEND_API_REVISION)
        self.assertIn('paged-query', BACKEND_API_REVISION)

    def test_backend_revision_marks_data_center_issue_list_payload_change(self):
        self.assertIn('issue-list', BACKEND_API_REVISION)

    def test_backend_revision_marks_batch_auto_stop_change(self):
        self.assertIn('batch-auto-stop', BACKEND_API_REVISION)

    def test_backend_revision_marks_code_prefix_analysis_change(self):
        self.assertIn('code-prefix-analysis', BACKEND_API_REVISION)

    def test_backend_revision_marks_actor_detail_refresh_guard_change(self):
        self.assertIn('actor-detail-refresh-guard', BACKEND_API_REVISION)

    def test_reuses_same_project_compatible_backend(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'existing-token',
        }

        self.assertTrue(VidNormApp.is_reusable_backend_instance(health))

    def test_does_not_reuse_different_project_backend(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT.parent),
            'backend_instance_token': 'existing-token',
        }

        self.assertFalse(VidNormApp.is_reusable_backend_instance(health))

    def test_does_not_reuse_incompatible_backend(self):
        health = {
            'backend_revision': 'old-revision',
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'existing-token',
        }

        self.assertFalse(VidNormApp.is_reusable_backend_instance(health))

    def test_does_not_reuse_backend_when_code_fingerprint_differs(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': 'stale-fingerprint',
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

    def test_stop_owned_backend_force_kills_process_when_terminate_does_not_exit(self):
        calls = []

        class HangingProcess:
            pid = 6789

            def __init__(self):
                self.wait_calls = 0

            def poll(self):
                return None

            def terminate(self):
                calls.append('terminate')

            def wait(self, timeout=None):
                self.wait_calls += 1
                raise subprocess.TimeoutExpired(cmd='backend', timeout=timeout)

        process = HangingProcess()
        stub = SimpleNamespace(
            owns_backend_process=True,
            backend_process=process,
            _terminate_backend_pid=lambda pid: calls.append(('force_kill', pid)) or True,
            _wait_for_backend_release=lambda timeout_seconds=3.0: calls.append(('wait_release', timeout_seconds)) or True,
            get_backend_health=lambda: None,
            is_expected_backend_instance=lambda health: False,
            stop_backend_on_port=lambda health=None: calls.append(('stop_backend_on_port', health)),
        )
        stub._is_backend_process_alive = VidNormApp._is_backend_process_alive
        stub._terminate_backend_process_handle = (
            lambda process, timeout_seconds=3: VidNormApp._terminate_backend_process_handle(
                stub, process, timeout_seconds=timeout_seconds
            )
        )

        VidNormApp.stop_owned_backend(stub)

        self.assertIn('terminate', calls)
        self.assertIn(('force_kill', 6789), calls)
        self.assertIn(('wait_release', 3), calls)
        self.assertIsNone(stub.backend_process)
        self.assertFalse(stub.owns_backend_process)

    def test_ensure_backend_running_cleans_previous_reusable_backend_before_restart(self):
        stale_health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'stale-token',
            'backend_process_id': 2222,
        }
        expected_health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'fresh-token',
            'backend_process_id': 3333,
        }
        health_sequence = iter([stale_health, None, expected_health])
        stop_calls = []

        class FakeProcess:
            pid = 3333

            @staticmethod
            def poll():
                return None

        stub = SimpleNamespace(
            backend_instance_token='',
            backend_process=None,
            owns_backend_process=False,
            get_backend_health=lambda: next(health_sequence, expected_health),
            stop_backend_on_port=lambda health=None: stop_calls.append(health),
            _get_backend_python_executable=lambda: 'python',
        )
        stub.is_reusable_backend_instance = VidNormApp.is_reusable_backend_instance
        stub._is_matching_backend_code = VidNormApp._is_matching_backend_code
        stub.is_backend_compatible = lambda health: VidNormApp.is_backend_compatible(stub, health)
        stub.is_expected_backend_instance = lambda health: VidNormApp.is_expected_backend_instance(stub, health)
        stub._adopt_reusable_backend = lambda health: VidNormApp._adopt_reusable_backend(stub, health)

        with patch('app.gui.main_window.uuid.uuid4', return_value=SimpleNamespace(hex='fresh-token')), patch(
            'app.gui.main_window.subprocess.Popen', return_value=FakeProcess()
        ), patch('app.gui.main_window.time.time', side_effect=[0, 0, 1]), patch(
            'app.gui.main_window.time.sleep', return_value=None
        ):
            VidNormApp.ensure_backend_running(stub)

        self.assertEqual(stop_calls, [stale_health])
        self.assertEqual(stub.backend_instance_token, 'fresh-token')
        self.assertTrue(stub.owns_backend_process)

    def test_backend_start_failure_prefers_database_locked_message(self):
        stub = SimpleNamespace(
            _is_database_locked=lambda: True,
            _is_backend_process_alive=lambda process: False,
            backend_process=None,
        )

        message = VidNormApp._build_backend_start_failure_message(stub, stale_backend_cleaned=False)

        self.assertEqual(message, tr('main.backend_db_locked'))

    def test_backend_start_failure_mentions_stale_backend_after_cleanup_attempt(self):
        stub = SimpleNamespace(
            _is_database_locked=lambda: False,
            _is_backend_process_alive=lambda process: False,
            backend_process=None,
        )

        message = VidNormApp._build_backend_start_failure_message(stub, stale_backend_cleaned=True)

        self.assertEqual(message, tr('main.backend_start_timeout_after_cleanup'))

    def test_backend_start_failure_prefers_initializing_message_when_spawned_backend_still_alive(self):
        stub = SimpleNamespace(
            _is_database_locked=lambda: True,
            _is_backend_process_alive=lambda process: True,
            backend_process=object(),
        )

        message = VidNormApp._build_backend_start_failure_message(stub, stale_backend_cleaned=False)

        self.assertEqual(message, tr('main.backend_start_initializing_too_long'))

    def test_ensure_backend_running_cleans_spawned_backend_before_raising_timeout(self):
        stop_calls = []

        class FakeProcess:
            pid = 5555

            @staticmethod
            def poll():
                return None

        stub = SimpleNamespace(
            backend_instance_token='',
            backend_process=None,
            owns_backend_process=False,
            get_backend_health=lambda: None,
            stop_backend_on_port=lambda health=None: None,
            _get_backend_python_executable=lambda: 'python',
            _build_backend_start_failure_message=lambda stale_backend_cleaned=False: 'timeout-message',
            stop_owned_backend=lambda: stop_calls.append('stop_owned_backend'),
        )
        stub.is_reusable_backend_instance = VidNormApp.is_reusable_backend_instance
        stub._is_matching_backend_code = VidNormApp._is_matching_backend_code
        stub.is_backend_compatible = lambda health: VidNormApp.is_backend_compatible(stub, health)
        stub.is_expected_backend_instance = lambda health: VidNormApp.is_expected_backend_instance(stub, health)
        stub._adopt_reusable_backend = lambda health: VidNormApp._adopt_reusable_backend(stub, health)

        with patch('app.gui.main_window.uuid.uuid4', return_value=SimpleNamespace(hex='fresh-token')), patch(
            'app.gui.main_window.subprocess.Popen', return_value=FakeProcess()
        ), patch('app.gui.main_window.time.time', side_effect=[0, 31, 31]), patch(
            'app.gui.main_window.time.sleep', return_value=None
        ):
            with self.assertRaisesRegex(RuntimeError, 'timeout-message'):
                VidNormApp.ensure_backend_running(stub)

        self.assertEqual(stop_calls, ['stop_owned_backend'])

    def test_get_initial_backend_instance_token_reads_environment(self):
        with patch.dict(os.environ, {'VIDNORM_BACKEND_INSTANCE_TOKEN': ' launcher-token '}, clear=False):
            self.assertEqual(VidNormApp._get_initial_backend_instance_token(), 'launcher-token')

    def test_should_own_prelaunched_backend_reads_environment(self):
        with patch.dict(os.environ, {'VIDNORM_BACKEND_OWNED': 'true'}, clear=False):
            self.assertTrue(VidNormApp._should_own_prelaunched_backend())
        with patch.dict(os.environ, {'VIDNORM_BACKEND_OWNED': '0'}, clear=False):
            self.assertFalse(VidNormApp._should_own_prelaunched_backend())

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

    def test_batch_plan_stops_when_remaining_count_reaches_zero(self):
        calls = []
        stub = SimpleNamespace(
            enrichment_mode='batch',
            batch_enrichment_active=True,
            status_label=SimpleNamespace(setText=lambda value: calls.append(('status', value))),
            build_enrichment_summary=lambda result: 'summary',
            stop_batch_enrichment=lambda message=None: calls.append(('stop_batch', message)),
            schedule_next_batch_enrichment=lambda last_result=None: calls.append(('schedule', last_result)),
        )

        with patch('app.gui.main_window.QMessageBox.information') as info_mock:
            VidNormApp.on_enrichment_finished(
                stub,
                {
                    'entity_label': '视频库',
                    'remaining_count': 0,
                    'stopped': False,
                    'requires_manual_verification': False,
                    'message': '',
                },
            )

        self.assertIn(('stop_batch', tr('main.batch_completed')), calls)
        self.assertNotIn(('schedule', unittest.mock.ANY), calls)
        self.assertTrue(info_mock.called)

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
