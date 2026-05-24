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
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.local_video_labels import (
    ENRICHMENT_REQUIRED_STATUS,
    IMPORT_REQUIRED_STATUS,
    NORMALIZED_STATUS,
    RENAME_REQUIRED_STATUS,
)
from app.core.project_paths import PROJECT_ROOT
from app.gui.actor_viewer import ActorViewerWindow
from app.gui.code_prefix_viewer import CodePrefixViewerWindow
from app.gui.data_center_viewer import DataCenterWindow
from app.gui.db_viewer import DatabaseViewerWindow
from app.gui.enrichment_dialog import EnrichmentDialog
from app.gui.path_library_viewer import PathLibraryWindow


class EnrichmentWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, backend_client, limit, show_browser, cooldown_before_search, target_type, source_key):
        super().__init__()
        self.backend_client = backend_client
        self.limit = limit
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.target_type = target_type
        self.source_key = source_key

    def run(self):
        try:
            result = self.backend_client.enrich_videos(
                self.limit,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                target_type=self.target_type,
                source_key=self.source_key,
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
        self.batch_countdown_timer = QTimer(self)
        self.batch_countdown_timer.setInterval(1000)
        self.batch_countdown_timer.timeout.connect(self.update_batch_countdown)
        self.batch_next_run_at = None
        self.enrichment_progress_timer = QTimer(self)
        self.enrichment_progress_timer.setInterval(1000)
        self.enrichment_progress_timer.timeout.connect(self.refresh_enrichment_progress)
        self.login_thread = None
        self.login_worker = None

        self.ensure_backend_running()
        self.init_ui()
        self.update_enrichment_controls()
        self.reset_progress_widgets()

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

    def init_ui(self):
        self.setWindowTitle('VidNorm - 本地视频整理工具')
        self.resize(1000, 700)
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
        self.table.setHorizontalHeaderLabels(['原文件名', '数据库重命名预览', '状态'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.status_label = QLabel('')
        self.progress_label = QLabel('')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(True)
        self.batch_countdown_label = QLabel('')

        button_layout = QVBoxLayout()
        top_button_row = QHBoxLayout()
        bottom_button_row = QHBoxLayout()

        self.btn_video_library = QPushButton('视频库')
        self.btn_video_library.clicked.connect(self.show_video_library)

        self.btn_database = QPushButton('数据中心')
        self.btn_database.clicked.connect(self.show_data_center)

        self.btn_view_actors = QPushButton('作者库')
        self.btn_view_actors.clicked.connect(self.show_actor_viewer)

        self.btn_view_code_prefixes = QPushButton('番号库')
        self.btn_view_code_prefixes.clicked.connect(self.show_code_prefix_viewer)

        self.btn_scan = QPushButton('扫描本地视频')
        self.btn_scan.clicked.connect(self.scan_files)

        self.btn_import_db = QPushButton('导入视频库')
        self.btn_import_db.clicked.connect(self.import_to_database)
        self.btn_import_db.setEnabled(False)

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

        top_button_row.addWidget(self.btn_video_library)
        top_button_row.addWidget(self.btn_database)
        top_button_row.addWidget(self.btn_view_actors)
        top_button_row.addWidget(self.btn_view_code_prefixes)
        top_button_row.addStretch()

        bottom_button_row.addWidget(self.btn_scan)
        bottom_button_row.addWidget(self.btn_import_db)
        bottom_button_row.addWidget(self.btn_auto_login)
        bottom_button_row.addWidget(self.btn_enrich)
        bottom_button_row.addWidget(self.btn_stop_enrich)
        bottom_button_row.addWidget(self.btn_reset_browser_profile)
        bottom_button_row.addWidget(self.btn_execute)
        bottom_button_row.addStretch()

        button_layout.addLayout(top_button_row)
        button_layout.addLayout(bottom_button_row)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_label)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.batch_countdown_label)
        main_layout.addLayout(button_layout)
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
        self.btn_import_db.setEnabled(False)

    def scan_files(self):
        self.refresh_scan_results(show_message=True)

    def refresh_scan_results(self, show_message=False):
        folder_path = self.path_input.text()
        if not folder_path:
            QMessageBox.warning(self, '错误', '请先选择文件夹')
            return False

        try:
            result = self.backend_client.scan_folder(folder_path)
        except Exception as exc:
            QMessageBox.warning(self, '错误', str(exc))
            return False

        self.pending_renames = result.get('plans', [])
        self.table.setRowCount(0)

        has_files_to_rename = False
        has_files_to_import = False

        for row, plan in enumerate(self.pending_renames):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plan.get('old_name', '')))
            self.table.setItem(row, 1, QTableWidgetItem(plan.get('preview_name', '')))

            row_status = plan.get('row_status', '')
            status_item = QTableWidgetItem(row_status)
            status_item.setForeground(self._status_color(row_status))
            self.table.setItem(row, 2, status_item)

            has_files_to_rename = has_files_to_rename or bool(plan.get('can_rename') and plan.get('needs_rename'))
            has_files_to_import = has_files_to_import or bool(plan.get('import_required'))

        self.btn_execute.setEnabled(has_files_to_rename)
        self.btn_import_db.setEnabled(has_files_to_import)

        if show_message:
            QMessageBox.information(
                self,
                '扫描完成',
                (
                    f"共识别到 {result.get('count', 0)} 个视频。\n"
                    f"待导入: {result.get('import_count', 0)} 个\n"
                    f"待重命名: {result.get('rename_count', 0)} 个"
                ),
            )
        return True

    def import_to_database(self):
        if not self.pending_renames:
            return

        try:
            result = self.backend_client.import_videos(self.pending_renames)
        except Exception as exc:
            QMessageBox.critical(self, '错误', f'导入视频库失败：\n{str(exc)}')
            return

        success_count = result.get('success_count', 0)
        self.refresh_scan_results(show_message=False)
        QMessageBox.information(
            self,
            '导入完成',
            f'成功将 {success_count} 个缺失番号写入视频库，可用于后续补全。',
        )

    def execute_rename(self):
        if not self.pending_renames:
            return

        renamable_plans = [
            plan
            for plan in self.pending_renames
            if bool(plan.get('can_rename')) and bool(plan.get('needs_rename'))
        ]
        if not renamable_plans:
            QMessageBox.information(self, '提示', '当前没有可重命名的视频。')
            return

        try:
            response = self.backend_client.execute_renames(renamable_plans)
        except Exception as exc:
            QMessageBox.critical(self, '错误', f'执行重命名失败：\n{str(exc)}')
            return

        success = response.get('success_count', 0)
        self.refresh_scan_results(show_message=False)
        QMessageBox.information(self, '结果', f'成功重命名 {success} 个文件。')

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
            values['target_type'],
            values['source_key'],
            mode='single',
        )

    def start_enrichment(self, limit, show_browser, cooldown_before_search, target_type, source_key, mode='single'):
        self.enrichment_mode = mode
        if mode == 'batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(f'分批补全第 {self.batch_enrichment_round} 批正在进行中，界面可继续操作。')
        else:
            self.status_label.setText('补全任务进行中，界面可继续操作。')
        self.update_enrichment_controls()
        self.reset_progress_widgets(keep_visible=True)
        self.enrichment_progress_timer.start()
        self.refresh_enrichment_progress()

        self.enrichment_thread = QThread(self)
        self.enrichment_worker = EnrichmentWorker(
            self.backend_client,
            limit,
            show_browser,
            cooldown_before_search,
            target_type,
            source_key,
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
            'target_type': values['target_type'],
            'source_key': values['source_key'],
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            f"分批补全已启动：每 {values['batch_interval_minutes']} 分钟补全 {values['batch_limit']} 个条目。"
        )
        self.update_enrichment_controls()
        self.run_next_batch_enrichment()

    def run_next_batch_enrichment(self):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return
        if self.enrichment_thread is not None:
            return

        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_countdown_label.setText('')

        self.start_enrichment(
            self.batch_enrichment_config['limit'],
            self.batch_enrichment_config['show_browser'],
            self.batch_enrichment_config['cooldown_before_search'],
            self.batch_enrichment_config['target_type'],
            self.batch_enrichment_config['source_key'],
            mode='batch',
        )

    def schedule_next_batch_enrichment(self):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return

        interval_minutes = max(1, int(self.batch_enrichment_config['interval_minutes']))
        interval_seconds = interval_minutes * 60
        self.batch_next_run_at = time.time() + interval_seconds
        self.batch_timer.start(interval_seconds * 1000)
        self.batch_countdown_timer.start()
        self.status_label.setText(
            f'分批补全第 {self.batch_enrichment_round} 批已完成，将在 {interval_minutes} 分钟后开始下一批。'
        )
        self.update_batch_countdown()
        self.update_enrichment_controls()
        self.reset_progress_widgets()

    def stop_batch_enrichment(self, message='已停止分批补全计划。'):
        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_enrichment_active = False
        self.batch_enrichment_config = None
        self.update_enrichment_controls()
        self.status_label.setText(message)
        self.batch_countdown_label.setText('')
        self.reset_progress_widgets()

    def update_batch_countdown(self):
        if self.batch_next_run_at is None:
            self.batch_countdown_label.setText('')
            return

        remaining_seconds = max(0, int(round(self.batch_next_run_at - time.time())))
        minutes, seconds = divmod(remaining_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if remaining_seconds <= 0:
            self.batch_countdown_timer.stop()
            self.batch_countdown_label.setText('下一批补全即将开始...')
            return

        if hours > 0:
            countdown_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        else:
            countdown_text = f'{minutes:02d}:{seconds:02d}'
        self.batch_countdown_label.setText(f'分批补全倒计时：{countdown_text}')

    def update_enrichment_controls(self):
        enrichment_running = self.enrichment_thread is not None
        self.btn_enrich.setEnabled(not enrichment_running and not self.batch_enrichment_active)
        self.btn_stop_enrich.setEnabled(enrichment_running or self.batch_enrichment_active)

    def refresh_enrichment_progress(self):
        try:
            progress = self.backend_client.get_enrichment_progress()
        except Exception:
            return

        total_count = int(progress.get('total_count', 0) or 0)
        processed_count = int(progress.get('processed_count', 0) or 0)
        success_count = int(progress.get('success_count', 0) or 0)
        failed_count = int(progress.get('failed_count', 0) or 0)
        progress_percent = float(progress.get('progress_percent', 0) or 0)
        target_label = str(progress.get('target_label', '') or '')
        source_label = str(progress.get('source_label', '') or '')
        current_item = str(progress.get('current_item', '') or '')
        message = str(progress.get('message', '') or '')
        is_running = bool(progress.get('is_running'))

        if not is_running and total_count <= 0 and not message:
            return

        label_text = target_label or '补全任务'
        if source_label:
            label_text = f'{label_text} / {source_label}'
        if current_item:
            label_text = f'{label_text} | 当前: {current_item}'
        elif message:
            label_text = f'{label_text} | {message}'

        self.progress_label.setText(label_text)
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_bar.setValue(int(progress_percent * 10))
        if total_count > 0:
            self.progress_bar.setFormat(
                f'{processed_count}/{total_count} | 成功 {success_count} | 失败 {failed_count} | {progress_percent:.1f}%'
            )
        else:
            self.progress_bar.setFormat(message or '准备中...')

    def reset_progress_widgets(self, keep_visible=False):
        self.enrichment_progress_timer.stop()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('0/0 | 0.0%')
        self.progress_label.setText('')
        if keep_visible:
            self.progress_bar.show()
            self.progress_label.show()
            return
        self.progress_bar.hide()
        self.progress_label.hide()

    def stop_enrichment(self):
        if self.enrichment_thread is None:
            if self.batch_enrichment_active:
                self.stop_batch_enrichment('已停止分批补全计划。')
            return

        self.btn_stop_enrich.setEnabled(False)
        if self.batch_enrichment_active:
            self.batch_timer.stop()
            self.batch_countdown_timer.stop()
            self.batch_next_run_at = None
            self.batch_countdown_label.setText('')
            self.batch_enrichment_active = False
            self.batch_enrichment_config = None
        self.status_label.setText('已请求停止补全，当前条目处理完成后会停止。')
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
        entity_label = result.get('entity_label', '视频')
        remaining_label = result.get('remaining_label', f'剩余未补全{entity_label}')
        summary = (
            f"本次处理 {result.get('processed_count', 0)} 个{entity_label}。\n"
            f"成功: {result.get('success_count', 0)} 个\n"
            f"失败: {result.get('failed_count', 0)} 个\n"
            f"{remaining_label}: {result.get('remaining_count', 0)} 个"
        )

        if result.get('requires_manual_verification'):
            message = result.get('message') or '检测到 AVFan 人机验证，已停止当前补全任务。'
            if mode == 'batch':
                self.stop_batch_enrichment('检测到人机验证，已停止分批补全。')
            else:
                self.status_label.setText('')
            QMessageBox.warning(self, '需要人工验证', f'{message}\n\n{summary}')
            return

        if mode == 'batch':
            if not self.batch_enrichment_active:
                self.status_label.setText('已停止分批补全计划。')
                QMessageBox.information(self, '分批补全已停止', summary)
                return

            if result.get('processed_count', 0) == 0 or result.get('remaining_count', 0) <= 0:
                self.stop_batch_enrichment(f'分批补全已完成，当前没有待补全{entity_label}。')
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
        if not self.batch_enrichment_active:
            self.reset_progress_widgets()

    def reset_browser_profile(self):
        answer = QMessageBox.question(
            self,
            '重置网页登录状态',
            '这会清除补全信息使用的专用浏览器登录状态、Cookie 和验证记录。\n'
            '不会影响视频数据库，也不会影响你日常使用的 Chrome。\n\n'
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
                f"{result.get('message', '已重置网页登录状态。')}\n\n目录: {result.get('profile_dir', '')}",
            )
        except Exception as exc:
            QMessageBox.critical(self, '重置失败', str(exc))
        finally:
            self.btn_reset_browser_profile.setEnabled(True)

    def show_data_center(self):
        viewer = DataCenterWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_video_library(self):
        viewer = DatabaseViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_actor_viewer(self):
        viewer = ActorViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_code_prefix_viewer(self):
        viewer = CodePrefixViewerWindow(backend_client=self.backend_client, parent=self)
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

    @staticmethod
    def _status_color(row_status):
        if row_status == IMPORT_REQUIRED_STATUS:
            return Qt.darkYellow
        if row_status == ENRICHMENT_REQUIRED_STATUS:
            return Qt.darkYellow
        if row_status == RENAME_REQUIRED_STATUS:
            return Qt.blue
        if row_status == NORMALIZED_STATUS:
            return Qt.darkGreen
        return Qt.black


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = VidNormApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
