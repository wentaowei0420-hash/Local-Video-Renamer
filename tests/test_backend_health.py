import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.backend.service import BackendService
from app.core.backend_protocol import BACKEND_PROCESS_CODE_FINGERPRINT


class BackendHealthTest(unittest.TestCase):
    def test_health_reports_instance_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('app.backend.service.VideoDatabase'), patch('app.backend.service.VideoLadderTagService'), patch(
                'app.backend.service.LocalVideoLibraryService'
            ), patch('app.backend.service.ActorDetailLibrary'), patch(
                'app.backend.service.ActorLibrarySyncService'
            ), patch(
                'app.backend.service.CodePrefixDetailLibrary'
            ), patch(
                'app.backend.service.CodePrefixLibrary'
            ), patch(
                'app.backend.service.CodePrefixVideoCategoryBulkService'
            ), patch(
                'app.backend.service.CanglanggeCandidateService'
            ), patch(
                'app.backend.service.DataCenterService'
            ), patch(
                'app.backend.service.LibraryAdminService'
            ), patch(
                'app.backend.service.LibraryStatusSyncService'
            ), patch(
                'app.backend.service.LadderBoardService'
            ), patch(
                'app.backend.service.PathLibrary'
            ), patch(
                'app.backend.service.EnrichmentProgressService'
            ), patch(
                'app.backend.service.ComboProgressService'
            ), patch(
                'app.backend.service.EnrichmentTaskState'
            ) as task_state_mock:
                task_state_mock.return_value.is_running = False
                task_state_mock.return_value.active_kind = ''
                service = BackendService(base_dir=Path(temp_dir), instance_token="token-123")
                health = service.health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["backend_instance_token"], "token-123")
        self.assertEqual(health["project_root"], str(Path(temp_dir)))
        self.assertEqual(health["backend_code_fingerprint"], BACKEND_PROCESS_CODE_FINGERPRINT)
        self.assertIsInstance(health["backend_process_id"], int)
        self.assertGreater(health["backend_process_id"], 0)

    def test_load_database_runs_startup_maintenance_before_sync(self):
        db_mock = Mock()
        db_mock.db_path = Path('video_database.db')
        db_mock.get_video_count.return_value = 1
        db_mock.get_actor_count.return_value = 2
        sync_service_mock = Mock()

        with patch('app.backend.service.VideoDatabase', return_value=db_mock), patch(
            'app.backend.service.VideoLadderTagService'
        ), patch('app.backend.service.LocalVideoLibraryService'), patch(
            'app.backend.service.ActorDetailLibrary'
        ), patch(
            'app.backend.service.ActorLibrarySyncService', return_value=sync_service_mock
        ), patch(
            'app.backend.service.CodePrefixDetailLibrary'
        ), patch(
            'app.backend.service.CodePrefixLibrary'
        ), patch(
            'app.backend.service.CodePrefixVideoCategoryBulkService'
        ), patch(
            'app.backend.service.CanglanggeCandidateService'
        ), patch(
            'app.backend.service.DataCenterService'
        ), patch(
            'app.backend.service.LibraryAdminService'
        ), patch(
            'app.backend.service.LibraryStatusSyncService'
        ), patch(
            'app.backend.service.LadderBoardService'
        ), patch(
            'app.backend.service.PathLibrary'
        ), patch(
            'app.backend.service.EnrichmentProgressService'
        ), patch(
            'app.backend.service.ComboProgressService'
        ), patch(
            'app.backend.service.EnrichmentTaskState'
        ) as task_state_mock:
            task_state_mock.return_value.is_running = False
            task_state_mock.return_value.active_kind = ''
            service = BackendService(base_dir=Path.cwd(), instance_token='token-123')

        payload = service.load_database()

        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['actor_count'], 2)
        db_mock.ensure_startup_maintenance.assert_called_once_with()
        sync_service_mock.sync_from_video_library.assert_called_once_with()
        db_mock.sanitize_ineligible_javtxt_state.assert_called_once_with()
        self.assertTrue(service.database_loaded)


if __name__ == "__main__":
    unittest.main()
