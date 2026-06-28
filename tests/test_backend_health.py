import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
