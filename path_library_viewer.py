from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class PathLibraryWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.selected_path = ''
        self.paths = []
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('📂 路径库')
        self.resize(900, 460)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        btn_add = QPushButton('➕ 添加')
        btn_add.clicked.connect(self.add_path)
        btn_delete = QPushButton('🗑 删除')
        btn_delete.clicked.connect(self.delete_selected_path)
        btn_use = QPushButton('✅ 使用选中路径')
        btn_use.clicked.connect(self.use_selected_path)
        btn_refresh = QPushButton('🔄 刷新')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('已保存路径:'))
        top_layout.addStretch()
        top_layout.addWidget(btn_add)
        top_layout.addWidget(btn_delete)
        top_layout.addWidget(btn_use)
        top_layout.addWidget(btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['ID', '路径', '状态', '创建时间'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self.use_selected_path)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        try:
            self.paths = self.backend_client.list_paths()
            self.render_rows(self.paths)
        except Exception as exc:
            QMessageBox.critical(self, '错误', f'读取路径库失败：\n{str(exc)}')

    def render_rows(self, paths):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(paths):
            self.table.insertRow(row_idx)

            values = (
                row_data.get('id', ''),
                row_data.get('path', ''),
                '可用' if row_data.get('exists') else '不存在',
                row_data.get('created_at', ''),
            )

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, '添加路径到路径库')
        if not folder_path:
            return

        try:
            self.backend_client.add_path(folder_path)
            self.load_data()
        except Exception as exc:
            QMessageBox.warning(self, '错误', f'添加路径失败：\n{str(exc)}')

    def delete_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, '提示', '请先选择要删除的路径')
            return

        path_id = self.table.item(row, 0).text()
        path_text = self.table.item(row, 1).text()
        confirmed = QMessageBox.question(
            self,
            '确认删除',
            f'确定从路径库删除这个路径吗？\n{path_text}',
        )
        if confirmed != QMessageBox.Yes:
            return

        try:
            self.backend_client.delete_path(int(path_id))
            self.load_data()
        except Exception as exc:
            QMessageBox.warning(self, '错误', f'删除路径失败：\n{str(exc)}')

    def use_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, '提示', '请先选择一个路径')
            return

        self.selected_path = self.table.item(row, 1).text()
        self.accept()

    def current_row(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return -1
        return selected_ranges[0].topRow()
