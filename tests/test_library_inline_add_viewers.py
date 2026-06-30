import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE
from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


def _layout_widgets(layout):
    widgets = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is not None:
            widgets.append(widget)
    return widgets


def _tracked_layout_widgets(layout, *tracked_widgets):
    widgets = []
    for widget in _layout_widgets(layout):
        if any(widget is tracked for tracked in tracked_widgets):
            widgets.append(widget)
    return widgets


class ActorBackendStub:
    def __init__(self):
        self.rows = [
            {
                'name': 'Alpha',
                'actor_id': '',
                'birthday': '',
                'age': '',
                'raw_age': '',
                'enrichment_status': '',
            }
        ]
        self.added = []
        self.list_calls = 0
        self.reset_calls = []

    def list_actors(self, search_text=''):
        self.list_calls += 1
        search = str(search_text or '').strip().lower()
        if not search:
            return [dict(row) for row in self.rows]
        return [dict(row) for row in self.rows if search in str(row.get('name', '')).lower()]

    def add_actor(self, actor_name, birthday='', age=''):
        self.added.append((actor_name, birthday, age))
        self.rows.append(
            {
                'name': actor_name,
                'actor_id': '',
                'birthday': birthday,
                'age': age,
                'raw_age': age,
                'enrichment_status': '',
            }
        )
        return 1

    def reset_actor_enrichments(self, actor_names, source_key=None):
        self.reset_calls.append((list(actor_names or []), source_key))
        return len(actor_names or [])


class CodePrefixBackendStub:
    def __init__(self):
        self.rows = [
            {
                'prefix': 'ABC',
                'video_count': 1,
                'enrichment_status': '',
                'avfan_total_videos': 0,
                'earliest_release_date': '',
                'latest_release_date': '',
            }
        ]
        self.added = []
        self.list_calls = 0
        self.reset_calls = []

    def list_code_prefixes(self, search_text=''):
        self.list_calls += 1
        search = str(search_text or '').strip().upper()
        if not search:
            return [dict(row) for row in self.rows]
        return [dict(row) for row in self.rows if search in str(row.get('prefix', '')).upper()]

    def add_code_prefix(self, prefix):
        self.added.append(prefix)
        self.rows.append(
            {
                'prefix': prefix,
                'video_count': 0,
                'enrichment_status': '',
                'avfan_total_videos': 0,
                'earliest_release_date': '',
                'latest_release_date': '',
            }
        )
        return 1

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        self.reset_calls.append((list(prefixes or []), source_key))
        return len(prefixes or [])


class ViewerInlineAddTest(unittest.TestCase):
    def test_actor_viewer_uses_two_row_toolbar_and_hides_actor_id_column(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                root_layout = window.layout()
                first_row = root_layout.itemAt(0).layout()
                second_row = root_layout.itemAt(1).layout()

                first_row_widgets = _tracked_layout_widgets(
                    first_row,
                    window.search_input,
                    window.sort_field_combo,
                    window.sort_order_combo,
                    window.btn_apply_sort,
                )
                second_row_widgets = _tracked_layout_widgets(
                    second_row,
                    window.detail_filter_combo,
                    window.btn_apply_detail_filter,
                    window.btn_add,
                    window.btn_reset_avfan,
                    window.btn_reset_javtxt,
                    window.btn_reset_binghuo,
                    window.btn_reset_baomu,
                    window.btn_refresh,
                )

                self.assertEqual(window.table.columnCount(), 6)
                self.assertEqual(
                    [window.table.horizontalHeaderItem(index).text() for index in range(window.table.columnCount())],
                    ['演员', '生日', '年龄', '补全状态', '详情', '操作'],
                )
                self.assertEqual(
                    first_row_widgets,
                    [
                        window.search_input,
                        window.sort_field_combo,
                        window.sort_order_combo,
                        window.btn_apply_sort,
                    ],
                )
                self.assertEqual(
                    second_row_widgets,
                    [
                        window.detail_filter_combo,
                        window.btn_apply_detail_filter,
                        window.btn_add,
                        window.btn_reset_avfan,
                        window.btn_reset_javtxt,
                        window.btn_reset_binghuo,
                        window.btn_reset_baomu,
                        window.btn_refresh,
                    ],
                )
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_viewer_binghuo_reset_uses_selected_rows(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                window.table.selectRow(0)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(
                    QMessageBox, 'information'
                ):
                    window.btn_reset_binghuo.click()

                self.assertEqual(backend.reset_calls, [(['Alpha'], BINGHUO_ACTOR_SOURCE)])
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_viewer_baomu_reset_uses_selected_rows(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                window.table.selectRow(0)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(
                    QMessageBox, 'information'
                ):
                    window.btn_reset_baomu.click()

                self.assertEqual(backend.reset_calls, [(['Alpha'], BAOMU_ACTOR_SOURCE)])
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_viewer_scales_actor_and_status_columns_for_new_layout(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                window.resize(1220, 540)
                window.show()
                _APP.processEvents()

                viewport_width = window.table.viewport().width()
                actor_width = max(120, viewport_width // 7)
                birthday_width = 120
                age_width = 72
                detail_width = 104
                base_status_width = max(320, int(viewport_width * 0.3))
                base_action_width = max(
                    188,
                    viewport_width - actor_width - birthday_width - age_width - base_status_width - detail_width,
                )
                expected_action_width = max(188, int(base_action_width * (2 / 3)))
                expected_status_width = base_status_width + (base_action_width - expected_action_width)

                self.assertAlmostEqual(window.table.columnWidth(0), viewport_width // 7, delta=16)
                self.assertEqual(window.table.columnWidth(3), expected_status_width)
                self.assertEqual(window.table.columnWidth(5), expected_action_width)
                self.assertGreater(window.table.columnWidth(3), window.table.columnWidth(0))
                self.assertLess(window.table.columnWidth(5), base_action_width)
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_viewer_adds_top_inline_row_and_confirms(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                backend.list_calls = 0
                window.handle_add_button()

                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(0, 0).text(), '')
                self.assertTrue(window.table.item(0, 0).flags() & Qt.ItemIsEditable)

                window.table.item(0, 0).setText('Beta')
                with patch.object(QMessageBox, 'information'):
                    window.handle_add_button()

                self.assertEqual(backend.added, [('Beta', '', '')])
                self.assertEqual(backend.list_calls, 0)
                self.assertIn('Beta', [window.table.item(row, 0).text() for row in range(window.table.rowCount())])
            finally:
                window.hide()
                window.deleteLater()

    def test_code_prefix_viewer_warns_before_duplicate_add(self):
        backend = CodePrefixBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixViewerWindow(backend)
            try:
                window.handle_add_button()
                window.table.item(0, 0).setText('abc')

                with patch.object(QMessageBox, 'warning') as warning_mock:
                    window.handle_add_button()

                self.assertEqual(backend.added, [])
                self.assertTrue(warning_mock.called)
            finally:
                window.hide()
                window.deleteLater()

    def test_code_prefix_viewer_adds_without_reloading_full_library(self):
        backend = CodePrefixBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixViewerWindow(backend)
            try:
                backend.list_calls = 0
                window.handle_add_button()
                window.table.item(0, 0).setText('ipx')

                with patch.object(QMessageBox, 'information'):
                    window.handle_add_button()

                self.assertEqual(backend.added, ['IPX'])
                self.assertEqual(backend.list_calls, 0)
                self.assertIn('IPX', [window.table.item(row, 0).text() for row in range(window.table.rowCount())])
            finally:
                window.hide()
                window.deleteLater()

if __name__ == '__main__':
    unittest.main()
