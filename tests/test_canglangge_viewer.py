import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QMessageBox

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.canglangge_viewer import CanglanggeViewerWindow
from app.gui.main_window import VidNormApp


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class CanglanggeBackendStub:
    def __init__(self):
        self.rows = [
            {
                'actor_name': 'ActorA',
                'prefixes': ['IPX'],
                'birthday': '',
                'age': '',
            },
            {
                'actor_name': 'ActorB',
                'prefixes': ['MIDV'],
                'birthday': '',
                'age': '',
            },
        ]
        self.admitted = []
        self.deleted = []
        self.snapshot_refresh_flags = []

    def list_canglangge_candidates_snapshot(self, force_refresh=False):
        self.snapshot_refresh_flags.append(bool(force_refresh))
        return {
            'candidates': [dict(row) for row in self.rows],
            'refreshed_at': '2026-06-21 21:20:00',
        }

    def list_canglangge_candidates(self):
        return [dict(row) for row in self.rows]

    def admit_canglangge_candidates(self, actor_names):
        actor_names = list(actor_names or [])
        self.admitted.append(actor_names)
        self.rows = [row for row in self.rows if row.get('actor_name') not in set(actor_names)]
        return len(actor_names)

    def delete_canglangge_candidates(self, actor_names):
        actor_names = list(actor_names or [])
        self.deleted.append(actor_names)
        self.rows = [row for row in self.rows if row.get('actor_name') not in set(actor_names)]
        return len(actor_names)


class CanglanggeViewerTest(unittest.TestCase):
    def test_renders_candidate_rows(self):
        backend = CanglanggeBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CanglanggeViewerWindow(backend)
            try:
                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(0, 0).text(), 'ActorA')
                self.assertEqual(window.table.item(0, 1).text(), 'IPX')
                self.assertEqual(window.table.columnCount(), 5)
                self.assertEqual(backend.snapshot_refresh_flags, [False])
                self.assertIn('2026-06-21 21:20:00', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_manual_refresh_uses_force_refresh_snapshot(self):
        backend = CanglanggeBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CanglanggeViewerWindow(backend)
            try:
                window.load_data(force_refresh=True)
                self.assertEqual(backend.snapshot_refresh_flags, [False, True])
            finally:
                window.hide()
                window.deleteLater()

    def test_batch_admit_removes_selected_rows_locally(self):
        backend = CanglanggeBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CanglanggeViewerWindow(backend)
            try:
                window.table.selectRow(0)

                with patch.object(QMessageBox, 'information'):
                    window.admit_selected_candidates()

                self.assertEqual(backend.admitted, [['ActorA']])
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), 'ActorB')
            finally:
                window.hide()
                window.deleteLater()

    def test_row_delete_blacklists_candidate_and_removes_it(self):
        backend = CanglanggeBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CanglanggeViewerWindow(backend)
            try:
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    with patch.object(QMessageBox, 'information'):
                        window.delete_candidates(['ActorB'])

                self.assertEqual(backend.deleted, [['ActorB']])
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), 'ActorA')
            finally:
                window.hide()
                window.deleteLater()

    def test_main_window_opens_canglangge_viewer(self):
        app = VidNormApp.__new__(VidNormApp)
        app.backend_client = object()
        created = {}

        class FakeViewer:
            def __init__(self, backend_client, parent=None):
                created['backend_client'] = backend_client
                created['parent'] = parent

            def exec_(self):
                created['opened'] = True

        with patch('app.gui.main_window.CanglanggeViewerWindow', FakeViewer):
            VidNormApp.show_canglangge_viewer(app)

        self.assertIs(created.get('backend_client'), app.backend_client)
        self.assertIs(created.get('parent'), app)
        self.assertTrue(created.get('opened'))


if __name__ == '__main__':
    unittest.main()
