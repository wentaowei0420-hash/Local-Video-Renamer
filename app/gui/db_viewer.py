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
)

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.core.enrichment_status import ENRICHED_STATUS
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.i18n import tr
from app.gui.video_category_update_events import video_category_update_event_bus
from app.gui.video_filter_dialog import VideoFilterDialog
from app.gui.video_filter_events import video_filter_event_bus
from app.gui.video_library_settings import load_video_library_settings, save_video_library_settings
from app.gui.video_library_sorting import (
    DEFAULT_VIDEO_SORT_FIELD,
    DEFAULT_VIDEO_SORT_ORDER,
    VIDEO_SORT_FIELDS,
    VIDEO_SORT_ORDERS,
    normalize_video_sort_settings,
    sort_video_rows,
)


VIDEO_TEXT_COLUMN_WIDTH = 150
VIDEO_COMPANY_COLUMN_WIDTH = 130
DEFAULT_VIDEO_PAGE_SIZE = 200


class DatabaseViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.total_count = 0
        self.current_offset = 0
        self.page_size = DEFAULT_VIDEO_PAGE_SIZE
        self.sort_settings = load_video_library_settings()
        self._init_async_task_host()
        self._init_deferred_reload(self.load_data, delay_ms=350)
        video_filter_event_bus.rules_saved.connect(self.on_filter_rules_saved)
        video_category_update_event_bus.categories_updated.connect(self.on_video_categories_updated)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('db.viewer.title'))
        self.resize(1440, 720)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('db.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)

        self.sort_field_combo = QComboBox()
        for sort_field in VIDEO_SORT_FIELDS:
            self.sort_field_combo.addItem(tr(f'db.viewer.sort_field.{sort_field}'), sort_field)

        self.sort_order_combo = QComboBox()
        for sort_order in VIDEO_SORT_ORDERS:
            self.sort_order_combo.addItem(tr(f'db.viewer.sort_order.{sort_order}'), sort_order)

        self.btn_apply_sort = QPushButton(tr('db.viewer.sort_apply'))
        self.btn_apply_sort.clicked.connect(self.apply_sort_settings)
        self.apply_sort_settings_to_controls()

        self.btn_reset_avfan = QPushButton(tr('db.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('db.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_filter_rules = QPushButton(tr('main.video_filter'))
        self.btn_filter_rules.clicked.connect(self.open_filter_dialog)

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_prev_page = QPushButton(tr('video.category.page_prev'))
        self.btn_prev_page.clicked.connect(self.go_to_previous_page)
        self.btn_next_page = QPushButton(tr('video.category.page_next'))
        self.btn_next_page.clicked.connect(self.go_to_next_page)

        top_layout.addWidget(QLabel(tr('common.filter_realtime')))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(QLabel(tr('db.viewer.sort_field_label')))
        top_layout.addWidget(self.sort_field_combo)
        top_layout.addWidget(QLabel(tr('db.viewer.sort_order_label')))
        top_layout.addWidget(self.sort_order_combo)
        top_layout.addWidget(self.btn_apply_sort)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_filter_rules)
        top_layout.addWidget(self.btn_prev_page)
        top_layout.addWidget(self.btn_next_page)
        top_layout.addWidget(self.btn_refresh)

        self.summary_label = QLabel(tr('db.viewer.summary', enriched_count=0, unenriched_count=0, total_count=0))
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.page_info_label = QLabel('')
        self.page_info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels(tr('db.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, VIDEO_TEXT_COLUMN_WIDTH)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, VIDEO_TEXT_COLUMN_WIDTH)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(11, QHeaderView.Fixed)
        self.table.setColumnWidth(11, VIDEO_COMPANY_COLUMN_WIDTH)
        self.table.horizontalHeader().setSectionResizeMode(12, QHeaderView.Fixed)
        self.table.setColumnWidth(12, VIDEO_COMPANY_COLUMN_WIDTH)
        self.table.horizontalHeader().setSectionResizeMode(13, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.page_info_label)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [
                self.search_input,
                self.sort_field_combo,
                self.sort_order_combo,
                self.btn_apply_sort,
                self.btn_reset_avfan,
                self.btn_reset_javtxt,
                self.btn_filter_rules,
                self.btn_prev_page,
                self.btn_next_page,
                self.btn_refresh,
                self.table,
            ]
        )
        self._update_page_controls()

    def load_data(self):
        if self.is_async_task_running():
            self.schedule_deferred_reload(0)
            return
        search_text = self.search_input.text().strip()
        sort_field = self.sort_settings.get('sort_field', DEFAULT_VIDEO_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_VIDEO_SORT_ORDER)
        self.start_async_task(
            lambda: self._list_videos_payload(
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
        self.table.setRowCount(0)
        fields = (
            'code',
            'title',
            'author',
            'javtxt_tags',
            'video_category',
            'duration',
            'size',
            'storage_location',
            'avfan_movie_id',
            'javtxt_movie_id',
            'release_date',
            'maker',
            'publisher',
            'enrichment_status',
        )
        centered_columns = {0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def refresh_summary(self):
        page_count = len(self.rows)
        enriched_count = sum(1 for row in self.rows if ENRICHED_STATUS in str(row.get('enrichment_status', '') or ''))
        unenriched_count = max(page_count - enriched_count, 0)
        self.summary_label.setText(
            tr(
                'db.viewer.summary',
                enriched_count=enriched_count,
                unenriched_count=unenriched_count,
                total_count=page_count,
            )
        )
        current_page = self.current_page_number()
        total_pages = max((self.total_count + self.page_size - 1) // self.page_size, 1)
        self.page_info_label.setText(
            tr(
                'video.category.page_info',
                page=current_page,
                total_pages=total_pages,
                page_count=page_count,
                total_count=self.total_count,
            )
        )
        self._update_page_controls()

    def filter_data(self, text):
        self.current_offset = 0
        self.schedule_deferred_reload()

    def apply_sort_settings(self):
        self.sort_settings = normalize_video_sort_settings({
            'sort_field': self.sort_field_combo.currentData(),
            'sort_order': self.sort_order_combo.currentData(),
        })
        try:
            save_video_library_settings(self.sort_settings)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), tr('db.viewer.sort_save_failed', error=exc))
            return

        self.current_offset = 0
        self.load_data()

    def open_filter_dialog(self):
        dialog = VideoFilterDialog(self)
        dialog.exec_()

    def on_filter_rules_saved(self):
        if not self.isVisible():
            return
        self.schedule_deferred_reload(0)

    def on_video_categories_updated(self):
        if not self.isVisible():
            return
        self.schedule_deferred_reload(0)

    def apply_sort_settings_to_controls(self):
        sort_field = self.sort_settings.get('sort_field', DEFAULT_VIDEO_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_VIDEO_SORT_ORDER)
        field_index = self.sort_field_combo.findData(sort_field)
        order_index = self.sort_order_combo.findData(sort_order)
        self.sort_field_combo.setCurrentIndex(max(field_index, 0))
        self.sort_order_combo.setCurrentIndex(max(order_index, 0))

    def sorted_rows(self, rows):
        return sort_video_rows(
            rows,
            self.sort_settings.get('sort_field', DEFAULT_VIDEO_SORT_FIELD),
            self.sort_settings.get('sort_order', DEFAULT_VIDEO_SORT_ORDER),
        )

    def reset_selected_rows(self, source_key):
        codes = self.selected_codes()
        if not codes:
            QMessageBox.information(self, tr('common.no_selection'), tr('db.viewer.select_reset_rows'))
            return

        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            tr('db.viewer.confirm_reset_title'),
            tr('db.viewer.confirm_reset_message', count=len(codes), source_label=source_label),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        sort_field = self.sort_settings.get('sort_field', DEFAULT_VIDEO_SORT_FIELD)
        sort_order = self.sort_settings.get('sort_order', DEFAULT_VIDEO_SORT_ORDER)
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_video_enrichments(codes, source_key=source_key),
                **self._list_videos_payload(
                    search_text,
                    sort_field=sort_field,
                    sort_order=sort_order,
                    limit=self.page_size,
                    offset=self.current_offset,
                ),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_codes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        codes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                codes.append(item.text().strip())
        return codes

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.rows = list(payload.get('videos', payload.get('rows', [])) or [])
        self.total_count = int(payload.get('total_count', len(self.rows)) or 0)
        self.current_offset = int(payload.get('offset', self.current_offset) or 0)
        self.page_size = int(payload.get('limit', self.page_size) or self.page_size)
        self.render_rows(self.rows)
        self.refresh_summary()

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

    def _list_videos_payload(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        if hasattr(self.backend_client, 'list_videos_page'):
            return self.backend_client.list_videos_page(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        rows = self.backend_client.list_videos(search_text)
        return {
            'videos': list(rows or []),
            'total_count': len(rows or []),
            'limit': limit,
            'offset': 0,
        }

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or tr('common.reset_source_fallback'))
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr('db.viewer.reset_completed_message', count=reset_count, source_label=source_label),
        )
