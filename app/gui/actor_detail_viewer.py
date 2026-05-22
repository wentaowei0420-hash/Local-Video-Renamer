from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ActorDetailViewerWindow(QDialog):
    def __init__(self, backend_client, actor_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.actor_name = actor_name
        self.detail = {}
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'演员详情 - {self.actor_name}')
        self.resize(760, 620)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        summary_group = QGroupBox('基础信息')
        summary_form = QFormLayout()
        self.name_label = QLabel('')
        self.age_label = QLabel('')
        self.birthday_label = QLabel('')
        self.video_count_label = QLabel('')
        for label in (
            self.name_label,
            self.age_label,
            self.birthday_label,
            self.video_count_label,
        ):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_form.addRow('姓名：', self.name_label)
        summary_form.addRow('年龄：', self.age_label)
        summary_form.addRow('出生日期：', self.birthday_label)
        summary_form.addRow('相关视频数：', self.video_count_label)
        summary_group.setLayout(summary_form)

        self.prefix_table = QTableWidget()
        self.prefix_table.setColumnCount(2)
        self.prefix_table.setHorizontalHeaderLabels(['番号', '视频数量'])
        self.prefix_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.prefix_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.prefix_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.prefix_table.setSelectionBehavior(QTableWidget.SelectRows)

        self.year_table = QTableWidget()
        self.year_table.setColumnCount(2)
        self.year_table.setHorizontalHeaderLabels(['视频年份', '视频数量'])
        self.year_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.year_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.year_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.year_table.setSelectionBehavior(QTableWidget.SelectRows)

        prefix_group = QGroupBox('番号分布')
        prefix_layout = QVBoxLayout()
        prefix_layout.addWidget(self.prefix_table)
        prefix_group.setLayout(prefix_layout)

        year_group = QGroupBox('视频年份分布')
        year_layout = QVBoxLayout()
        year_layout.addWidget(self.year_table)
        year_group.setLayout(year_layout)

        layout.addWidget(summary_group)
        layout.addWidget(prefix_group)
        layout.addWidget(year_group)
        self.setLayout(layout)

    def load_data(self):
        try:
            self.detail = self.backend_client.get_actor_detail(self.actor_name)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取演员详情失败：\n{str(exc)}')
            self.reject()
            return

        self.name_label.setText(self.detail.get('name', ''))
        self.age_label.setText(self.detail.get('age', '') or '暂缺')
        self.birthday_label.setText(self.detail.get('birthday', '') or '暂缺')
        self.video_count_label.setText(str(self.detail.get('video_count', 0)))
        self.render_distribution(
            self.prefix_table,
            self.detail.get('prefix_distribution', []),
            ('prefix', 'video_count'),
        )
        self.render_distribution(
            self.year_table,
            self.detail.get('year_distribution', []),
            ('year', 'video_count'),
        )

    def render_distribution(self, table, rows, fields):
        table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                value = row_data.get(field, '')
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

