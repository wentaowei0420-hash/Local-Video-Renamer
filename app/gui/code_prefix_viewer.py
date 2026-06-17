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
from app.gui.code_prefix_library_sorting import (
    CODE_PREFIX_SORT_FIELDS,
    CODE_PREFIX_SORT_ORDERS,
    DEFAULT_CODE_PREFIX_SORT_FIELD,
    DEFAULT_CODE_PREFIX_SORT_ORDER,
    normalize_code_prefix_sort_settings,
    sort_code_prefix_rows,
)
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.i18n import tr
from app.services.detail_quick_filter_service import CODE_PREFIX_DETAIL_FILTER_OPTIONS, DETAIL_FILTER_ALL, filter_library_rows


class CodePrefixViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.all_rows = []
        self.rows = []
        self.detail_quick_filter_key = DETAIL_FILTER_ALL
        self.editing_prefix = None
        self.editing_row = None
        self.action_buttons = {}
        self.sort_settings = load_code_prefix_library_settings()
        self._init_async_task_host()
        self._init_deferred_reload(self.load_data)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('code_prefix.viewer.title'))
        self.resize(1160, 560)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('code_prefix.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)

        self.detail_filter_combo = QComboBox()
        for filter_key in CODE_PREFIX_DETAIL_FILTER_OPTIONS:
            self.detail_filter_combo.addItem(tr(f'detail.quick_filter.{filter_key}'), filter_key)
        initial_filter_index = self.detail_filter_combo.findData(self.detail_quick_filter_key)
        self.detail_filter_combo.setCurrentIndex(max(initial_filter_index, 0))
        self.btn_apply_detail_filter = QPushButton(tr('detail.apply_filter'))
        self.btn_apply_detail_filter.clicked.connect(self.apply_quick_filter_from_controls)

        self.sort_field_combo = QComboBox()
        for sort_field in CODE_PREFIX_SORT_FIELDS:
            self.sort_field_combo.addItem(tr(f'code_prefix.viewer.sort_field.{sort_field}'), sort_field)

        self.sort_order_combo = QComboBox()
        for sort_order in CODE_PREFIX_SORT_ORDERS:
            self.sort_order_combo.addItem(tr(f'common.sort_order.{sort_order}'), sort_order)

        self.btn_apply_sort = QPushButton(tr('common.ok'))
        self.btn_apply_sort.clicked.connect(self.apply_sort_settings)
        self.apply_sort_settings_to_controls()

        self.btn_reset_avfan = QPushButton(tr('code_prefix.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('code_prefix.viewer.reset_javtxt'))
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
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(tr('code_prefix.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 8):
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
            lambda: {'rows': self.backend_client.list_code_prefixes(search_text)},
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

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

    def filter_data(self, text):
        self.clear_edit_state()
        self.schedule_deferred_reload()

    def apply_sort_settings(self):
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

        self.rebuild_visible_rows()

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

    def sorted_rows(self, rows):
        return sort_code_prefix_rows(
            rows,
            self.sort_settings.get('sort_field', DEFAULT_CODE_PREFIX_SORT_FIELD),
            self.sort_settings.get('sort_order', DEFAULT_CODE_PREFIX_SORT_ORDER),
        )

    def rebuild_visible_rows(self):
        self.rows = self.sorted_rows(filter_library_rows(self.all_rows, self.detail_quick_filter_key))
        self.render_rows(self.rows)

    def clear_edit_state(self):
        self.editing_prefix = None
        self.editing_row = None

    def handle_edit_button(self, prefix):
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
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.rename_code_prefix(old_prefix, new_prefix),
                lambda: self.backend_client.list_code_prefixes(search_text),
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

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.delete_code_prefix(prefix),
                lambda: self.backend_client.list_code_prefixes(search_text),
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

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_code_prefix_enrichments(prefixes, source_key=source_key),
                'rows': self.backend_client.list_code_prefixes(search_text),
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
        self.all_rows = list((result or {}).get('rows', []) or [])
        self.rebuild_visible_rows()

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
