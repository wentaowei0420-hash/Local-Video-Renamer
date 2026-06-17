from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.actor_library_settings import load_actor_library_settings, save_actor_library_settings
from app.gui.actor_library_sorting import (
    ACTOR_SORT_FIELDS,
    ACTOR_SORT_ORDERS,
    DEFAULT_ACTOR_SORT_FIELD,
    DEFAULT_ACTOR_SORT_ORDER,
    normalize_actor_sort_settings,
    sort_actor_rows,
)
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.i18n import tr
from app.services.actor_profile_update_service import ActorProfileUpdateService
from app.services.detail_quick_filter_service import ACTOR_DETAIL_FILTER_OPTIONS, DETAIL_FILTER_ALL, filter_library_rows


class ActorViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.all_rows = []
        self.rows = []
        self.detail_quick_filter_key = DETAIL_FILTER_ALL
        self.editing_actor_name = None
        self.editing_row = None
        self.editing_actor_original = None
        self.actor_profile_update_service = ActorProfileUpdateService()
        self.action_buttons = {}
        self.sort_settings = load_actor_library_settings()
        self._init_async_task_host()
        self._init_deferred_reload(self.load_data)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('actor.viewer.title'))
        self.resize(1220, 540)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('actor.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)

        self.detail_filter_combo = QComboBox()
        for filter_key in ACTOR_DETAIL_FILTER_OPTIONS:
            self.detail_filter_combo.addItem(tr(f'detail.quick_filter.{filter_key}'), filter_key)
        initial_filter_index = self.detail_filter_combo.findData(self.detail_quick_filter_key)
        self.detail_filter_combo.setCurrentIndex(max(initial_filter_index, 0))
        self.btn_apply_detail_filter = QPushButton(tr('detail.apply_filter'))
        self.btn_apply_detail_filter.clicked.connect(self.apply_quick_filter_from_controls)

        self.sort_field_combo = QComboBox()
        for sort_field in ACTOR_SORT_FIELDS:
            self.sort_field_combo.addItem(tr(f'actor.viewer.sort_field.{sort_field}'), sort_field)

        self.sort_order_combo = QComboBox()
        for sort_order in ACTOR_SORT_ORDERS:
            self.sort_order_combo.addItem(tr(f'common.sort_order.{sort_order}'), sort_order)

        self.btn_apply_sort = QPushButton(tr('common.ok'))
        self.btn_apply_sort.clicked.connect(self.apply_sort_settings)
        self.apply_sort_settings_to_controls()

        self.btn_reset_avfan = QPushButton(tr('actor.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('actor.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel(tr('common.filter_realtime')))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(QLabel(tr('detail.quick_filter_label')))
        top_layout.addWidget(self.detail_filter_combo)
        top_layout.addWidget(self.btn_apply_detail_filter)
        top_layout.addWidget(QLabel(tr('common.sort_field_label')))
        top_layout.addWidget(self.sort_field_combo)
        top_layout.addWidget(QLabel(tr('common.sort_order_label')))
        top_layout.addWidget(self.sort_order_combo)
        top_layout.addWidget(self.btn_apply_sort)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(tr('actor.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [
                self.search_input,
                self.detail_filter_combo,
                self.btn_apply_detail_filter,
                self.sort_field_combo,
                self.sort_order_combo,
                self.btn_apply_sort,
                self.btn_reset_avfan,
                self.btn_reset_javtxt,
                self.btn_refresh,
                self.table,
            ]
        )

    def load_data(self):
        if self.is_async_task_running():
            self.schedule_deferred_reload(0)
            return
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {'rows': self.backend_client.list_actors(search_text)},
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('name', ''),
                row_data.get('actor_id', ''),
                row_data.get('birthday', ''),
                row_data.get('age', ''),
                row_data.get('enrichment_status', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (1, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            actor_name = row_data.get('name', '')
            self.table.setCellWidget(row_idx, 5, self.build_detail_button(actor_name))
            self.table.setCellWidget(row_idx, 6, self.build_action_buttons(actor_name))

    def build_detail_button(self, actor_name):
        button = QPushButton(tr('actor.viewer.detail'))
        button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, actor_name):
        edit_button = QPushButton(tr('actor.viewer.edit'))
        edit_button.clicked.connect(lambda _checked=False, value=actor_name: self.handle_edit_button(value))
        delete_button = QPushButton(tr('actor.viewer.delete'))
        delete_button.clicked.connect(lambda _checked=False, value=actor_name: self.delete_actor(value))
        self.action_buttons[actor_name] = {'edit': edit_button, 'delete': delete_button}

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_actor_detail(self, actor_name):
        if not actor_name:
            return
        viewer = ActorDetailViewerWindow(self.backend_client, actor_name, self)
        viewer.exec_()

    def filter_data(self, text):
        self.clear_edit_state()
        self.schedule_deferred_reload()

    def apply_sort_settings(self):
        if self.editing_actor_name is not None:
            QMessageBox.information(self, tr('actor.viewer.editing_title'), tr('actor.viewer.editing_message'))
            return
        self.sort_settings = normalize_actor_sort_settings({
            'sort_field': self.sort_field_combo.currentData(),
            'sort_order': self.sort_order_combo.currentData(),
        })
        try:
            save_actor_library_settings(self.sort_settings)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), tr('actor.viewer.sort_save_failed', error=exc))
            return

        self.rebuild_visible_rows()

    def apply_quick_filter_from_controls(self):
        current_name = self.current_selected_actor_name()
        target_name = self.apply_detail_quick_filter(self.detail_filter_combo.currentData(), current_name)
        if not target_name:
            self.table.clearSelection()

    def apply_sort_settings_to_controls(self):
        sort_field = self.sort_settings.get('sort_field', DEFAULT_ACTOR_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_ACTOR_SORT_ORDER)
        field_index = self.sort_field_combo.findData(sort_field)
        order_index = self.sort_order_combo.findData(sort_order)
        self.sort_field_combo.setCurrentIndex(max(field_index, 0))
        self.sort_order_combo.setCurrentIndex(max(order_index, 0))

    def sorted_rows(self, rows):
        return sort_actor_rows(
            rows,
            self.sort_settings.get('sort_field', DEFAULT_ACTOR_SORT_FIELD),
            self.sort_settings.get('sort_order', DEFAULT_ACTOR_SORT_ORDER),
        )

    def rebuild_visible_rows(self):
        self.rows = self.sorted_rows(filter_library_rows(self.all_rows, self.detail_quick_filter_key))
        self.render_rows(self.rows)

    def clear_edit_state(self):
        self.editing_actor_name = None
        self.editing_row = None
        self.editing_actor_original = None

    def handle_edit_button(self, actor_name):
        if self.editing_actor_name is None:
            self.start_actor_edit(actor_name)
            return
        if self.editing_actor_name != actor_name:
            QMessageBox.information(self, tr('actor.viewer.editing_title'), tr('actor.viewer.editing_message'))
            return
        self.confirm_actor_edit()

    def start_actor_edit(self, actor_name):
        row = self.find_row_by_actor_name(actor_name)
        if row < 0:
            QMessageBox.warning(self, tr('common.prompt'), tr('actor.viewer.not_found', actor_name=actor_name))
            return
        self.editing_actor_name = actor_name
        self.editing_row = row
        self.editing_actor_original = {
            'name': self._item_text(row, 0),
            'birthday': self._item_text(row, 2),
            'age': self._item_text(row, 3),
        }
        self.set_actor_row_editable(row, True)
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText(tr('common.ok'))
        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_actor_edit(self):
        if self.editing_actor_name is None or self.editing_row is None:
            return
        old_name = self.editing_actor_name
        original = dict(self.editing_actor_original or {})
        if not original:
            self.clear_edit_state()
            return

        new_name = self._item_text(self.editing_row, 0)
        birthday = self._item_text(self.editing_row, 2)
        age = self._item_text(self.editing_row, 3)
        if not new_name:
            self.set_actor_row_editable(self.editing_row, False)
            self.restore_editing_row_values(original)
            self.reset_row_button_text(old_name)
            self.clear_edit_state()
            QMessageBox.warning(self, tr('common.prompt'), tr('actor.viewer.name_required'))
            return

        try:
            normalized_payload = self.actor_profile_update_service.normalize_payload(new_name, birthday=birthday, age=age)
        except Exception as exc:
            QMessageBox.warning(self, tr('common.prompt'), str(exc))
            return

        self._set_item_text(self.editing_row, 0, normalized_payload.get('name', ''))
        self._set_item_text(self.editing_row, 2, normalized_payload.get('birthday', ''))
        self._set_item_text(self.editing_row, 3, normalized_payload.get('age', ''))
        self.set_actor_row_editable(self.editing_row, False)

        self.clear_edit_state()
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.rename_actor(
                    old_name,
                    normalized_payload.get('name', ''),
                    birthday=normalized_payload.get('birthday', ''),
                    age=normalized_payload.get('age', ''),
                ),
                lambda: self.backend_client.list_actors(search_text),
                old_name=old_name,
                new_name=normalized_payload.get('name', ''),
            ),
            self._on_update_finished,
            tr('actor.viewer.rename_failed'),
        )

    def _on_update_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('actor.viewer.rename_completed'),
            tr(
                'actor.viewer.update_completed_message',
                actor_name=result.get('new_name', '') or result.get('old_name', ''),
            ),
        )

    def reset_row_button_text(self, actor_name):
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText(tr('actor.viewer.edit'))

    def set_actor_row_editable(self, row, editable):
        for column in (0, 2, 3):
            item = self.table.item(row, column)
            if item is None:
                continue
            if editable:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def restore_editing_row_values(self, values):
        if self.editing_row is None:
            return
        self._set_item_text(self.editing_row, 0, values.get('name', ''))
        self._set_item_text(self.editing_row, 2, values.get('birthday', ''))
        self._set_item_text(self.editing_row, 3, values.get('age', ''))

    def _item_text(self, row, column):
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ''

    def _set_item_text(self, row, column, value):
        item = self.table.item(row, column)
        if item is not None:
            item.setText(str(value or ''))

    def find_row_by_actor_name(self, actor_name):
        target = str(actor_name or '').strip()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip() == target:
                return row
        return -1

    def delete_actor(self, actor_name):
        if self.editing_actor_name is not None:
            QMessageBox.information(self, tr('actor.viewer.editing_title'), tr('actor.viewer.editing_message'))
            return
        answer = QMessageBox.question(
            self,
            tr('actor.viewer.confirm_delete_title'),
            tr('actor.viewer.confirm_delete_message', actor_name=actor_name),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.delete_actor(actor_name),
                lambda: self.backend_client.list_actors(search_text),
                actor_name=actor_name,
            ),
            self._on_delete_finished,
            tr('actor.viewer.delete_failed'),
        )

    def _on_delete_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('actor.viewer.delete_completed'),
            tr('actor.viewer.delete_completed_message', actor_name=result.get('actor_name', '')),
        )

    def reset_selected_rows(self, source_key):
        actor_names = self.selected_actor_names()
        if not actor_names:
            QMessageBox.information(self, tr('common.no_selection'), tr('actor.viewer.select_reset_rows'))
            return
        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            tr('actor.viewer.confirm_reset_title'),
            tr('actor.viewer.confirm_reset_message', count=len(actor_names), source_label=source_label),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_actor_enrichments(actor_names, source_key=source_key),
                'rows': self.backend_client.list_actors(search_text),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_actor_names(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        actor_names = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                actor_names.append(item.text().strip())
        return actor_names

    def current_selected_actor_name(self):
        actor_names = self.selected_actor_names()
        return actor_names[0] if actor_names else ''

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        self.all_rows = list((result or {}).get('rows', []) or [])
        self.rebuild_visible_rows()

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or tr('common.reset_source_fallback'))
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr('actor.viewer.reset_completed_message', count=reset_count, source_label=source_label),
        )

    def apply_detail_quick_filter(self, filter_key, current_name=''):
        self.detail_quick_filter_key = str(filter_key or DETAIL_FILTER_ALL).strip() or DETAIL_FILTER_ALL
        self.rebuild_visible_rows()
        target_name = str(current_name or '').strip()
        visible_names = self.detail_navigation_keys()
        if target_name in visible_names:
            self.select_actor_row(target_name)
            return target_name
        if visible_names:
            self.select_actor_row(visible_names[0])
            return visible_names[0]
        return ''

    def current_detail_quick_filter(self):
        return self.detail_quick_filter_key

    def detail_navigation_keys(self):
        return [
            str((row or {}).get('name', '') or '').strip()
            for row in self.rows
            if str((row or {}).get('name', '') or '').strip()
        ]

    def neighbor_detail_key(self, current_name, offset):
        names = self.detail_navigation_keys()
        target_name = str(current_name or '').strip()
        if target_name not in names:
            return ''
        index = names.index(target_name) + int(offset or 0)
        if index < 0 or index >= len(names):
            return ''
        return names[index]

    def select_actor_row(self, actor_name):
        row = self.find_row_by_actor_name(actor_name)
        if row >= 0:
            self.table.selectRow(row)
