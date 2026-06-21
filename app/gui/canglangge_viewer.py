from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


class CanglanggeViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('canglangge.title'))
        self.resize(1120, 620)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)

        self.btn_batch_admit = QPushButton(tr('canglangge.batch_admit'))
        self.btn_batch_admit.clicked.connect(self.admit_selected_candidates)

        self.btn_batch_delete = QPushButton(tr('canglangge.batch_delete'))
        self.btn_batch_delete.clicked.connect(self.delete_selected_candidates)

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))

        action_layout.addWidget(self.last_refreshed_label)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_batch_admit)
        action_layout.addWidget(self.btn_batch_delete)
        action_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(tr('canglangge.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(action_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [
                self.btn_batch_admit,
                self.btn_batch_delete,
                self.btn_refresh,
                self.table,
            ]
        )

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.list_canglangge_candidates_snapshot(force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def render_rows(self):
        self.table.setRowCount(0)
        for row_index, row_data in enumerate(self.rows):
            self.table.insertRow(row_index)
            values = (
                row_data.get('actor_name', ''),
                '\n'.join(row_data.get('prefixes', []) or []),
                row_data.get('birthday', ''),
                row_data.get('age', ''),
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if column_index >= 2:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)

            actor_name = str(row_data.get('actor_name', '') or '').strip()
            self.table.setCellWidget(row_index, 4, self.build_action_buttons(actor_name))

    def build_action_buttons(self, actor_name):
        admit_button = QPushButton(tr('canglangge.admit'))
        admit_button.clicked.connect(lambda _checked=False, value=actor_name: self.admit_candidates([value]))

        delete_button = QPushButton(tr('canglangge.delete'))
        delete_button.clicked.connect(lambda _checked=False, value=actor_name: self.delete_candidates([value]))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(admit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def selected_actor_names(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        actor_names = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item is not None and item.text().strip():
                actor_names.append(item.text().strip())
        return actor_names

    def admit_selected_candidates(self):
        actor_names = self.selected_actor_names()
        if not actor_names:
            QMessageBox.information(self, tr('common.no_selection'), tr('canglangge.select_rows'))
            return
        self.admit_candidates(actor_names)

    def admit_candidates(self, actor_names):
        normalized_names = self._normalize_actor_names(actor_names)
        if not normalized_names:
            return
        self.start_async_task(
            lambda: self._run_admit_task(normalized_names),
            self._on_admit_finished,
            tr('canglangge.admit_failed'),
        )

    def delete_selected_candidates(self):
        actor_names = self.selected_actor_names()
        if not actor_names:
            QMessageBox.information(self, tr('common.no_selection'), tr('canglangge.select_rows'))
            return
        self.delete_candidates(actor_names)

    def delete_candidates(self, actor_names):
        normalized_names = self._normalize_actor_names(actor_names)
        if not normalized_names:
            return
        answer = QMessageBox.question(
            self,
            tr('canglangge.delete_confirm_title'),
            tr('canglangge.delete_confirm_message', count=len(normalized_names)),
        )
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self._run_delete_task(normalized_names),
            self._on_delete_finished,
            tr('canglangge.delete_failed'),
        )

    def _run_admit_task(self, actor_names):
        admitted_count = self.backend_client.admit_canglangge_candidates(actor_names)
        return {
            'admitted_count': admitted_count,
            'snapshot': self.backend_client.list_canglangge_candidates_snapshot(),
        }

    def _run_delete_task(self, actor_names):
        deleted_count = self.backend_client.delete_canglangge_candidates(actor_names)
        return {
            'deleted_count': deleted_count,
            'snapshot': self.backend_client.list_canglangge_candidates_snapshot(),
        }

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.rows = list(payload.get('candidates', payload.get('rows', [])) or [])
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self.render_rows()

    def _on_admit_finished(self, result):
        self._on_load_data_finished((result or {}).get('snapshot', {}))
        QMessageBox.information(
            self,
            tr('canglangge.admit_completed'),
            tr('canglangge.admit_completed_message', count=int((result or {}).get('admitted_count', 0) or 0)),
        )

    def _on_delete_finished(self, result):
        self._on_load_data_finished((result or {}).get('snapshot', {}))
        QMessageBox.information(
            self,
            tr('canglangge.delete_completed'),
            tr('canglangge.delete_completed_message', count=int((result or {}).get('deleted_count', 0) or 0)),
        )

    def _remove_actor_names_locally(self, actor_names):
        target_names = set(self._normalize_actor_names(actor_names))
        self.rows = [
            dict(row or {})
            for row in self.rows
            if str((row or {}).get('actor_name', '') or '').strip() not in target_names
        ]
        self.render_rows()

    @staticmethod
    def _normalize_actor_names(actor_names):
        normalized_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_names.append(normalized_name)
        return normalized_names
