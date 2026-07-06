from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
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

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.ladder_selected_panel import MedalEditDialog


class MasterpieceDetailWindow(QDialog):
    _DETAIL_FIELDS = (
        ('编号', 'code'),
        ('标题', 'title'),
        ('演员', 'author'),
        ('时长', 'duration'),
        ('大小(GB)', 'size'),
        ('存放位置', 'storage_location'),
        ('AVFan ID', 'avfan_movie_id'),
        ('JAVTXT ID', 'javtxt_movie_id'),
        ('JAVTXT 链接', 'javtxt_url'),
        ('JAVTXT 标题', 'javtxt_title'),
        ('JAVTXT 演员', 'javtxt_actors'),
        ('JAVTXT 标签', 'javtxt_tags'),
        ('视频分类', 'video_category'),
        ('发行日期', 'release_date'),
        ('制作商', 'maker'),
        ('发行商', 'publisher'),
        ('AVFan 补全状态', 'avfan_enrichment_status'),
        ('JAVTXT 补全状态', 'javtxt_enrichment_status'),
        ('补充任务状态', 'supplement_enrichment_status'),
        ('补充任务错误', 'supplement_enrichment_error'),
        ('补充任务时间', 'supplement_enriched_at'),
    )

    def __init__(self, backend_client, code, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.code = str(code or '').strip()
        self.setWindowTitle(f'视频详情 - {self.code}')
        self.resize(860, 620)
        self._init_ui()
        self.load_detail()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.summary_label = QLabel('')
        layout.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['字段', '内容'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def load_detail(self):
        detail = dict(self.backend_client.get_video_detail(self.code) or {})
        self.summary_label.setText(f'编号: {detail.get("code", "")} | 标题: {detail.get("title", "")}')
        self.table.setRowCount(0)
        for row_index, (label_text, field_name) in enumerate(self._DETAIL_FIELDS):
            self.table.insertRow(row_index)
            name_item = QTableWidgetItem(label_text)
            value_item = QTableWidgetItem(str(detail.get(field_name, '') or ''))
            name_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, value_item)


class MasterpieceWindow(QDialog, AsyncTaskHostMixin):
    _MEDAL_STYLES = {
        'border': '#b96a3b',
        'background': '#f6d8c3',
        'text': '#7a3513',
    }

    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.setWindowTitle('名作堂')
        self.resize(980, 640)
        self._init_ui()
        self.load_entries()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('视频编号'))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText('输入视频编号，例如 PFSA-001')
        self.code_input.returnPressed.connect(self.handle_add_entry)
        toolbar.addWidget(self.code_input, 1)

        self.btn_add = QPushButton('添加')
        self.btn_add.clicked.connect(self.handle_add_entry)
        toolbar.addWidget(self.btn_add)

        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_entries)
        toolbar.addWidget(self.btn_refresh)

        self.summary_label = QLabel('共 0 条')

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['编号', '标题', '演员', '勋章', '操作', '详情'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        layout.addLayout(toolbar)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

        self.set_async_busy_widgets([self.code_input, self.btn_add, self.btn_refresh, self.table])

    def load_entries(self):
        self.start_async_task(
            lambda: self.backend_client.list_masterpiece_entries(),
            self._on_entries_loaded,
            '读取名作堂失败',
        )

    def handle_add_entry(self):
        code = str(self.code_input.text() or '').strip()
        if not code:
            QMessageBox.warning(self, '缺少编号', '请先输入要加入名作堂的视频编号。')
            return

        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.add_masterpiece_entry(code),
                self.backend_client.list_masterpiece_entries,
            ),
            self._on_rows_reloaded_after_add,
            '添加名作堂失败',
        )

    def _on_rows_reloaded_after_add(self, payload):
        self.code_input.clear()
        self.code_input.setFocus()
        self._on_entries_loaded(payload)

    def _on_entries_loaded(self, payload):
        rows = payload
        if isinstance(payload, dict):
            rows = payload.get('rows', [])
        self.rows = [dict(row or {}) for row in (rows or [])]
        self._render_rows()

    def _render_rows(self):
        self.table.setRowCount(0)
        for row_index, row in enumerate(self.rows):
            code = str((row or {}).get('code', '') or '').strip()
            title = str((row or {}).get('title', '') or '').strip()
            author = str((row or {}).get('author', '') or '').strip()
            medal_text = str((row or {}).get('medal', '') or '').strip()
            medals = list((row or {}).get('medals', []) or [])

            self.table.insertRow(row_index)
            self.table.setItem(row_index, 0, QTableWidgetItem(code))
            self.table.setItem(row_index, 1, QTableWidgetItem(title))
            self.table.setItem(row_index, 2, QTableWidgetItem(author))
            self.table.setCellWidget(row_index, 3, self._build_medal_widget(medals))
            self.table.setCellWidget(row_index, 4, self._build_medal_button(code, medal_text))
            self.table.setCellWidget(row_index, 5, self._build_detail_button(code))

        self.summary_label.setText(f'共 {len(self.rows)} 条')
        self.table.resizeRowsToContents()

    def _build_medal_widget(self, medals):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setMargin(4)
        label.setText(self._build_medal_html(medals))
        return label

    def _build_medal_button(self, code, medal_text):
        button = QPushButton('编辑勋章' if medal_text else '添加勋章')
        button.clicked.connect(lambda _checked=False, target_code=code, target_medal=medal_text: self.edit_medal(target_code, target_medal))
        return button

    def _build_detail_button(self, code):
        button = QPushButton('详情')
        button.clicked.connect(lambda _checked=False, target_code=code: self.show_detail(target_code))
        return button

    def _build_medal_html(self, medals):
        if not medals:
            return '<span style="color:#888888;">暂无勋章</span>'

        palette = dict(self._MEDAL_STYLES)
        chips = []
        for medal in medals:
            chips.append(
                (
                    '<span style="display:inline-block; margin:0 6px 6px 0; '
                    f'padding:3px 10px; border:1px solid {palette["border"]}; border-radius:10px; '
                    f'background-color:{palette["background"]}; color:{palette["text"]};">'
                    f'{escape(str(medal or ""))}'
                    '</span>'
                )
            )
        return ''.join(chips)

    def edit_medal(self, code, medal_text):
        dialog = MedalEditDialog(code, medal_text, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.update_masterpiece_entry_medal(code, dialog.medal_text()),
                self.backend_client.list_masterpiece_entries,
            ),
            self._on_entries_loaded,
            '保存勋章失败',
        )

    def show_detail(self, code):
        dialog = MasterpieceDetailWindow(self.backend_client, code, self)
        dialog.exec_()

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
