from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.actor_detail_viewer import ActorDetailViewerWindow


class ActorViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('🎭 演员库')
        self.resize(860, 520)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('🔍 输入演员、生日或年龄筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        btn_refresh = QPushButton('🔄 刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['演员', '生日', '年龄', '匹配状态', '详情'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        self.table.setRowCount(0)

        try:
            self.rows = self.backend_client.list_actors()
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'读取演员库失败: {exc}')

    def render_rows(self, rows):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('name', ''),
                row_data.get('birthday', ''),
                row_data.get('age', ''),
                '已匹配' if row_data.get('matched') else '未匹配',
            )

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

            self.table.setCellWidget(row_idx, 4, self.build_detail_button(row_data.get('name', '')))

    def build_detail_button(self, actor_name):
        button = QPushButton('查看详情')
        button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_actor_detail(self, actor_name):
        if not actor_name:
            return
        viewer = ActorDetailViewerWindow(
            backend_client=self.backend_client,
            actor_name=actor_name,
            parent=self,
        )
        viewer.exec_()

    def filter_data(self, text):
        try:
            self.rows = self.backend_client.list_actors(text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选演员库失败: {exc}')

