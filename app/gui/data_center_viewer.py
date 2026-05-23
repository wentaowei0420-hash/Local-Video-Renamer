from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SummaryCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName('summaryCard')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.count_label = QLabel('已补全 0 / 0')
        self.detail_label = QLabel('待补全 0 | 失败 0 | 无结果 0')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.progress_bar)

    def set_summary(self, summary, show_terminal_details=True):
        total_count = int(summary.get('total_count', 0) or 0)
        enriched_count = int(summary.get('enriched_count', 0) or 0)
        pending_count = int(summary.get('pending_count', 0) or 0)
        failed_count = int(summary.get('failed_count', 0) or 0)
        no_search_count = int(summary.get('no_search_count', 0) or 0)
        progress_percent = float(summary.get('progress_percent', 0) or 0)

        self.title_label.setText(str(summary.get('label', '')))
        self.count_label.setText(f'已补全 {enriched_count} / {total_count}')
        if show_terminal_details:
            self.detail_label.setText(
                f'待补全 {pending_count} | 失败 {failed_count} | 无结果 {no_search_count}'
            )
        else:
            self.detail_label.setText(f'待补全 {pending_count}')
        self.progress_bar.setFormat(f'{progress_percent:.1f}%')
        self.progress_bar.setValue(int(progress_percent * 10))


class DataCenterWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.all_rows = []
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('数据中心')
        self.resize(1240, 760)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        summary_group = QGroupBox('补全进度')
        summary_layout = QGridLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)

        self.video_avfan_card = SummaryCard('视频库 / 天陨阁')
        self.video_javtxt_card = SummaryCard('视频库 / 辛聚谷')
        self.code_prefix_card = SummaryCard('番号库')
        self.actor_card = SummaryCard('作者库')

        summary_layout.addWidget(self.video_avfan_card, 0, 0)
        summary_layout.addWidget(self.video_javtxt_card, 0, 1)
        summary_layout.addWidget(self.code_prefix_card, 1, 0)
        summary_layout.addWidget(self.actor_card, 1, 1)

        table_group = QGroupBox('视频库')
        table_layout = QVBoxLayout(table_group)

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入视频编号、标题、演员、来源 ID 或存放位置，实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        btn_reset = QPushButton('选中重置')
        btn_reset.clicked.connect(self.reset_selected_rows)

        btn_refresh = QPushButton('刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_reset)
        top_layout.addWidget(btn_refresh)

        self.table_summary_label = QLabel('已补全数: 0 | 未补全数: 0 | 视频总数: 0')
        self.table_summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            '视频编号',
            '视频标题',
            '作者/演员',
            '时长',
            '大小(GB)',
            '存放位置',
            '天陨阁 ID',
            '辛聚谷 ID',
            '发行日期',
            '制作商',
            '发行商',
            '补全状态',
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        table_layout.addLayout(top_layout)
        table_layout.addWidget(self.table_summary_label)
        table_layout.addWidget(self.table)

        layout.addWidget(summary_group)
        layout.addWidget(table_group)
        self.setLayout(layout)

    def load_data(self):
        self.table.setRowCount(0)
        try:
            self.refresh_data_center_summary()
            self.all_rows = self.backend_client.list_videos()
            self.rows = list(self.all_rows)
            self.render_rows(self.rows)
            self.refresh_table_summary()
        except Exception as exc:
            print(f'读取数据中心失败: {exc}')

    def refresh_data_center_summary(self):
        summary = self.backend_client.get_data_center_summary() or {}
        video_summary = summary.get('video_library', {}).get('sources', {})
        self.video_avfan_card.set_summary(video_summary.get('avfan', {}), show_terminal_details=False)
        self.video_javtxt_card.set_summary(video_summary.get('javtxt', {}), show_terminal_details=False)
        self.code_prefix_card.set_summary(summary.get('code_prefix_library', {}))
        self.actor_card.set_summary(summary.get('actor_library', {}))

    def refresh_table_summary(self):
        summary = self._build_table_summary(self.rows)
        self.table_summary_label.setText(
            '已补全数: {enriched_count} | 未补全数: {unenriched_count} | 视频总数: {total_count}'.format(
                enriched_count=summary.get('enriched_count', 0),
                unenriched_count=summary.get('unenriched_count', 0),
                total_count=summary.get('total_count', 0),
            )
        )

    @staticmethod
    def _build_table_summary(rows):
        total_count = len(rows)
        enriched_count = sum(
            1
            for row in rows
            if '已补全' in str(row.get('enrichment_status', '') or '')
        )
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def render_rows(self, rows):
        self.table.setRowCount(0)
        fields = (
            'code',
            'title',
            'author',
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

        centered_columns = {0, 3, 4, 5, 6, 7, 8, 9, 10, 11}
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def filter_data(self, text):
        search_text = (text or '').strip()
        if not search_text:
            self.rows = list(self.all_rows)
            self.render_rows(self.rows)
            self.refresh_table_summary()
            return

        try:
            self.rows = self.backend_client.list_videos(search_text)
            self.render_rows(self.rows)
            self.refresh_table_summary()
        except Exception as exc:
            print(f'筛选视频库失败: {exc}')

    def reset_selected_rows(self):
        codes = self.selected_codes()
        if not codes:
            QMessageBox.information(self, '未选择', '请先选中要重置的视频行。')
            return

        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(codes)} 个视频补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        try:
            reset_count = self.backend_client.reset_video_enrichments(codes)
        except Exception as exc:
            QMessageBox.critical(self, '重置失败', f'重置视频补全状态失败：\n{exc}')
            return

        self.load_data()
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个视频的补全状态。')

    def selected_codes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        codes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                codes.append(item.text().strip())
        return codes
