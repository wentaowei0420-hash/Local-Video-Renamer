import sys
import subprocess
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
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

from backend_client import BackendClient
from db_viewer import DatabaseViewerWindow


class VidNormApp(QWidget):
    def __init__(self):
        super().__init__()
        self.pending_renames = []
        self.backend_process = None
        self.backend_client = BackendClient()

        self.ensure_backend_running()
        self.load_csv_data()
        self.init_ui()

    def ensure_backend_running(self):
        if self.is_backend_alive():
            return

        backend_script = Path(__file__).with_name('backend_server.py')
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.backend_process = subprocess.Popen(
            [sys.executable, str(backend_script)],
            cwd=str(backend_script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        deadline = time.time() + 5
        while time.time() < deadline:
            if self.is_backend_alive():
                return
            time.sleep(0.2)

        raise RuntimeError('后端服务启动超时')

    def is_backend_alive(self):
        try:
            self.backend_client.health()
            return True
        except Exception:
            return False

    def load_csv_data(self):
        try:
            result = self.backend_client.reload_database()
            print(f"成功加载 {result['count']} 条视频元数据")
        except Exception as exc:
            QMessageBox.critical(self, "CSV 加载失败", f"无法读取数据库文件：\n{str(exc)}")

    def init_ui(self):
        self.setWindowTitle('VidNorm - 基于 CSV 数据库的视频规范化工具')
        self.resize(1000, 650)
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择包含视频的本地文件夹...")
        self.path_input.setReadOnly(True)
        btn_browse = QPushButton('📁 选择文件夹')
        btn_browse.clicked.connect(self.browse_folder)
        top_layout.addWidget(QLabel("本地目录:"))
        top_layout.addWidget(self.path_input)
        top_layout.addWidget(btn_browse)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['原文件名', 'CSV 匹配结果 (规范化)', '匹配状态'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        bottom_layout = QHBoxLayout()

        # 👇 新增：查看数据库按钮 (它随时可用，独立于扫描流程)
        self.btn_view_db = QPushButton('📊 查看数据库')
        self.btn_view_db.clicked.connect(self.show_db_viewer)

        self.btn_scan = QPushButton('🔍 扫描并匹配 CSV')
        self.btn_scan.clicked.connect(self.scan_files)

        self.btn_write_db = QPushButton('💾 写入数据库')
        self.btn_write_db.clicked.connect(self.write_to_db)
        self.btn_write_db.setEnabled(False)

        self.btn_execute = QPushButton('🚀 执行重命名')
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_execute.setEnabled(False)

        bottom_layout.addWidget(self.btn_view_db)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_scan)
        bottom_layout.addWidget(self.btn_write_db)
        bottom_layout.addWidget(self.btn_execute)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder_path:
            self.path_input.setText(folder_path)
            self.table.setRowCount(0)
            self.pending_renames.clear()
            self.btn_execute.setEnabled(False)
            self.btn_write_db.setEnabled(False)

    def scan_files(self):
        folder_path = self.path_input.text()
        if not folder_path:
            QMessageBox.warning(self, "错误", "请先选择文件夹")
            return

        try:
            result = self.backend_client.scan_folder(folder_path)
            self.pending_renames = result.get('plans', [])
        except Exception as exc:
            QMessageBox.warning(self, "错误", str(exc))
            return

        self.table.setRowCount(0)
        has_files_to_rename = False

        for row, plan in enumerate(self.pending_renames):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plan.get('old_name', '')))
            self.table.setItem(row, 1, QTableWidgetItem(plan.get('new_name', '')))

            if plan.get('needs_rename'):
                status_item = QTableWidgetItem("待重命名")
                status_item.setForeground(Qt.blue)
                has_files_to_rename = True
            else:
                status_item = QTableWidgetItem("已规范")
                status_item.setForeground(Qt.darkGreen)

            self.table.setItem(row, 2, status_item)

        self.btn_execute.setEnabled(has_files_to_rename)
        self.btn_write_db.setEnabled(len(self.pending_renames) > 0)

        QMessageBox.information(
            self,
            "扫描完成",
            f"共识别到 {len(self.pending_renames)} 个视频，其中有待重命名视频。" if has_files_to_rename else f"共识别到 {len(self.pending_renames)} 个视频，全部符合规范！",
        )

    def write_to_db(self):
        if not self.pending_renames:
            return

        try:
            result = self.backend_client.save_plans(self.pending_renames)
            success_count = result.get('success_count', 0)
            QMessageBox.information(
                self,
                "写入成功",
                f"成功将当前列表中的 {success_count} 个视频数据写入/更新至数据库！\n(已根据视频编号自动覆盖去重)"
            )
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"写入数据库失败：\n{str(exc)}")

    def execute_rename(self):
        try:
            response = self.backend_client.execute_renames(self.pending_renames)
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"执行重命名失败：\n{str(exc)}")
            return

        results = response.get('results', [])
        success = response.get('success_count', 0)

        for row, result in enumerate(results):
            status_item = self.table.item(row, 2)
            if result.get('success'):
                status_item.setText(f"✅ {result.get('message', '完成')}")
            else:
                status_item.setText(f"❌ {result.get('message', '错误')}")

        QMessageBox.information(self, "结果", f"成功重命名 {success} 个文件。")
        self.btn_execute.setEnabled(False)

    # 👇 新增：弹出独立数据库查看器的方法
    def show_db_viewer(self):
        viewer = DatabaseViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()  # 弹出对话框

    def closeEvent(self, event):
        if self.backend_process and self.backend_process.poll() is None:
            self.backend_process.terminate()
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = VidNormApp()
    window.show()
    sys.exit(app.exec_())
