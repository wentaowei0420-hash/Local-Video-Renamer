import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication, QDialog

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.masterpiece_viewer import MasterpieceDetailWindow, MasterpieceWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class MasterpieceBackendStub:
    def __init__(self):
        self.entries = [
            {
                'code': 'PFSA-001',
                'title': 'Perfect First Scene',
                'author': 'Alice',
                'medal': '年度新人',
                'medals': ['年度新人'],
            }
        ]
        self.add_calls = []
        self.medal_calls = []
        self.detail_calls = []

    def list_masterpiece_entries(self):
        return [dict(row) for row in self.entries]

    def add_masterpiece_entry(self, code):
        normalized_code = str(code or '').strip().upper()
        self.add_calls.append(normalized_code)
        row = {
            'code': normalized_code,
            'title': 'Second Story',
            'author': 'Beta',
            'medal': '',
            'medals': [],
        }
        self.entries.append(row)
        return dict(row)

    def update_masterpiece_entry_medal(self, code, medal):
        self.medal_calls.append((code, medal))
        for row in self.entries:
            if row['code'] == code:
                row['medal'] = medal
                row['medals'] = [segment for segment in medal.split('\n') if segment]
                return dict(row)
        raise AssertionError('missing code')

    def get_video_detail(self, code):
        self.detail_calls.append(code)
        return {
            'code': code,
            'title': 'Perfect First Scene',
            'author': 'Alice',
            'duration': '01:30:00',
            'size': '3.20',
            'storage_location': r'D:\videos',
            'avfan_movie_id': 'avfan-001',
            'javtxt_movie_id': 'javtxt-001',
            'javtxt_url': 'https://example.com/pfsa-001',
            'javtxt_title': 'Perfect First Scene',
            'javtxt_actors': 'Alice',
            'javtxt_tags': '剧情,新人',
            'video_category': '单体',
            'release_date': '2024-05-01',
            'maker': 'Maker A',
            'publisher': 'Publisher A',
            'avfan_enrichment_status': '已补全',
            'javtxt_enrichment_status': '已补全',
            'supplement_enrichment_status': 'pending',
            'supplement_enrichment_error': '',
            'supplement_enriched_at': '2026-07-06 00:00:00',
        }


class _AcceptedMedalDialog:
    def __init__(self, *_args, **_kwargs):
        pass

    def exec_(self):
        return QDialog.Accepted

    def medal_text(self):
        return '年度新人\n白金常青'


class MasterpieceViewerTest(unittest.TestCase):
    def test_window_loads_entries_and_adds_new_code(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), 'PFSA-001')

                window.code_input.setText('ipx-001')
                window.handle_add_entry()

                self.assertEqual(backend.add_calls, ['IPX-001'])
                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(1, 0).text(), 'IPX-001')
            finally:
                window.hide()
                window.deleteLater()

    def test_window_edits_medal_and_updates_backend(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch(
            'app.gui.masterpiece_viewer.MedalEditDialog',
            _AcceptedMedalDialog,
        ):
            window = MasterpieceWindow(backend)
            try:
                action_button = window.table.cellWidget(0, 4)
                action_button.click()

                self.assertEqual(backend.medal_calls, [('PFSA-001', '年度新人\n白金常青')])
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_renders_all_fields_from_backend(self):
        backend = MasterpieceBackendStub()
        window = MasterpieceDetailWindow(backend, 'PFSA-001')
        try:
            self.assertEqual(backend.detail_calls, ['PFSA-001'])
            self.assertEqual(window.table.rowCount(), 21)
            self.assertEqual(window.table.item(0, 0).text(), '编号')
            self.assertEqual(window.table.item(0, 1).text(), 'PFSA-001')
            self.assertEqual(window.table.item(1, 0).text(), '标题')
            self.assertEqual(window.table.item(1, 1).text(), 'Perfect First Scene')
        finally:
            window.hide()
            window.deleteLater()

    def test_close_event_ignores_close_while_async_task_running(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                event = QCloseEvent()
                with patch.object(window, 'block_close_while_async_running', return_value=True) as block_mock:
                    window.closeEvent(event)

                block_mock.assert_called_once_with(event)
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
