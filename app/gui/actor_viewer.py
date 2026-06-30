from PyQt5.QtCore import QTimer, Qt
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
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
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
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.services.detail import ACTOR_DETAIL_FILTER_OPTIONS, DETAIL_FILTER_ALL, filter_library_rows
from app.services.library import ActorProfileUpdateService


ACTOR_COLUMN_NAME = 0
ACTOR_COLUMN_BIRTHDAY = 1
ACTOR_COLUMN_AGE = 2
ACTOR_COLUMN_STATUS = 3
ACTOR_COLUMN_DETAIL = 4
ACTOR_COLUMN_ACTIONS = 5
DEFAULT_ACTOR_PAGE_SIZE = 200


class ActorViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.all_rows = []
        self.rows = []
        self.total_count = 0
        self.current_offset = 0
        self.page_size = DEFAULT_ACTOR_PAGE_SIZE
        self.detail_quick_filter_key = DETAIL_FILTER_ALL
        self.adding_actor = False
        self.adding_row = None
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
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('actor.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)
        self.search_input.setMinimumWidth(180)

        self.detail_filter_combo = QComboBox()
        for filter_key in ACTOR_DETAIL_FILTER_OPTIONS:
            self.detail_filter_combo.addItem(tr(f'detail.quick_filter.{filter_key}'), filter_key)
        initial_filter_index = self.detail_filter_combo.findData(self.detail_quick_filter_key)
        self.detail_filter_combo.setCurrentIndex(max(initial_filter_index, 0))
        self.detail_filter_combo.setMinimumWidth(180)
        self.btn_apply_detail_filter = QPushButton(tr('detail.apply_filter'))
        self.btn_apply_detail_filter.clicked.connect(self.apply_quick_filter_from_controls)

        self.sort_field_combo = QComboBox()
        for sort_field in ACTOR_SORT_FIELDS:
            self.sort_field_combo.addItem(tr(f'actor.viewer.sort_field.{sort_field}'), sort_field)
        self.sort_field_combo.setMinimumWidth(120)

        self.sort_order_combo = QComboBox()
        for sort_order in ACTOR_SORT_ORDERS:
            self.sort_order_combo.addItem(tr(f'common.sort_order.{sort_order}'), sort_order)
        self.sort_order_combo.setMinimumWidth(120)

        self.btn_apply_sort = QPushButton(tr('common.ok'))
        self.btn_apply_sort.clicked.connect(self.apply_sort_settings)
        self.apply_sort_settings_to_controls()

        self.btn_add = QPushButton(tr('actor.viewer.add'))
        self.btn_add.clicked.connect(self.handle_add_button)

        self.btn_reset_avfan = QPushButton(tr('actor.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('actor.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_reset_binghuo = QPushButton(tr('actor.viewer.reset_binghuo'))
        self.btn_reset_binghuo.clicked.connect(lambda: self.reset_selected_rows(BINGHUO_ACTOR_SOURCE))

        self.btn_reset_baomu = QPushButton(tr('actor.viewer.reset_baomu'))
        self.btn_reset_baomu.clicked.connect(lambda: self.reset_selected_rows(BAOMU_ACTOR_SOURCE))

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_prev_page = QPushButton(tr('video.category.page_prev'))
        self.btn_prev_page.clicked.connect(self.go_to_previous_page)
        self.btn_next_page = QPushButton(tr('video.category.page_next'))
        self.btn_next_page.clicked.connect(self.go_to_next_page)
        self.page_info_label = QLabel('')

        filter_layout.addWidget(QLabel(tr('common.filter_realtime')))
        filter_layout.addWidget(self.search_input)
        filter_layout.addWidget(QLabel(tr('common.sort_field_label')))
        filter_layout.addWidget(self.sort_field_combo)
        filter_layout.addWidget(QLabel(tr('common.sort_order_label')))
        filter_layout.addWidget(self.sort_order_combo)
        filter_layout.addWidget(self.btn_apply_sort)
        filter_layout.addStretch()

        action_layout.addWidget(QLabel(tr('detail.quick_filter_label')))
        action_layout.addWidget(self.detail_filter_combo)
        action_layout.addWidget(self.btn_apply_detail_filter)
        action_layout.addStretch()
        action_layout.addWidget(self.btn_add)
        action_layout.addWidget(self.btn_reset_avfan)
        action_layout.addWidget(self.btn_reset_javtxt)
        action_layout.addWidget(self.btn_reset_binghuo)
        action_layout.addWidget(self.btn_reset_baomu)
        action_layout.addWidget(self.page_info_label)
        action_layout.addWidget(self.btn_prev_page)
        action_layout.addWidget(self.btn_next_page)
        action_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(tr('actor.viewer.headers'))
        for index in range(self.table.columnCount()):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.Fixed)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(filter_layout)
        layout.addLayout(action_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self._apply_table_column_widths()
        self.set_async_busy_widgets(
            [
                self.search_input,
                self.detail_filter_combo,
                self.btn_apply_detail_filter,
                self.sort_field_combo,
                self.sort_order_combo,
                self.btn_apply_sort,
                self.btn_add,
                self.btn_reset_avfan,
                self.btn_reset_javtxt,
                self.btn_reset_binghuo,
                self.btn_reset_baomu,
                self.btn_prev_page,
                self.btn_next_page,
                self.btn_refresh,
                self.table,
            ]
        )
        self._update_page_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_table_column_widths()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_table_column_widths)

    def _apply_table_column_widths(self):
        viewport_width = max(self.table.viewport().width(), 980)
        actor_width = max(120, viewport_width // 7)
        birthday_width = 120
        age_width = 72
        detail_width = 104
        base_status_width = max(320, int(viewport_width * 0.3))
        base_action_width = max(
            188,
            viewport_width - actor_width - birthday_width - age_width - base_status_width - detail_width,
        )
        action_width = max(188, int(base_action_width * (2 / 3)))
        status_width = base_status_width + (base_action_width - action_width)

        self.table.setColumnWidth(ACTOR_COLUMN_NAME, actor_width)
        self.table.setColumnWidth(ACTOR_COLUMN_BIRTHDAY, birthday_width)
        self.table.setColumnWidth(ACTOR_COLUMN_AGE, age_width)
        self.table.setColumnWidth(ACTOR_COLUMN_STATUS, status_width)
        self.table.setColumnWidth(ACTOR_COLUMN_DETAIL, detail_width)
        self.table.setColumnWidth(ACTOR_COLUMN_ACTIONS, action_width)

    def load_data(self):
        if self.is_async_task_running():
            self.schedule_deferred_reload(0)
            return
        search_text = self.search_input.text().strip()
        sort_field = self.sort_settings.get('sort_field', DEFAULT_ACTOR_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_ACTOR_SORT_ORDER)
        self.start_async_task(
            lambda: self._list_actors_payload(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=self.page_size,
                offset=self.current_offset,
            ),
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
                row_data.get('birthday', ''),
                row_data.get('age', ''),
                row_data.get('enrichment_status', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (ACTOR_COLUMN_BIRTHDAY, ACTOR_COLUMN_AGE):
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            actor_name = row_data.get('name', '')
            self.table.setCellWidget(row_idx, ACTOR_COLUMN_DETAIL, self.build_detail_button(actor_name))
            self.table.setCellWidget(row_idx, ACTOR_COLUMN_ACTIONS, self.build_action_buttons(actor_name))
        if self.adding_actor:
            self.insert_add_row()

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

    def handle_add_button(self):
        if self.adding_actor:
            self.confirm_actor_add()
            return
        if self.editing_actor_name is not None:
            QMessageBox.information(self, tr('actor.viewer.editing_title'), tr('actor.viewer.editing_message'))
            return
        self.start_actor_add()

    def start_actor_add(self):
        self.adding_actor = True
        self.btn_add.setText(tr('actor.viewer.add_confirm'))
        self.insert_add_row()

    def insert_add_row(self):
        self.table.insertRow(0)
        for column in range(ACTOR_COLUMN_STATUS + 1):
            item = QTableWidgetItem('')
            if column in (ACTOR_COLUMN_BIRTHDAY, ACTOR_COLUMN_AGE):
                item.setTextAlignment(Qt.AlignCenter)
            if column in (ACTOR_COLUMN_NAME, ACTOR_COLUMN_BIRTHDAY, ACTOR_COLUMN_AGE):
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(0, column, item)
        self.table.setCellWidget(0, ACTOR_COLUMN_DETAIL, QWidget())
        self.table.setCellWidget(0, ACTOR_COLUMN_ACTIONS, QWidget())
        self.adding_row = 0
        self.table.setEditTriggers(
            QAbstractItemView.SelectedClicked
            | QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
        )
        item = self.table.item(0, ACTOR_COLUMN_NAME)
        if item is not None:
            self.table.setCurrentCell(0, ACTOR_COLUMN_NAME)
            self.table.editItem(item)

    def confirm_actor_add(self):
        if self.adding_row is None:
            return
        actor_name = self._item_text(self.adding_row, ACTOR_COLUMN_NAME)
        birthday = self._item_text(self.adding_row, ACTOR_COLUMN_BIRTHDAY)
        age = self._item_text(self.adding_row, ACTOR_COLUMN_AGE)
        if not actor_name:
            QMessageBox.warning(self, tr('common.prompt'), tr('actor.viewer.name_required'))
            return

        try:
            normalized_payload = self.actor_profile_update_service.normalize_payload(actor_name, birthday=birthday, age=age)
        except Exception as exc:
            QMessageBox.warning(self, tr('common.prompt'), str(exc))
            return

        normalized_name = normalized_payload.get('name', '')
        if self.actor_exists(normalized_name):
            QMessageBox.warning(
                self,
                tr('common.prompt'),
                tr('actor.viewer.add_duplicate', actor_name=normalized_name),
            )
            return

        self._set_item_text(self.adding_row, ACTOR_COLUMN_NAME, normalized_name)
        self._set_item_text(self.adding_row, ACTOR_COLUMN_BIRTHDAY, normalized_payload.get('birthday', ''))
        self._set_item_text(self.adding_row, ACTOR_COLUMN_AGE, normalized_payload.get('age', ''))

        self.start_async_task(
            lambda: self._run_actor_add_task(
                normalized_name,
                normalized_payload.get('birthday', ''),
                normalized_payload.get('age', ''),
            ),
            self._on_add_finished,
            tr('actor.viewer.add_failed'),
        )

    def _run_actor_add_task(self, actor_name, birthday='', age=''):
        self.backend_client.add_actor(
            actor_name,
            birthday=birthday,
            age=age,
        )
        return {
            'actor_name': actor_name,
            'row': self._build_added_actor_row(actor_name, birthday=birthday, age=age),
        }

    def _build_added_actor_row(self, actor_name, birthday='', age=''):
        normalized_birthday = str(birthday or '').strip()
        normalized_age = str(age or '').strip()
        return {
            'name': str(actor_name or '').strip(),
            'birthday': normalized_birthday,
            'raw_age': normalized_age,
            'age': normalized_age,
            'matched': False,
            'actor_id': '',
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'binghuo_enrichment_status': UNENRICHED_STATUS,
            'enrichment_status': build_library_enrichment_status_text(
                UNENRICHED_STATUS,
                UNENRICHED_STATUS,
                UNENRICHED_STATUS,
            ),
            'ladder_tier': '',
            'update_status': '',
        }

    def _actor_row_matches_current_search(self, row_data):
        search_text = self.search_input.text().strip().lower()
        if not search_text:
            return True
        haystack = ' '.join(
            str((row_data or {}).get(field, '') or '').strip().lower()
            for field in ('name', 'actor_id', 'birthday', 'age', 'enrichment_status')
        )
        return search_text in haystack

    def _upsert_actor_row_locally(self, row_data):
        target_name = str((row_data or {}).get('name', '') or '').strip()
        if not target_name:
            return False
        for index, current_row in enumerate(self.all_rows):
            if str((current_row or {}).get('name', '') or '').strip() == target_name:
                self.all_rows[index] = dict(row_data or {})
                return True
        if self._actor_row_matches_current_search(row_data):
            self.all_rows.append(dict(row_data or {}))
            return True
        return False

    def _sync_local_actor_add(self, result):
        self.clear_edit_state()
        row_data = dict((result or {}).get('row', {}) or {})
        actor_name = str((result or {}).get('actor_name', '') or row_data.get('name', '') or '').strip()
        is_visible = self._upsert_actor_row_locally(row_data)
        self.rebuild_visible_rows()
        if is_visible and actor_name:
            self.select_actor_row(actor_name)
        return actor_name

    def filter_data(self, text):
        self.clear_edit_state()
        self.current_offset = 0
        self.schedule_deferred_reload()

    def apply_sort_settings(self):
        if self.adding_actor:
            QMessageBox.information(self, tr('actor.viewer.adding_title'), tr('actor.viewer.adding_message'))
            return
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

        self.current_offset = 0
        self.load_data()

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
        if self.editing_actor_name is not None:
            self.reset_row_button_text(self.editing_actor_name)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.adding_actor = False
        self.adding_row = None
        self.btn_add.setText(tr('actor.viewer.add'))
        self.editing_actor_name = None
        self.editing_row = None
        self.editing_actor_original = None

    def handle_edit_button(self, actor_name):
        if self.adding_actor:
            QMessageBox.information(self, tr('actor.viewer.adding_title'), tr('actor.viewer.adding_message'))
            return
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
            'name': self._item_text(row, ACTOR_COLUMN_NAME),
            'birthday': self._item_text(row, ACTOR_COLUMN_BIRTHDAY),
            'age': self._item_text(row, ACTOR_COLUMN_AGE),
            'raw_birthday': self._row_data_value(actor_name, 'birthday'),
            'raw_age': self._row_data_value(actor_name, 'raw_age'),
        }
        self.set_actor_row_editable(row, True)
        self.table.setEditTriggers(
            QAbstractItemView.SelectedClicked
            | QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
        )
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText(tr('common.ok'))
        item = self.table.item(row, ACTOR_COLUMN_NAME)
        if item is not None:
            self.table.setCurrentCell(row, ACTOR_COLUMN_NAME)
            self.table.editItem(item)

    def confirm_actor_edit(self):
        if self.editing_actor_name is None or self.editing_row is None:
            return
        old_name = self.editing_actor_name
        original = dict(self.editing_actor_original or {})
        if not original:
            self.clear_edit_state()
            return

        new_name = self._item_text(self.editing_row, ACTOR_COLUMN_NAME)
        birthday = self._edited_value_or_original_raw(
            ACTOR_COLUMN_BIRTHDAY,
            original.get('birthday', ''),
            original.get('raw_birthday', ''),
        )
        age = self._edited_value_or_original_raw(
            ACTOR_COLUMN_AGE,
            original.get('age', ''),
            original.get('raw_age', ''),
        )
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

        self._set_item_text(self.editing_row, ACTOR_COLUMN_NAME, normalized_payload.get('name', ''))
        self._set_item_text(self.editing_row, ACTOR_COLUMN_BIRTHDAY, normalized_payload.get('birthday', ''))
        self._set_item_text(self.editing_row, ACTOR_COLUMN_AGE, normalized_payload.get('age', ''))
        self.set_actor_row_editable(self.editing_row, False)

        self.clear_edit_state()
        self.start_async_task(
            lambda: self._reload_actor_page_after(
                lambda: self.backend_client.rename_actor(
                    old_name,
                    normalized_payload.get('name', ''),
                    birthday=normalized_payload.get('birthday', ''),
                    age=normalized_payload.get('age', ''),
                ),
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

    def _on_add_finished(self, result):
        actor_name = self._sync_local_actor_add(result)
        QMessageBox.information(
            self,
            tr('actor.viewer.add_completed'),
            tr('actor.viewer.add_completed_message', actor_name=actor_name),
        )

    def reset_row_button_text(self, actor_name):
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText(tr('actor.viewer.edit'))

    def set_actor_row_editable(self, row, editable):
        for column in (ACTOR_COLUMN_NAME, ACTOR_COLUMN_BIRTHDAY, ACTOR_COLUMN_AGE):
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
        self._set_item_text(self.editing_row, ACTOR_COLUMN_NAME, values.get('name', ''))
        self._set_item_text(self.editing_row, ACTOR_COLUMN_BIRTHDAY, values.get('birthday', ''))
        self._set_item_text(self.editing_row, ACTOR_COLUMN_AGE, values.get('age', ''))

    def _item_text(self, row, column):
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ''

    def _set_item_text(self, row, column, value):
        item = self.table.item(row, column)
        if item is not None:
            item.setText(str(value or ''))

    def _row_data_value(self, actor_name, field_name):
        target_name = str(actor_name or '').strip()
        for row_data in self.rows:
            if str((row_data or {}).get('name', '') or '').strip() == target_name:
                return str((row_data or {}).get(field_name, '') or '').strip()
        for row_data in self.all_rows:
            if str((row_data or {}).get('name', '') or '').strip() == target_name:
                return str((row_data or {}).get(field_name, '') or '').strip()
        return ''

    def _edited_value_or_original_raw(self, column, original_display_value, original_raw_value):
        current_text = self._item_text(self.editing_row, column)
        if current_text == str(original_display_value or '').strip():
            return str(original_raw_value or '').strip()
        return current_text

    def find_row_by_actor_name(self, actor_name):
        target = str(actor_name or '').strip()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, ACTOR_COLUMN_NAME)
            if item and item.text().strip() == target:
                return row
        return -1

    def delete_actor(self, actor_name):
        if self.adding_actor:
            QMessageBox.information(self, tr('actor.viewer.adding_title'), tr('actor.viewer.adding_message'))
            return
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

        self.start_async_task(
            lambda: self._reload_actor_page_after(
                lambda: self.backend_client.delete_actor(actor_name),
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
        if self.adding_actor:
            QMessageBox.information(self, tr('actor.viewer.adding_title'), tr('actor.viewer.adding_message'))
            return
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
                **self._current_actor_page_loader(),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_actor_names(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        actor_names = []
        for row in selected_rows:
            item = self.table.item(row, ACTOR_COLUMN_NAME)
            if item and item.text().strip():
                actor_names.append(item.text().strip())
        return actor_names

    def current_selected_actor_name(self):
        actor_names = self.selected_actor_names()
        return actor_names[0] if actor_names else ''

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        payload = dict(result or {})
        self.all_rows = list(payload.get('actors', payload.get('rows', [])) or [])
        self.total_count = int(payload.get('total_count', len(self.all_rows)) or 0)
        self.current_offset = int(payload.get('offset', self.current_offset) or 0)
        self.page_size = int(payload.get('limit', self.page_size) or self.page_size)
        self.rebuild_visible_rows()
        current_page = self.current_page_number()
        total_pages = max((self.total_count + self.page_size - 1) // self.page_size, 1)
        self.page_info_label.setText(
            tr(
                'video.category.page_info',
                page=current_page,
                total_pages=total_pages,
                page_count=len(self.rows),
                total_count=self.total_count,
            )
        )
        self._update_page_controls()

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

    def actor_exists(self, actor_name):
        target_name = str(actor_name or '').strip()
        if not target_name:
            return False
        return any(
            str((row_data or {}).get('name', '') or '').strip() == target_name
            for row_data in self.all_rows
        )

    def _current_actor_page_loader(self):
        search_text = self.search_input.text().strip()
        return self._list_actors_payload(
            search_text,
            sort_field=self.sort_settings.get('sort_field', DEFAULT_ACTOR_SORT_FIELD),
            sort_order=self.sort_settings.get('sort_order', DEFAULT_ACTOR_SORT_ORDER),
            limit=self.page_size,
            offset=self.current_offset,
        )

    def _list_actors_payload(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        if hasattr(self.backend_client, 'list_actors_page'):
            return self.backend_client.list_actors_page(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        rows = self.backend_client.list_actors(search_text)
        return {
            'actors': list(rows or []),
            'total_count': len(rows or []),
            'limit': limit,
            'offset': 0,
        }

    def _reload_actor_page_after(self, operation, **payload):
        operation()
        return {
            **self._current_actor_page_loader(),
            **payload,
        }

    def current_page_number(self):
        return (self.current_offset // self.page_size) + 1 if self.page_size > 0 else 1

    def go_to_previous_page(self):
        if self.current_offset <= 0:
            return
        self.current_offset = max(self.current_offset - self.page_size, 0)
        self.load_data()

    def go_to_next_page(self):
        if self.current_offset + self.page_size >= self.total_count:
            return
        self.current_offset += self.page_size
        self.load_data()

    def _update_page_controls(self):
        has_previous = self.current_offset > 0
        has_next = (self.current_offset + self.page_size) < max(self.total_count, 0)
        self.btn_prev_page.setEnabled(has_previous and not self.is_async_task_running())
        self.btn_next_page.setEnabled(has_next and not self.is_async_task_running())
