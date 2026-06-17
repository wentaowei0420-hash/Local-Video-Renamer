import unittest

from app.core.backend_protocol import BACKEND_API_REVISION
from app.core.project_paths import PROJECT_ROOT
from app.gui.main_window import VidNormApp


class BackendReuseDecisionTest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
