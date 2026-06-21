import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.core.ladder_board import LADDER_BOARD_ACTOR
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.ladder_board_viewer import LadderBoardWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class LadderBoardBackendStub:
    def __init__(self):
        self.refresh_flags = []

    def get_ladder_board_snapshot(self, board_key, force_refresh=False):
        self.refresh_flags.append((board_key, bool(force_refresh)))
        return {
            'board': {
                'board_key': board_key,
                'entity_type': 'actor',
                'candidates': [{'entity_name': 'ActorA', 'display_name': 'ActorA', 'local_video_count': 3}],
                'selected': [],
            },
            'refreshed_at': '2026-06-21 21:00:00',
        }


class LadderBoardViewerTest(unittest.TestCase):
    def test_uses_cached_snapshot_on_open_and_force_refresh_on_button_click(self):
        backend = LadderBoardBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = LadderBoardWindow(backend)
            try:
                self.assertEqual(backend.refresh_flags, [(LADDER_BOARD_ACTOR, False)])
                self.assertIn('2026-06-21 21:00:00', window.last_refreshed_label.text())

                window.load_board(force_refresh=True)

                self.assertEqual(
                    backend.refresh_flags,
                    [(LADDER_BOARD_ACTOR, False), (LADDER_BOARD_ACTOR, True)],
                )
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
