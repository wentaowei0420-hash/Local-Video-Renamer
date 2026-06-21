import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.path_library_viewer import PathLibraryWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class PathLibraryBackendStub:
    def __init__(self):
        self.refresh_flags = []

    def get_path_library_snapshot(self, force_refresh=False):
        self.refresh_flags.append(bool(force_refresh))
        return {
            'paths': [
                {
                    'id': 1,
                    'exists': True,
                    'uses_last_snapshot': False,
                    'path': 'D:/videos',
                    'total': '100 GB',
                    'free': '50 GB',
                    'used': '50 GB',
                    'usage_percent': '50',
                    'created_at': '2026-06-21 21:00:00',
                }
            ],
            'summary': {
                'path_count': 1,
                'connected_count': 1,
                'total': '100 GB',
                'free': '50 GB',
                'used': '50 GB',
                'usage_percent': '50',
            },
            'refreshed_at': '2026-06-21 21:10:00',
        }


class PathLibraryViewerTest(unittest.TestCase):
    def test_uses_cached_snapshot_on_open_and_force_refresh_on_button_click(self):
        backend = PathLibraryBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = PathLibraryWindow(backend)
            try:
                self.assertEqual(backend.refresh_flags, [False])
                self.assertIn('2026-06-21 21:10:00', window.last_refreshed_label.text())

                window.load_data(force_refresh=True)

                self.assertEqual(backend.refresh_flags, [False, True])
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
