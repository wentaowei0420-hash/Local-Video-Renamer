from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


class PathLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.selected_path = ''
        self.paths = []
        self.summary = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('path.viewer.title'))
        self.resize(900, 460)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()

        self.btn_add = QPushButton(tr('path.viewer.add'))
        self.btn_add.clicked.connect(self.add_path)
        self.btn_delete = QPushButton(tr('path.viewer.delete'))
        self.btn_delete.clicked.connect(self.delete_selected_path)
        self.btn_use = QPushButton(tr('path.viewer.use_selected'))
        self.btn_use.clicked.connect(self.use_selected_path)
        self.btn_refresh = QPushButton(tr('path.viewer.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))

        top_layout.addWidget(QLabel(tr('path.viewer.saved_paths')))
        top_layout.addStretch()
        top_layout.addWidget(self.last_refreshed_label)
        top_layout.addWidget(self.btn_add)
        top_layout.addWidget(self.btn_delete)
        top_layout.addWidget(self.btn_use)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(tr('path.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self.use_selected_path)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_add, self.btn_delete, self.btn_use, self.btn_refresh, self.table])

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.get_path_library_snapshot(force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def render_rows(self):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(self.paths):
            self.table.insertRow(row_idx)
            if row_data.get('exists'):
                entrance = tr('path.viewer.entrance_usb')
            elif row_data.get('uses_last_snapshot'):
                entrance = tr('path.viewer.entrance_offline_last')
            else:
                entrance = tr('path.viewer.entrance_offline')

            usage_percent = row_data.get('usage_percent', '')
            usage_text = f'{usage_percent}%' if usage_percent != '' else ''
            values = (
                row_data.get('id', ''),
                entrance,
                row_data.get('path', ''),
                row_data.get('total', ''),
                row_data.get('free', ''),
                row_data.get('used', ''),
                usage_text,
                row_data.get('created_at', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (0, 1, 3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        usage_percent = self.summary.get('usage_percent', '')
        usage_text = f'{usage_percent}%' if usage_percent != '' else ''
        summary_values = (
            tr('path.viewer.summary_total'),
            tr(
                'path.viewer.summary_count',
                path_count=self.summary.get('path_count', 0),
                connected_count=self.summary.get('connected_count', 0),
            ),
            tr('path.viewer.summary_all_paths'),
            self.summary.get('total', ''),
            self.summary.get('free', ''),
            self.summary.get('used', ''),
            usage_text,
            '',
        )
        for col_idx, value in enumerate(summary_values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter if col_idx != 2 else Qt.AlignLeft | Qt.AlignVCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.table.setItem(row_idx, col_idx, item)

    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, tr('path.viewer.add_dialog'))
        if not folder_path:
            return
        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.add_path(folder_path)),
            self._on_load_data_finished,
            tr('path.viewer.add_failed'),
        )

    def delete_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, tr('common.prompt'), tr('path.viewer.delete_select_first'))
            return

        path_id = int(self.table.item(row, 0).text())
        path_text = self.table.item(row, 2).text()
        answer = QMessageBox.question(
            self,
            tr('path.viewer.confirm_delete_title'),
            tr('path.viewer.confirm_delete_message', path_text=path_text),
        )
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.delete_path(path_id)),
            self._on_load_data_finished,
            tr('path.viewer.delete_failed'),
        )

    def _reload_after(self, operation):
        operation()
        return self.backend_client.get_path_library_snapshot()

    def use_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, tr('common.prompt'), tr('path.viewer.use_select_first'))
            return
        self.selected_path = self.table.item(row, 2).text()
        self.accept()

    def current_row(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return -1
        row = selected_ranges[0].topRow()
        item = self.table.item(row, 0)
        if not item or not item.text().isdigit():
            return -1
        return row

    def _on_load_data_finished(self, result):
        result = dict(result or {})
        self.paths = list(result.get('paths', []) or [])
        self.summary = dict(result.get('summary', {}) or {})
        refreshed_at = str(result.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self.render_rows()
