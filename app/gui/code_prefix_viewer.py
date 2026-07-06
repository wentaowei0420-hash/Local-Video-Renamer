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
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_library_settings import (
    load_code_prefix_library_settings,
    save_code_prefix_library_settings,
)
from app.gui.data_center_analysis_viewer import _build_refresh_client
from app.gui.code_prefix_library_sorting import (
    CODE_PREFIX_SORT_FIELDS,
    CODE_PREFIX_SORT_ORDERS,
    DEFAULT_CODE_PREFIX_SORT_FIELD,
    DEFAULT_CODE_PREFIX_SORT_ORDER,
    normalize_code_prefix_sort_settings,
)
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.i18n import tr
from app.core.enrichment_sources import build_library_enrichment_status_text
from app.core.enrichment_status import UNENRICHED_STATUS
from app.services.detail import CODE_PREFIX_DETAIL_FILTER_OPTIONS, DETAIL_FILTER_ALL, filter_library_rows
from app.services.library.library_admin_service import normalize_code_prefix


DEFAULT_CODE_PREFIX_PAGE_SIZE = 200


class CodePrefixViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.all_rows = []
        self.rows = []
        self.total_count = 0
        self.current_offset = 0
        self.page_size = DEFAULT_CODE_PREFIX_PAGE_SIZE
        self.detail_quick_filter_key = DETAIL_FILTER_ALL
        self.adding_prefix = False
        self.adding_row = None
        self.editing_prefix = None
        self.editing_row = None
        self.action_buttons = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self.sort_settings = load_code_prefix_library_settings()
        self._init_async_task_host()
        self._init_deferred_reload(self._perform_deferred_load)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('code_prefix.viewer.title'))
        self.resize(1160, 560)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('code_prefix.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)
        self.search_input.setMinimumWidth(180)

        self.detail_filter_combo = QComboBox()
        for filter_key in CODE_PREFIX_DETAIL_FILTER_OPTIONS:
            self.detail_filter_combo.addItem(tr(f'detail.quick_filter.{filter_key}'), filter_key)
        initial_filter_index = self.detail_filter_combo.findData(self.detail_quick_filter_key)
        self.detail_filter_combo.setCurrentIndex(max(initial_filter_index, 0))
        self.detail_filter_combo.setMinimumWidth(180)
        self.btn_apply_detail_filter = QPushButton(tr('detail.apply_filter'))
        self.btn_apply_detail_filter.clicked.connect(self.apply_quick_filter_from_controls)

        self.sort_field_combo = QComboBox()
        for sort_field in CODE_PREFIX_SORT_FIELDS:
            self.sort_field_combo.addItem(tr(f'code_prefix.viewer.sort_field.{sort_field}'), sort_field)
        self.sort_field_combo.setMinimumWidth(120)

        self.sort_order_combo = QComboBox()
        for sort_order in CODE_PREFIX_SORT_ORDERS:
            self.sort_order_combo.addItem(tr(f'common.sort_order.{sort_order}'), sort_order)
        self.sort_order_combo.setMinimumWidth(120)

        self.btn_apply_sort = QPushButton(tr('common.ok'))
        self.btn_apply_sort.clicked.connect(self.apply_sort_settings)
        self.apply_sort_settings_to_controls()

        self.btn_add = QPushButton(tr('code_prefix.viewer.add'))
        self.btn_add.clicked.connect(self.handle_add_button)

        self.btn_reset_avfan = QPushButton(tr('code_prefix.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('code_prefix.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        self.btn_prev_page = QPushButton(tr('video.category.page_prev'))
        self.btn_prev_page.clicked.connect(self.go_to_previous_page)
        self.btn_next_page = QPushButton(tr('video.category.page_next'))
        self.btn_next_page.clicked.connect(self.go_to_next_page)
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        self.last_refresh_duration_label = QLabel(tr('common.duration', value=tr('common.empty')))
        self.page_info_label = QLabel('')

        filter_layout.addWidget(QLabel(tr('common.filter_realtime')))
        filter_layout.addWidget(self.search_input)
        filter_layout.addWidget(QLabel(tr('detail.quick_filter_label')))
        filter_layout.addWidget(self.detail_filter_combo)
        filter_layout.addWidget(self.btn_apply_detail_filter)
        filter_layout.addWidget(QLabel(tr('common.sort_field_label')))
        filter_layout.addWidget(self.sort_field_combo)
        filter_layout.addWidget(QLabel(tr('common.sort_order_label')))
        filter_layout.addWidget(self.sort_order_combo)
        filter_layout.addStretch()

        action_layout.addStretch()
        action_layout.addWidget(self.last_refreshed_label)
        action_layout.addWidget(self.last_refresh_duration_label)
        action_layout.addWidget(self.btn_apply_sort)
        action_layout.addWidget(self.btn_add)
        action_layout.addWidget(self.btn_reset_avfan)
        action_layout.addWidget(self.btn_reset_javtxt)
        action_layout.addWidget(self.page_info_label)
        action_layout.addWidget(self.btn_prev_page)
        action_layout.addWidget(self.btn_next_page)
        action_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(tr('code_prefix.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 8):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(filter_layout)
        layout.addLayout(action_layout)
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
                self.btn_add,
                self.btn_reset_avfan,
                self.btn_reset_javtxt,
                self.btn_prev_page,
                self.btn_next_page,
                self.btn_refresh,
                self.table,
            ]
        )
        self._update_page_controls()

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            self._deferred_force_refresh = self._deferred_force_refresh or bool(force_refresh)
            self.schedule_deferred_reload(0 if force_refresh else None)
            return
        search_text = self.search_input.text().strip()
        sort_field = self.sort_settings.get('sort_field', DEFAULT_CODE_PREFIX_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_CODE_PREFIX_SORT_ORDER)
        self.start_async_task(
            lambda: self._list_code_prefixes_payload(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=self.page_size,
                offset=self.current_offset,
                force_refresh=force_refresh,
            ),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _perform_deferred_load(self):
        force_refresh = self._deferred_force_refresh
        self._deferred_force_refresh = False
        self.load_data(force_refresh=force_refresh)

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('prefix', ''),
                row_data.get('video_count', 0),
                row_data.get('enrichment_status', ''),
                row_data.get('avfan_total_videos', 0),
                row_data.get('earliest_release_date', ''),
                row_data.get('latest_release_date', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            prefix = row_data.get('prefix', '')
            self.table.setCellWidget(row_idx, 6, self.build_detail_button(prefix))
            self.table.setCellWidget(row_idx, 7, self.build_action_buttons(prefix))
        if self.adding_prefix:
            self.insert_add_row()

    def build_detail_button(self, prefix):
        button = QPushButton(tr('code_prefix.viewer.detail'))
        button.clicked.connect(lambda _checked=False, value=prefix: self.show_prefix_detail(value))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, prefix):
        edit_button = QPushButton(tr('code_prefix.viewer.edit'))
        edit_button.clicked.connect(lambda _checked=False, value=prefix: self.handle_edit_button(value))
        delete_button = QPushButton(tr('code_prefix.viewer.delete'))
        delete_button.clicked.connect(lambda _checked=False, value=prefix: self.delete_prefix(value))
        self.action_buttons[prefix] = {'edit': edit_button, 'delete': delete_button}

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_prefix_detail(self, prefix):
        if not prefix:
            return
        viewer = CodePrefixDetailViewerWindow(self.backend_client, prefix, self)
        viewer.exec_()

    def handle_add_button(self):
        if self.adding_prefix:
            self.confirm_prefix_add()
            return
        if self.editing_prefix is not None:
            QMessageBox.information(self, tr('code_prefix.viewer.editing_title'), tr('code_prefix.viewer.editing_message'))
            return
        self.start_prefix_add()

    def start_prefix_add(self):
        self.adding_prefix = True
        self.btn_add.setText(tr('code_prefix.viewer.add_confirm'))
        self.insert_add_row()

    def insert_add_row(self):
        self.table.insertRow(0)
        for column in range(6):
            item = QTableWidgetItem('')
            item.setTextAlignment(Qt.AlignCenter)
            if column == 0:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(0, column, item)
        self.table.setCellWidget(0, 6, QWidget())
        self.table.setCellWidget(0, 7, QWidget())
        self.adding_row = 0
        self.table.setEditTriggers(
            QAbstractItemView.SelectedClicked
            | QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
        )
        item = self.table.item(0, 0)
        if item is not None:
            self.table.setCurrentCell(0, 0)
            self.table.editItem(item)

    def confirm_prefix_add(self):
        if self.adding_row is None:
            return
        item = self.table.item(self.adding_row, 0)
        if item is None:
            return

        raw_prefix = item.text().strip()
        if not raw_prefix:
            QMessageBox.warning(self, tr('common.prompt'), tr('code_prefix.viewer.prefix_required'))
            return

        try:
            normalized_prefix = normalize_code_prefix(raw_prefix)
        except Exception as exc:
            QMessageBox.warning(self, tr('common.prompt'), str(exc))
            return

        if self.prefix_exists(normalized_prefix):
            QMessageBox.warning(
                self,
                tr('common.prompt'),
                tr('code_prefix.viewer.add_duplicate', prefix=normalized_prefix),
            )
            return

        item.setText(normalized_prefix)
        self.start_async_task(
            lambda: self._run_prefix_add_task(normalized_prefix),
            self._on_add_finished,
            tr('code_prefix.viewer.add_failed'),
        )

    def _run_prefix_add_task(self, prefix):
        self.backend_client.add_code_prefix(prefix)
        return {
            'prefix': prefix,
            'row': self._build_added_prefix_row(prefix),
        }

    def _build_added_prefix_row(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        return {
            'prefix': normalized_prefix,
            'video_count': 0,
            'enrichment_status': build_library_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'update_status': '',
            'ladder_tier': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'earliest_release_date': '',
            'latest_release_date': '',
            'last_enriched_at': '',
        }

    def _prefix_row_matches_current_search(self, row_data):
        search_text = self.search_input.text().strip().upper()
        if not search_text:
            return True
        return search_text in str((row_data or {}).get('prefix', '') or '').strip().upper()

    def _upsert_prefix_row_locally(self, row_data):
        target_prefix = str((row_data or {}).get('prefix', '') or '').strip().upper()
        if not target_prefix:
            return False
        for index, current_row in enumerate(self.all_rows):
            if str((current_row or {}).get('prefix', '') or '').strip().upper() == target_prefix:
                self.all_rows[index] = dict(row_data or {})
                return True
        if self._prefix_row_matches_current_search(row_data):
            self.all_rows.append(dict(row_data or {}))
            return True
        return False

    def _sync_local_prefix_add(self, result):
        self.clear_edit_state()
        row_data = dict((result or {}).get('row', {}) or {})
        prefix = str((result or {}).get('prefix', '') or row_data.get('prefix', '') or '').strip().upper()
        is_visible = self._upsert_prefix_row_locally(row_data)
        self.rebuild_visible_rows()
        if is_visible and prefix:
            self.select_prefix_row(prefix)
        return prefix

    def filter_data(self, text):
        self.clear_edit_state()
        self.current_offset = 0
        self.schedule_deferred_reload()

    def apply_sort_settings(self):
        if self.adding_prefix:
            QMessageBox.information(
                self,
                tr('code_prefix.viewer.adding_title'),
                tr('code_prefix.viewer.adding_message'),
            )
            return
        if self.editing_prefix is not None:
            QMessageBox.information(
                self,
                tr('code_prefix.viewer.editing_title'),
                tr('code_prefix.viewer.editing_message'),
            )
            return
        self.sort_settings = normalize_code_prefix_sort_settings({
            'sort_field': self.sort_field_combo.currentData(),
            'sort_order': self.sort_order_combo.currentData(),
        })
        try:
            save_code_prefix_library_settings(self.sort_settings)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), tr('code_prefix.viewer.sort_save_failed', error=exc))
            return

        self.current_offset = 0
        self.load_data()

    def apply_quick_filter_from_controls(self):
        current_prefix = self.current_selected_prefix()
        target_prefix = self.apply_detail_quick_filter(self.detail_filter_combo.currentData(), current_prefix)
        if not target_prefix:
            self.table.clearSelection()

    def apply_sort_settings_to_controls(self):
        sort_field = self.sort_settings.get('sort_field', DEFAULT_CODE_PREFIX_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_CODE_PREFIX_SORT_ORDER)
        field_index = self.sort_field_combo.findData(sort_field)
        order_index = self.sort_order_combo.findData(sort_order)
        self.sort_field_combo.setCurrentIndex(max(field_index, 0))
        self.sort_order_combo.setCurrentIndex(max(order_index, 0))

    def rebuild_visible_rows(self):
        self.rows = list(filter_library_rows(self.all_rows, self.detail_quick_filter_key))
        self.render_rows(self.rows)

    def clear_edit_state(self):
        if self.editing_prefix is not None:
            self.reset_row_button_text(self.editing_prefix)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.adding_prefix = False
        self.adding_row = None
        self.btn_add.setText(tr('code_prefix.viewer.add'))
        self.editing_prefix = None
        self.editing_row = None

    def handle_edit_button(self, prefix):
        if self.adding_prefix:
            QMessageBox.information(self, tr('code_prefix.viewer.adding_title'), tr('code_prefix.viewer.adding_message'))
            return
        if self.editing_prefix is None:
            self.start_prefix_edit(prefix)
            return
        if self.editing_prefix != prefix:
            QMessageBox.information(self, tr('code_prefix.viewer.editing_title'), tr('code_prefix.viewer.editing_message'))
            return
        self.confirm_prefix_edit()

    def start_prefix_edit(self, prefix):
        row = self.find_row_by_prefix(prefix)
        if row < 0:
            QMessageBox.warning(self, tr('common.prompt'), tr('code_prefix.viewer.not_found', prefix=prefix))
            return
        self.editing_prefix = prefix
        self.editing_row = row
        self.set_prefix_cell_editable(row, True)
        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText(tr('common.ok'))
        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_prefix_edit(self):
        if self.editing_prefix is None or self.editing_row is None:
            return
        item = self.table.item(self.editing_row, 0)
        old_prefix = self.editing_prefix
        if item is None:
            self.clear_edit_state()
            return

        new_prefix = item.text().strip().upper()
        self.set_prefix_cell_editable(self.editing_row, False)
        if not new_prefix:
            item.setText(old_prefix)
            self.reset_row_button_text(old_prefix)
            self.clear_edit_state()
            QMessageBox.warning(self, tr('common.prompt'), tr('code_prefix.viewer.prefix_required'))
            return

        self.clear_edit_state()
        self.start_async_task(
            lambda: self._reload_prefix_page_after(
                lambda: self.backend_client.rename_code_prefix(old_prefix, new_prefix),
                old_prefix=old_prefix,
                new_prefix=new_prefix,
            ),
            self._on_rename_finished,
            tr('code_prefix.viewer.rename_failed'),
        )

    def _on_rename_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('code_prefix.viewer.rename_completed'),
            tr(
                'code_prefix.viewer.rename_completed_message',
                old_prefix=result.get('old_prefix', ''),
                new_prefix=result.get('new_prefix', ''),
            ),
        )

    def _on_add_finished(self, result):
        prefix = self._sync_local_prefix_add(result)
        QMessageBox.information(
            self,
            tr('code_prefix.viewer.add_completed'),
            tr('code_prefix.viewer.add_completed_message', prefix=prefix),
        )

    def reset_row_button_text(self, prefix):
        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText(tr('code_prefix.viewer.edit'))

    def set_prefix_cell_editable(self, row, editable):
        item = self.table.item(row, 0)
        if item is None:
            return
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def find_row_by_prefix(self, prefix):
        target = str(prefix or '').strip().upper()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip().upper() == target:
                return row
        return -1

    def delete_prefix(self, prefix):
        if self.adding_prefix:
            QMessageBox.information(self, tr('code_prefix.viewer.adding_title'), tr('code_prefix.viewer.adding_message'))
            return
        if self.editing_prefix is not None:
            QMessageBox.information(self, tr('code_prefix.viewer.editing_title'), tr('code_prefix.viewer.editing_message'))
            return
        answer = QMessageBox.question(
            self,
            tr('code_prefix.viewer.confirm_delete_title'),
            tr('code_prefix.viewer.confirm_delete_message', prefix=prefix),
        )
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: self._reload_prefix_page_after(
                lambda: self.backend_client.delete_code_prefix(prefix),
                prefix=prefix,
            ),
            self._on_delete_finished,
            tr('code_prefix.viewer.delete_failed'),
        )

    def _on_delete_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('code_prefix.viewer.delete_completed'),
            tr('code_prefix.viewer.delete_completed_message', prefix=result.get('prefix', '')),
        )

    def reset_selected_rows(self, source_key):
        if self.adding_prefix:
            QMessageBox.information(self, tr('code_prefix.viewer.adding_title'), tr('code_prefix.viewer.adding_message'))
            return
        prefixes = self.selected_prefixes()
        if not prefixes:
            QMessageBox.information(self, tr('common.no_selection'), tr('code_prefix.viewer.select_reset_rows'))
            return
        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            tr('code_prefix.viewer.confirm_reset_title'),
            tr('code_prefix.viewer.confirm_reset_message', count=len(prefixes), source_label=source_label),
        )
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_code_prefix_enrichments(prefixes, source_key=source_key),
                **self._current_prefix_page_loader(),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_prefixes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        prefixes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                prefixes.append(item.text().strip())
        return prefixes

    def current_selected_prefix(self):
        prefixes = self.selected_prefixes()
        return prefixes[0] if prefixes else ''

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        payload = dict(result or {})
        self.all_rows = list(payload.get('prefixes', payload.get('rows', [])) or [])
        self.total_count = int(payload.get('total_count', len(self.all_rows)) or 0)
        self.current_offset = int(payload.get('offset', self.current_offset) or 0)
        self.page_size = int(payload.get('limit', self.page_size) or self.page_size)
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        refresh_duration_text = str(payload.get('refresh_duration_text', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self.last_refresh_duration_label.setText(tr('common.duration', value=refresh_duration_text))
        self.rebuild_visible_rows()
        self.page_info_label.setText(
            tr(
                'video.category.page_info',
                page=self.current_page_number(),
                total_pages=max((self.total_count + self.page_size - 1) // self.page_size, 1),
                page_count=len(self.rows),
                total_count=self.total_count,
            )
        )
        self._update_page_controls()
        if self._startup_refresh_pending:
            self._startup_refresh_pending = False
            if bool(payload.get('cache_hit')):
                self.load_data(force_refresh=True)

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or tr('common.reset_source_fallback'))
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr('code_prefix.viewer.reset_completed_message', count=reset_count, source_label=source_label),
        )

    def apply_detail_quick_filter(self, filter_key, current_prefix=''):
        self.detail_quick_filter_key = str(filter_key or DETAIL_FILTER_ALL).strip() or DETAIL_FILTER_ALL
        self.rebuild_visible_rows()
        target_prefix = str(current_prefix or '').strip().upper()
        visible_prefixes = self.detail_navigation_keys()
        if target_prefix in visible_prefixes:
            self.select_prefix_row(target_prefix)
            return target_prefix
        if visible_prefixes:
            self.select_prefix_row(visible_prefixes[0])
            return visible_prefixes[0]
        return ''

    def current_detail_quick_filter(self):
        return self.detail_quick_filter_key

    def detail_navigation_keys(self):
        return [
            str((row or {}).get('prefix', '') or '').strip().upper()
            for row in self.rows
            if str((row or {}).get('prefix', '') or '').strip()
        ]

    def neighbor_detail_key(self, current_prefix, offset):
        prefixes = self.detail_navigation_keys()
        target_prefix = str(current_prefix or '').strip().upper()
        if target_prefix not in prefixes:
            return ''
        index = prefixes.index(target_prefix) + int(offset or 0)
        if index < 0 or index >= len(prefixes):
            return ''
        return prefixes[index]

    def select_prefix_row(self, prefix):
        row = self.find_row_by_prefix(prefix)
        if row >= 0:
            self.table.selectRow(row)

    def prefix_exists(self, prefix):
        target_prefix = str(prefix or '').strip().upper()
        if not target_prefix:
            return False
        return any(
            str((row_data or {}).get('prefix', '') or '').strip().upper() == target_prefix
            for row_data in self.all_rows
        )

    def _current_prefix_page_loader(self, force_refresh=False):
        search_text = self.search_input.text().strip()
        return self._list_code_prefixes_payload(
            search_text,
            sort_field=self.sort_settings.get('sort_field', DEFAULT_CODE_PREFIX_SORT_FIELD),
            sort_order=self.sort_settings.get('sort_order', DEFAULT_CODE_PREFIX_SORT_ORDER),
            limit=self.page_size,
            offset=self.current_offset,
            force_refresh=force_refresh,
        )

    def _reload_prefix_page_after(self, operation, **payload):
        operation()
        return {
            **self._current_prefix_page_loader(force_refresh=True),
            **payload,
        }

    def current_page_number(self):
        if self.page_size <= 0:
            return 1
        return self.current_offset // self.page_size + 1

    def go_to_previous_page(self):
        if self.current_offset <= 0 or self.is_async_task_running():
            return
        self.current_offset = max(self.current_offset - self.page_size, 0)
        self.load_data()

    def go_to_next_page(self):
        if self.is_async_task_running():
            return
        if self.current_offset + len(self.all_rows) >= self.total_count:
            return
        self.current_offset += self.page_size
        self.load_data()

    def _update_page_controls(self):
        busy = self.is_async_task_running()
        self.btn_prev_page.setEnabled((not busy) and self.current_offset > 0)
        self.btn_next_page.setEnabled((not busy) and (self.current_offset + len(self.all_rows) < self.total_count))

    def _list_code_prefixes_payload(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=None,
        offset=0,
        force_refresh=False,
    ):
        if hasattr(self.refresh_client, 'list_code_prefixes_snapshot'):
            return self.refresh_client.list_code_prefixes_snapshot(
                search_text=search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
                force_refresh=force_refresh,
            )
        if hasattr(self.backend_client, 'list_code_prefixes_page'):
            return self.backend_client.list_code_prefixes_page(
                search_text=search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        rows = self.backend_client.list_code_prefixes(search_text)
        return {
            'prefixes': rows,
            'total_count': len(rows),
            'limit': limit,
            'offset': 0,
        }
