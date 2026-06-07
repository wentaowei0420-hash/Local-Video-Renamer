import tempfile
import unittest
from pathlib import Path

from app.backend.service import BackendService


class BackendHealthTest(unittest.TestCase):
    def test_health_reports_instance_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BackendService(base_dir=Path(temp_dir), instance_token="token-123")
            health = service.health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["backend_instance_token"], "token-123")
        self.assertEqual(health["project_root"], str(Path(temp_dir)))
        self.assertIsInstance(health["backend_process_id"], int)
        self.assertGreater(health["backend_process_id"], 0)


if __name__ == "__main__":
    unittest.main()
