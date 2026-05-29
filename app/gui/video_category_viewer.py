from PyQt5.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr
from app.services.video_category_service import VIDEO_CATEGORY_COLLECTION, VIDEO_CATEGORY_CO_STAR, VIDEO_CATEGORY_SINGLE


COLUMN_CODE = 0
COLUMN_TITLE = 1
COLUMN_SINGLE = 2
COLUMN_CO_STAR = 3
COLUMN_COLLECTION = 4
COLUMN_STAGE = 5
COLUMN_DETAIL = 6

CATEGORY_COLUMNS = {
    COLUMN_SINGLE: VIDEO_CATEGORY_SINGLE,
    COLUMN_CO_STAR: VIDEO_CATEGORY_CO_STAR,
    COLUMN_COLLECTION: VIDEO_CATEGORY_COLLECTION,
}

CATEGORY_ROLE = Qt.UserRole + 1
SELECTED_ROLE = Qt.UserRole + 2
ACTION_ENABLED_ROLE = Qt.UserRole + 3
CODE_ROLE = Qt.UserRole + 4
DETAIL_URL_ROLE = Qt.UserRole + 5

RADIO_COLUMN_WIDTH = 88
ACTION_COLUMN_WIDTH = 84


class VideoCategoryTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows = []
        self._visible_rows = []
        self._selected_category_by_code = {}
        self._page = 0
        self._page_size = 200

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._visible_rows)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return 7

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = self._visible_rows[index.row()]
        code = self._row_code(row)
        column = index.column()

        if role == Qt.DisplayRole:
            if column == COLUMN_CODE:
                return code
            if column == COLUMN_TITLE:
                return str(row.get('title', '') or '').strip()
            if column == COLUMN_STAGE:
                return tr('video.category.stage')
            if column == COLUMN_DETAIL:
                return tr('video.category.detail')
            return ''

        if role == Qt.TextAlignmentRole:
            if column == COLUMN_TITLE:
                return Qt.AlignVCenter | Qt.AlignLeft
            return Qt.AlignCenter

        if role == CATEGORY_ROLE:
            return CATEGORY_COLUMNS.get(column, '')

        if role == SELECTED_ROLE and column in CATEGORY_COLUMNS:
            return self.selected_category(code) == CATEGORY_COLUMNS[column]

        if role == ACTION_ENABLED_ROLE:
            if column == COLUMN_STAGE:
                return bool(self.selected_category(code))
            if column == COLUMN_DETAIL:
                return bool(str(row.get('javtxt_url', '') or '').strip())
            return True

        if role == CODE_ROLE:
            return code

        if role == DETAIL_URL_ROLE:
            return str(row.get('javtxt_url', '') or '').strip()

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            headers = tr('video.category.headers')
            if 0 <= section < len(headers):
                return headers[section]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def set_rows(self, rows):
        normalized_rows = list(rows or [])
        valid_codes = {
            self._row_code(row)
            for row in normalized_rows
            if self._row_code(row)
        }
        self.beginResetModel()
        self._all_rows = normalized_rows
        self._selected_category_by_code = {
            code: category
            for code, category in self._selected_category_by_code.items()
            if code in valid_codes
        }
        self._page = self._normalized_page(self._page)
        self._rebuild_visible_rows()
        self.endResetModel()

    def set_page(self, page):
        normalized_page = self._normalized_page(page)
        if normalized_page == self._page:
            return False
        self.beginResetModel()
        self._page = normalized_page
        self._rebuild_visible_rows()
        self.endResetModel()
        return True

    def next_page(self):
        return self.set_page(self._page + 1)

    def previous_page(self):
        return self.set_page(self._page - 1)

    def set_page_size(self, page_size):
        normalized_size = max(1, int(page_size or 1))
        if normalized_size == self._page_size:
            return False
        self.beginResetModel()
        self._page_size = normalized_size
        self._page = self._normalized_page(self._page)
        self._rebuild_visible_rows()
        self.endResetModel()
        return True

    def total_count(self):
        return len(self._all_rows)

    def page_count(self):
        return len(self._visible_rows)

    def total_pages(self):
        if not self._all_rows:
            return 0
        return (len(self._all_rows) + self._page_size - 1) // self._page_size

    def current_page_number(self):
        return self._page + 1 if self._all_rows else 0

    def can_go_previous(self):
        return self._page > 0

    def can_go_next(self):
        return self._page + 1 < self.total_pages()

    def selected_category(self, code):
        return str(self._selected_category_by_code.get(str(code or '').strip().upper(), '') or '').strip()

    def set_selected_category(self, code, category):
        normalized_code = str(code or '').strip().upper()
        normalized_category = str(category or '').strip()
        if not normalized_code or normalized_category not in CATEGORY_COLUMNS.values():
            return False
        if self._selected_category_by_code.get(normalized_code) == normalized_category:
            return False

        self._selected_category_by_code[normalized_code] = normalized_category
        row_index = self._find_visible_row(normalized_code)
        if row_index >= 0:
            self.dataChanged.emit(
                self.index(row_index, COLUMN_SINGLE),
                self.index(row_index, COLUMN_STAGE),
                [Qt.DisplayRole, SELECTED_ROLE, ACTION_ENABLED_ROLE],
            )
        return True

    def remove_code(self, code):
        normalized_code = str(code or '').strip().upper()
        if not normalized_code:
            return False

        filtered_rows = [
            row
            for row in self._all_rows
            if self._row_code(row) != normalized_code
        ]
        if len(filtered_rows) == len(self._all_rows):
            return False

        self.beginResetModel()
        self._all_rows = filtered_rows
        self._selected_category_by_code.pop(normalized_code, None)
        self._page = self._normalized_page(self._page)
        self._rebuild_visible_rows()
        self.endResetModel()
        return True

    def _rebuild_visible_rows(self):
        if not self._all_rows:
            self._visible_rows = []
            return
        start = self._page * self._page_size
        end = start + self._page_size
        self._visible_rows = self._all_rows[start:end]

    def _normalized_page(self, page):
        total_pages = self.total_pages()
        if total_pages <= 0:
            return 0
        return max(0, min(int(page or 0), total_pages - 1))

    def _find_visible_row(self, code):
        target = str(code or '').strip().upper()
        if not target:
            return -1
        for row_index, row in enumerate(self._visible_rows):
            if self._row_code(row) == target:
                return row_index
        return -1

    @staticmethod
    def _row_code(row):
        return str((row or {}).get('code', '') or '').strip().upper()


class CategorySelectionDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        self._paint_item_background(painter, option, index)

        button = QStyleOptionButton()
        button.rect = self._indicator_rect(option)
        button.state = QStyle.State_Enabled
        button.state |= QStyle.State_On if bool(index.data(SELECTED_ROLE)) else QStyle.State_Off

        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_RadioButton, button, painter, option.widget)

    def editorEvent(self, event, model, option, index):
        if (
            event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self._indicator_rect(option).contains(event.pos())
        ):
            return bool(model.set_selected_category(index.data(CODE_ROLE), index.data(CATEGORY_ROLE)))
        return False

    @staticmethod
    def _indicator_rect(option):
        indicator_size = 18
        x = option.rect.x() + (option.rect.width() - indicator_size) // 2
        y = option.rect.y() + (option.rect.height() - indicator_size) // 2
        return option.rect.adjusted(
            x - option.rect.x(),
            y - option.rect.y(),
            x - option.rect.x() + indicator_size - option.rect.width(),
            y - option.rect.y() + indicator_size - option.rect.height(),
        )

    @staticmethod
    def _paint_item_background(painter, option, index):
        item_option = QStyleOptionViewItem(option)
        delegate = QStyledItemDelegate()
        delegate.initStyleOption(item_option, index)
        item_option.text = ''
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, item_option, painter, option.widget)


