import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.calls = []

    def list_actors_snapshot(
        self,
        search_text='',
        sort_field='name',
        sort_order='asc',
        limit=200,
        offset=0,
        force_refresh=False,
    ):
        self.calls.append((search_text, sort_field, sort_order, limit, offset, bool(force_refresh)))
        return {
            'actors': [
                {
                    'name': 'Alpha',
                    'birthday': '',
                    'age': '',
                    'enrichment_status': '',
                }
            ],
            'total_count': 1,
            'limit': limit,
            'offset': offset,
            'refreshed_at': '2026-07-06 15:00:00' if force_refresh else '2026-07-06 14:50:00',
            'refresh_duration_text': '12秒' if force_refresh else '9秒',
            'cache_hit': not force_refresh,
        }


class ActorViewerSnapshotTest(unittest.TestCase):
    def test_startup_load_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch(
                'app.gui.actor_viewer.load_actor_library_settings',
                return_value={'sort_field': 'name', 'sort_order': 'asc'},
            ),
            patch('app.gui.actor_viewer.save_actor_library_settings'),
        ):
            window = ActorViewerWindow(backend)
            try:
                self.assertEqual(
                    backend.calls,
                    [
                        ('', 'name', 'asc', window.page_size, 0, False),
                        ('', 'name', 'asc', window.page_size, 0, True),
                    ],
                )
                self.assertIn('2026-07-06 15:00:00', window.last_refreshed_label.text())
                self.assertIn('12秒', window.last_refresh_duration_label.text())
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
