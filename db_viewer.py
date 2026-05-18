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
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
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
        self.search_input.setPlaceholderText('🔍 输入视频编号、标题、演员或存放位置，即可实时快速筛选...')
        # 绑定文字变化事件，实现边打字边过滤的秒出效果
        self.search_input.textChanged.connect(self.filter_data)

        btn_refresh = QPushButton('🔄 刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_refresh)

        # --- 数据库表格主体 ---
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            '视频编号',
            '视频标题',
            '作者/演员',
            '时长',
            '大小(GB)',
            '存放位置',
            '视频ID',
            '发行日期',
            '制作商',
            '发行商',
            '补全状态',
        ])

        # 宽度自适应优化：标题列拉伸占满，其他列自适应文字宽度
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)

        self.table.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止在此处直接修改表格
        self.table.setSelectionBehavior(QTableWidget.SelectRows)  # 点击时选中整行

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        """从后端读取数据库台账并渲染到表格。"""
        self.table.setRowCount(0)

        try:
            self.rows = self.backend_client.list_videos()
            self.render_rows(self.rows)
        except Exception as e:
            print(f"读取数据库失败: {e}")

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
            'release_date',
            'maker',
            'publisher',
            'enrichment_status',
        )

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))

                # 让编号、作者、时长等列居中显示，更美观
                if col_idx in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10):
                    item.setTextAlignment(Qt.AlignCenter)

                self.table.setItem(row_idx, col_idx, item)

    def filter_data(self, text):
        """通过后端执行实时搜索。"""
        try:
            self.rows = self.backend_client.list_videos(text)
            self.render_rows(self.rows)
        except Exception as e:
            print(f"筛选数据库失败: {e}")
