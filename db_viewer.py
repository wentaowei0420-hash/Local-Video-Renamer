import sqlite3
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QLabel,
    QPushButton,
)


class DatabaseViewerWindow(QDialog):
    def __init__(self, db_path='video_database.db', parent=None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('📊 已存档视频数据库台账')
        self.resize(900, 550)

        # 设置窗口模态（打开它时，主窗体会被锁定，防止数据冲突）
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        # --- 顶部工具栏：搜索框和刷新按钮 ---
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('🔍 输入视频编号、标题或演员，即可实时快速筛选...')
        # 绑定文字变化事件，实现边打字边过滤的秒出效果
        self.search_input.textChanged.connect(self.filter_data)

        btn_refresh = QPushButton('🔄 刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_refresh)

        # --- 数据库表格主体 ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['视频编号', '视频标题', '作者/演员', '时长', '大小(GB)'])

        # 宽度自适应优化：标题列拉伸占满，其他列自适应文字宽度
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.table.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止在此处直接修改表格
        self.table.setSelectionBehavior(QTableWidget.SelectRows)  # 点击时选中整行

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        """连接 SQLite 数据库并读取所有数据渲染到表格"""
        self.table.setRowCount(0)
        if not self.db_path.exists():
            return

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT code, title, author, duration, size FROM processed_videos')
                rows = cursor.fetchall()

                for row_idx, row_data in enumerate(rows):
                    self.table.insertRow(row_idx)
                    for col_idx, value in enumerate(row_data):
                        item = QTableWidgetItem(str(value if value is not None else ''))

                        # 让编号、作者、时长等列居中显示，更美观
                        if col_idx in (0, 2, 3, 4):
                            item.setTextAlignment(Qt.AlignCenter)

                        self.table.setItem(row_idx, col_idx, item)

            # 加载完数据后顺便应用一下当前的搜索框筛选状态
            self.filter_data(self.search_input.text())
        except Exception as e:
            print(f"读取数据库失败: {e}")

    def filter_data(self, text):
        """实现实时搜索的黑魔法功能"""
        text = text.lower().strip()
        for row in range(self.table.rowCount()):
            match = False
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            # 如果这行的所有列都不包含搜索关键词，就把这行隐藏掉
            self.table.setRowHidden(row, not match)