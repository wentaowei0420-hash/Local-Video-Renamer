import subprocess
import sys
import time

from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
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

from app.backend.client import BackendClient
from app.core.project_paths import PROJECT_ROOT
from app.gui.actor_viewer import ActorViewerWindow
from app.gui.db_viewer import DatabaseViewerWindow
from app.gui.enrichment_dialog import EnrichmentDialog
from app.gui.path_library_viewer import PathLibraryWindow


class EnrichmentWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, backend_client, limit, show_browser, cooldown_before_search):
        super().__init__()
        self.backend_client = backend_client
        self.limit = limit
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search

    def run(self):
        try:
            result = self.backend_client.enrich_videos(
                self.limit,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class AutoLoginWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, backend_client):
        super().__init__()
        self.backend_client = backend_client

    def run(self):
        try:
            result = self.backend_client.auto_login()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class VidNormApp(QWidget):
    def __init__(self):
        super().__init__()
        self.pending_renames = []
        self.backend_process = None
        self.backend_client = BackendClient()
        self.enrichment_thread = None
        self.enrichment_worker = None
        self.enrichment_mode = None
        self.batch_enrichment_active = False
        self.batch_enrichment_config = None
        self.batch_enrichment_round = 0
        self.batch_timer = QTimer(self)
        self.batch_timer.setSingleShot(True)
        self.batch_timer.timeout.connect(self.run_next_batch_enrichment)
        self.login_thread = None
        self.login_worker = None

        self.ensure_backend_running()
        self.load_csv_data()
        self.init_ui()
        self.update_enrichment_controls()

    def ensure_backend_running(self):
        if self.is_backend_alive():
            return

        backend_script = PROJECT_ROOT / 'backend_server.py'
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
            QMessageBox.critical(self, 'CSV 加载失败', f'无法读取数据库文件：\n{str(exc)}')

    def init_ui(self):
        self.setWindowTitle('VidNorm - 基于 CSV 数据库的视频规范化工具')
        self.resize(1000, 650)
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText('请选择包含视频的本地文件夹...')
        self.path_input.setReadOnly(True)

        btn_browse = QPushButton('选择文件夹')
        btn_browse.clicked.connect(self.browse_folder)
        btn_path_library = QPushButton('路径库')
        btn_path_library.clicked.connect(self.show_path_library)

        top_layout.addWidget(QLabel('本地目录:'))
        top_layout.addWidget(self.path_input)
        top_layout.addWidget(btn_path_library)
        top_layout.addWidget(btn_browse)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['原文件名', 'CSV 匹配结果(规范化)', '匹配状态'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.status_label = QLabel('')

        bottom_layout = QHBoxLayout()
        self.btn_view_db = QPushButton('查看数据库')
        self.btn_view_db.clicked.connect(self.show_db_viewer)

        self.btn_view_actors = QPushButton('查看作者库')
        self.btn_view_actors.clicked.connect(self.show_actor_viewer)

        self.btn_scan = QPushButton('扫描并匹配 CSV')
        self.btn_scan.clicked.connect(self.scan_files)

        self.btn_write_db = QPushButton('写入数据库')
        self.btn_write_db.clicked.connect(self.write_to_db)
        self.btn_write_db.setEnabled(False)

        self.btn_auto_login = QPushButton('自动登录')
        self.btn_auto_login.clicked.connect(self.auto_login)

        self.btn_enrich = QPushButton('补全信息')
        self.btn_enrich.clicked.connect(self.enrich_video_info)

        self.btn_stop_enrich = QPushButton('停止补全')
        self.btn_stop_enrich.clicked.connect(self.stop_enrichment)
        self.btn_stop_enrich.setEnabled(False)

        self.btn_reset_browser_profile = QPushButton('重置网页登录')
        self.btn_reset_browser_profile.clicked.connect(self.reset_browser_profile)

        self.btn_execute = QPushButton('执行重命名')
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_execute.setEnabled(False)

        bottom_layout.addWidget(self.btn_view_db)
        bottom_layout.addWidget(self.btn_view_actors)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_scan)
        bottom_layout.addWidget(self.btn_write_db)
        bottom_layout.addWidget(self.btn_auto_login)
        bottom_layout.addWidget(self.btn_enrich)
        bottom_layout.addWidget(self.btn_stop_enrich)
        bottom_layout.addWidget(self.btn_reset_browser_profile)
        bottom_layout.addWidget(self.btn_execute)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.status_label)
        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, '选择文件夹')
        if folder_path:
            self.set_current_folder(folder_path)

    def set_current_folder(self, folder_path):
        self.path_input.setText(folder_path)
        self.table.setRowCount(0)
        self.pending_renames.clear()
        self.btn_execute.setEnabled(False)
        self.btn_write_db.setEnabled(False)

    def scan_files(self):
        folder_path = self.path_input.text()
        if not folder_path:
            QMessageBox.warning(self, '错误', '请先选择文件夹')
            return

        try:
            result = self.backend_client.scan_folder(folder_path)
            self.pending_renames = result.get('plans', [])
        except Exception as exc:
            QMessageBox.warning(self, '错误', str(exc))
            return

        self.table.setRowCount(0)
        has_files_to_rename = False

        for row, plan in enumerate(self.pending_renames):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plan.get('old_name', '')))
            self.table.setItem(row, 1, QTableWidgetItem(plan.get('new_name', '')))

            if plan.get('needs_rename'):
                status_item = QTableWidgetItem('待重命名')
                status_item.setForeground(Qt.blue)
                has_files_to_rename = True
            else:
                status_item = QTableWidgetItem('已规范')
                status_item.setForeground(Qt.darkGreen)

            self.table.setItem(row, 2, status_item)

        self.btn_execute.setEnabled(has_files_to_rename)
        self.btn_write_db.setEnabled(len(self.pending_renames) > 0)

        if has_files_to_rename:
            message = f'共识别到 {len(self.pending_renames)} 个视频，其中有待重命名视频。'
        else:
            message = f'共识别到 {len(self.pending_renames)} 个视频，全部符合规范。'
        QMessageBox.information(self, '扫描完成', message)

    def write_to_db(self):
        if not self.pending_renames:
            return

        try:
            result = self.backend_client.save_plans(self.pending_renames)
            success_count = result.get('success_count', 0)
            QMessageBox.information(
                self,
                '写入成功',
                f'成功将当前列表中的 {success_count} 个视频数据写入或更新至数据库。\n'
                f'同时识别并写入或更新 {result.get("actor_count", 0)} 个作者。\n'
                f'(已根据视频编号和作者名称自动覆盖去重)',
            )
        except Exception as exc:
            QMessageBox.critical(self, '错误', f'写入数据库失败：\n{str(exc)}')

    def execute_rename(self):
        try:
            response = self.backend_client.execute_renames(self.pending_renames)
        except Exception as exc:
            QMessageBox.critical(self, '错误', f'执行重命名失败：\n{str(exc)}')
            return

        results = response.get('results', [])
        success = response.get('success_count', 0)

        for row, result in enumerate(results):
            status_item = self.table.item(row, 2)
            if result.get('success'):
                status_item.setText(f"OK {result.get('message', '完成')}")
            else:
                status_item.setText(f"错误 {result.get('message', '失败')}")

        QMessageBox.information(self, '结果', f'成功重命名 {success} 个文件。')
        self.btn_execute.setEnabled(False)

    def auto_login(self):
        if self.login_thread is not None:
            QMessageBox.information(self, '登录进行中', '当前自动登录还没有结束。')
            return
        self.start_auto_login()

    def start_auto_login(self):
        self.btn_auto_login.setEnabled(False)
        self.status_label.setText('正在打开登录页面并自动填入账号密码，请手动输入图片验证码后点击登录。')

        self.login_thread = QThread(self)
        self.login_worker = AutoLoginWorker(self.backend_client)
        self.login_worker.moveToThread(self.login_thread)
        self.login_thread.started.connect(self.login_worker.run)
        self.login_worker.finished.connect(self.on_auto_login_finished)
        self.login_worker.failed.connect(self.on_auto_login_failed)
        self.login_worker.finished.connect(self.login_thread.quit)
        self.login_worker.failed.connect(self.login_thread.quit)
        self.login_thread.finished.connect(self.cleanup_auto_login_thread)
        self.login_thread.start()

    def enrich_video_info(self):
        if self.enrichment_thread is not None or self.batch_enrichment_active:
            QMessageBox.information(self, '补全进行中', '当前补全任务还没有结束。')
            return

        dialog = EnrichmentDialog(self)
        if not dialog.exec_():
            return

        values = dialog.values()
        if dialog.action_mode == 'batch':
            self.start_batch_enrichment(values)
            return

        self.start_enrichment(
            values['limit'],
            values['show_browser'],
            values['cooldown_before_search'],
            mode='single',
        )

    def start_enrichment(self, limit, show_browser, cooldown_before_search, mode='single'):
        self.enrichment_mode = mode
        if mode == 'batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(f'分批补全第 {self.batch_enrichment_round} 批正在进行中，界面可继续操作。')
        else:
            self.status_label.setText('补全任务进行中，界面可继续操作。')
        self.update_enrichment_controls()

        self.enrichment_thread = QThread(self)
        self.enrichment_worker = EnrichmentWorker(
            self.backend_client,
            limit,
            show_browser,
            cooldown_before_search,
        )
        self.enrichment_worker.moveToThread(self.enrichment_thread)
        self.enrichment_thread.started.connect(self.enrichment_worker.run)
        self.enrichment_worker.finished.connect(self.on_enrichment_finished)
        self.enrichment_worker.failed.connect(self.on_enrichment_failed)
        self.enrichment_worker.finished.connect(self.enrichment_thread.quit)
        self.enrichment_worker.failed.connect(self.enrichment_thread.quit)
        self.enrichment_thread.finished.connect(self.cleanup_enrichment_thread)
        self.enrichment_thread.start()

    def start_batch_enrichment(self, values):
        self.batch_enrichment_active = True
        self.batch_enrichment_config = {
            'limit': values['batch_limit'],
            'interval_minutes': values['batch_interval_minutes'],
            'show_browser': values['show_browser'],
            'cooldown_before_search': values['cooldown_before_search'],
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            f"分批补全已启动：每 {values['batch_interval_minutes']} 分钟补全 {values['batch_limit']} 个视频。"
        )
        self.update_enrichment_controls()
        self.run_next_batch_enrichment()

    def run_next_batch_enrichment(self):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return
        if self.enrichment_thread is not None:
            return

        self.start_enrichment(
            self.batch_enrichment_config['limit'],
            self.batch_enrichment_config['show_browser'],
            self.batch_enrichment_config['cooldown_before_search'],
            mode='batch',
        )

    def schedule_next_batch_enrichment(self):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return

        interval_minutes = max(1, int(self.batch_enrichment_config['interval_minutes']))
        self.batch_timer.start(interval_minutes * 60 * 1000)
        self.status_label.setText(
            f'分批补全第 {self.batch_enrichment_round} 批已完成，将在 {interval_minutes} 分钟后开始下一批。'
        )
        self.update_enrichment_controls()

    def stop_batch_enrichment(self, message='已停止分批补全计划。'):
        self.batch_timer.stop()
        self.batch_enrichment_active = False
        self.batch_enrichment_config = None
        self.update_enrichment_controls()
        self.status_label.setText(message)

    def update_enrichment_controls(self):
        enrichment_running = self.enrichment_thread is not None
        self.btn_enrich.setEnabled(not enrichment_running and not self.batch_enrichment_active)
        self.btn_stop_enrich.setEnabled(enrichment_running or self.batch_enrichment_active)

    def stop_enrichment(self):
        if self.enrichment_thread is None:
            if self.batch_enrichment_active:
                self.stop_batch_enrichment('已停止分批补全计划。')
            return

        self.btn_stop_enrich.setEnabled(False)
        if self.batch_enrichment_active:
            self.batch_timer.stop()
            self.batch_enrichment_active = False
            self.batch_enrichment_config = None
        self.status_label.setText('已请求停止补全，当前视频处理完后会停止。')
        try:
            result = self.backend_client.cancel_enrichment()
            self.status_label.setText(result.get('message', '已请求停止补全。'))
        except Exception as exc:
            self.update_enrichment_controls()
            self.status_label.setText('停止补全请求失败。')
            QMessageBox.critical(self, '停止失败', str(exc))

    def on_auto_login_finished(self, result):
        QMessageBox.information(
            self,
            '自动登录完成',
            result.get('message', '已完成自动登录。'),
        )

    def on_auto_login_failed(self, error_message):
        QMessageBox.critical(self, '自动登录失败', error_message)

    def on_enrichment_finished(self, result):
        mode = self.enrichment_mode
        summary = (
            f"本次处理 {result.get('processed_count', 0)} 个视频。\n"
            f"成功: {result.get('success_count', 0)} 个\n"
            f"失败: {result.get('failed_count', 0)} 个\n"
            f"剩余未补全: {result.get('remaining_count', 0)} 个"
        )

        if mode == 'batch':
            if not self.batch_enrichment_active:
                self.status_label.setText('已停止分批补全计划。')
                QMessageBox.information(self, '分批补全已停止', summary)
                return

            if result.get('processed_count', 0) == 0 or result.get('remaining_count', 0) <= 0:
                self.stop_batch_enrichment('分批补全已完成，当前没有待补全视频。')
                QMessageBox.information(self, '分批补全完成', summary)
                return

            self.schedule_next_batch_enrichment()
            return

        title = '补全已停止' if result.get('stopped') else '补全完成'
        QMessageBox.information(self, title, summary)
        self.status_label.setText('')

    def on_enrichment_failed(self, error_message):
        mode = self.enrichment_mode
        if mode == 'batch':
            self.stop_batch_enrichment('分批补全失败，计划已停止。')
            QMessageBox.critical(self, '分批补全失败', error_message)
            return

        self.status_label.setText('')
        QMessageBox.critical(self, '补全失败', error_message)

    def cleanup_auto_login_thread(self):
        self.btn_auto_login.setEnabled(True)
        self.status_label.setText('')
        if self.login_worker is not None:
            self.login_worker.deleteLater()
        if self.login_thread is not None:
            self.login_thread.deleteLater()
        self.login_worker = None
        self.login_thread = None

    def cleanup_enrichment_thread(self):
        if self.enrichment_worker is not None:
            self.enrichment_worker.deleteLater()
        if self.enrichment_thread is not None:
            self.enrichment_thread.deleteLater()
        self.enrichment_worker = None
        self.enrichment_thread = None
        self.enrichment_mode = None
        self.update_enrichment_controls()

    def reset_browser_profile(self):
        answer = QMessageBox.question(
            self,
            '重置网页登录状态',
            '这会清除补全信息使用的专用浏览器登录状态、Cookie 和验证记录。\n'
            '不会影响视频数据库，也不会影响你的日常 Chrome。\n\n'
            '请先关闭补全时弹出的浏览器窗口，然后继续。是否重置？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.btn_reset_browser_profile.setEnabled(False)
        try:
            result = self.backend_client.reset_browser_profile()
            QMessageBox.information(
                self,
                '重置完成',
                f"{result.get('message', '已重置网页登录状态。')}\n\n"
                f"目录: {result.get('profile_dir', '')}",
            )
        except Exception as exc:
            QMessageBox.critical(self, '重置失败', str(exc))
        finally:
            self.btn_reset_browser_profile.setEnabled(True)

    def show_db_viewer(self):
        viewer = DatabaseViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_actor_viewer(self):
        viewer = ActorViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_path_library(self):
        viewer = PathLibraryWindow(backend_client=self.backend_client, parent=self)
        if viewer.exec_() and viewer.selected_path:
            self.set_current_folder(viewer.selected_path)

    def closeEvent(self, event):
        if self.enrichment_thread and self.enrichment_thread.isRunning():
            QMessageBox.information(self, '补全进行中', '请等待补全任务结束后再关闭窗口。')
            event.ignore()
            return
        if self.batch_enrichment_active or self.batch_timer.isActive():
            QMessageBox.information(self, '分批补全进行中', '请先停止分批补全计划，再关闭窗口。')
            event.ignore()
            return
        if self.login_thread and self.login_thread.isRunning():
            QMessageBox.information(self, '登录进行中', '请等待自动登录结束后再关闭窗口。')
            event.ignore()
            return
        if self.backend_process and self.backend_process.poll() is None:
            self.backend_process.terminate()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = VidNormApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
