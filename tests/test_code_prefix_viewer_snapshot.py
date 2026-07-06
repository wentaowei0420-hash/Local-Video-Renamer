import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.calls = []

    def list_code_prefixes_snapshot(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=200,
        offset=0,
        force_refresh=False,
    ):
        self.calls.append((search_text, sort_field, sort_order, limit, offset, bool(force_refresh)))
        return {
            'prefixes': [
                {
                    'prefix': 'ADN',
                    'video_count': 12,
                    'enrichment_status': '',
                    'avfan_total_videos': 30,
                    'earliest_release_date': '2024-01-01',
                    'latest_release_date': '2024-02-01',
                }
            ],
            'total_count': 1,
            'limit': limit,
            'offset': offset,
            'refreshed_at': '2026-07-06 14:10:00' if force_refresh else '2026-07-06 14:00:00',
            'refresh_duration_text': '18秒' if force_refresh else '11秒',
            'cache_hit': not force_refresh,
        }


class CodePrefixViewerSnapshotTest(unittest.TestCase):
    def test_startup_load_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                self.assertEqual(
                    backend.calls,
                    [
                        ('', 'prefix', 'asc', window.page_size, 0, False),
                        ('', 'prefix', 'asc', window.page_size, 0, True),
                    ],
                )
                self.assertIn('2026-07-06 14:10:00', window.last_refreshed_label.text())
                self.assertIn('18秒', window.last_refresh_duration_label.text())
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