class ActionButtonDelegate(QStyledItemDelegate):
    clicked = pyqtSignal(object)

    def paint(self, painter, option, index):
        CategorySelectionDelegate._paint_item_background(painter, option, index)

        button = QStyleOptionButton()
        button.rect = self._button_rect(option)
        button.text = str(index.data(Qt.DisplayRole) or '').strip()
        if bool(index.data(ACTION_ENABLED_ROLE)):
            button.state = QStyle.State_Enabled
        else:
            button.state = QStyle.State_None

        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_PushButton, button, painter, option.widget)

    def editorEvent(self, event, model, option, index):
        if not bool(index.data(ACTION_ENABLED_ROLE)):
            return False
        if (
            event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self._button_rect(option).contains(event.pos())
        ):
            self.clicked.emit(index)
            return True
        return False

    @staticmethod
    def _button_rect(option):
        return option.rect.adjusted(6, 4, -6, -4)


class VideoCategoryViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.staged_count = 0
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('video.category.title'))
        self.resize(1200, 640)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.summary_label = QLabel(tr('video.category.summary', count=0, staged_count=0))
        self.btn_sync = QPushButton(tr('video.category.sync'))
        self.btn_sync.clicked.connect(self.sync_staged_categories)
        self.btn_refresh = QPushButton(tr('video.category.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)
        top_layout.addWidget(self.summary_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_sync)
        top_layout.addWidget(self.btn_refresh)

        self.model = VideoCategoryTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(COLUMN_CODE, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COLUMN_TITLE, QHeaderView.Stretch)
        for index in (COLUMN_SINGLE, COLUMN_CO_STAR, COLUMN_COLLECTION):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.Fixed)
            self.table.setColumnWidth(index, RADIO_COLUMN_WIDTH)
        for index in (COLUMN_STAGE, COLUMN_DETAIL):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.Fixed)
            self.table.setColumnWidth(index, ACTION_COLUMN_WIDTH)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        category_delegate = CategorySelectionDelegate(self.table)
        self.table.setItemDelegateForColumn(COLUMN_SINGLE, category_delegate)
        self.table.setItemDelegateForColumn(COLUMN_CO_STAR, category_delegate)
        self.table.setItemDelegateForColumn(COLUMN_COLLECTION, category_delegate)

        self.stage_delegate = ActionButtonDelegate(self.table)
        self.stage_delegate.clicked.connect(self._on_stage_index_clicked)
        self.table.setItemDelegateForColumn(COLUMN_STAGE, self.stage_delegate)

        self.detail_delegate = ActionButtonDelegate(self.table)
        self.detail_delegate.clicked.connect(self._on_detail_index_clicked)
        self.table.setItemDelegateForColumn(COLUMN_DETAIL, self.detail_delegate)

        bottom_layout = QHBoxLayout()
        self.page_size_label = QLabel(tr('video.category.page_size'))
        self.page_size_combo = QComboBox()
        for page_size in (100, 200, 500):
            self.page_size_combo.addItem(str(page_size), page_size)
        self.page_size_combo.setCurrentIndex(1)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

        self.btn_prev_page = QPushButton(tr('video.category.page_prev'))
        self.btn_prev_page.clicked.connect(self._go_previous_page)
        self.page_label = QLabel()
        self.btn_next_page = QPushButton(tr('video.category.page_next'))
        self.btn_next_page.clicked.connect(self._go_next_page)

        bottom_layout.addWidget(self.page_size_label)
        bottom_layout.addWidget(self.page_size_combo)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_prev_page)
        bottom_layout.addWidget(self.page_label)
        bottom_layout.addWidget(self.btn_next_page)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        layout.addLayout(bottom_layout)
        self.set_async_busy_widgets([
            self.btn_refresh,
            self.btn_sync,
            self.page_size_combo,
            self.btn_prev_page,
            self.btn_next_page,
        ])
        self._update_summary_label()

    def load_data(self):
        self.start_async_task(
            lambda: self.backend_client.list_videos_requiring_manual_category(),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def sync_staged_categories(self):
        if self.staged_count <= 0:
            QMessageBox.information(self, tr('common.prompt'), tr('video.category.sync_empty_message'))
            return

        def task():
            sync_result = self.backend_client.sync_staged_video_categories()
            overview = self.backend_client.list_videos_requiring_manual_category()
            return {
                'sync_result': sync_result,
                'overview': overview,
            }

        self.start_async_task(task, self._on_sync_finished, tr('common.operation_failed'))

    def open_detail_url(self, javtxt_url):
        target_url = str(javtxt_url or '').strip()
        if not target_url:
            QMessageBox.information(self, tr('video.category.missing_link_title'), tr('video.category.missing_link_message'))
            return
        if not QDesktopServices.openUrl(QUrl(target_url)):
            QMessageBox.warning(self, tr('video.category.open_failed_title'), tr('video.category.open_failed_message', target_url=target_url))

    def _on_stage_index_clicked(self, index):
        if self.is_async_task_running():
            return
        code = str(index.data(CODE_ROLE) or '').strip().upper()
        selected_category = self.model.selected_category(code)
        if not selected_category:
            QMessageBox.information(self, tr('common.no_selection'), tr('video.category.select_first'))
            return

        self.start_async_task(
            lambda: {
                **self.backend_client.stage_video_category(code, selected_category),
                'code': code,
                'category': selected_category,
            },
            self._on_stage_category_finished,
            tr('common.save_failed'),
        )

    def _on_detail_index_clicked(self, index):
        self.open_detail_url(index.data(DETAIL_URL_ROLE))

    def _on_load_data_finished(self, result):
        self._apply_overview(result)

    def _on_stage_category_finished(self, result):
        code = str((result or {}).get('code', '') or '').strip().upper()
        if code:
            self.model.remove_code(code)
        self.staged_count = int((result or {}).get('staged_count', self.staged_count) or 0)
        self._update_summary_label()

    def _on_sync_finished(self, result):
        sync_result = dict((result or {}).get('sync_result', {}) or {})
        self._apply_overview((result or {}).get('overview', {}))
        QMessageBox.information(
            self,
            tr('video.category.sync_completed_title'),
            tr('video.category.sync_completed_message', count=int(sync_result.get('synced_count', 0) or 0)),
        )

    def _apply_overview(self, overview):
        overview = dict(overview or {})
        self.staged_count = int(overview.get('staged_count', 0) or 0)
        self.model.set_rows(overview.get('videos', []) or [])
        self._update_summary_label()

    def _go_previous_page(self):
        if self.model.previous_page():
            self._update_summary_label()

    def _go_next_page(self):
        if self.model.next_page():
            self._update_summary_label()

    def _on_page_size_changed(self):
        if self.model.set_page_size(self.page_size_combo.currentData()):
            self._update_summary_label()

    def _update_summary_label(self):
        self.summary_label.setText(
            tr(
                'video.category.summary',
                count=self.model.total_count(),
                staged_count=self.staged_count,
            )
        )
        self.page_label.setText(
            tr(
                'video.category.page_info',
                page=self.model.current_page_number(),
                total_pages=self.model.total_pages(),
                page_count=self.model.page_count(),
                total_count=self.model.total_count(),
            )
        )
        self._update_navigation_state()
        self._update_sync_button_state()
        self.table.viewport().update()

    def _update_navigation_state(self):
        busy = self.is_async_task_running()
        self.btn_prev_page.setEnabled((not busy) and self.model.can_go_previous())
        self.btn_next_page.setEnabled((not busy) and self.model.can_go_next())

    def _update_sync_button_state(self):
        self.btn_sync.setEnabled((not self.is_async_task_running()) and self.staged_count > 0)

    def _cleanup_async_task_thread(self):
        super()._cleanup_async_task_thread()
        self._update_navigation_state()
        self._update_sync_button_state()
        self.table.viewport().update()

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        if self.staged_count > 0:
            answer = QMessageBox.question(
                self,
                tr('video.category.close_pending_title'),
                tr('video.category.close_pending_message', count=self.staged_count),
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)
