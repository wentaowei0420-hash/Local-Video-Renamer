import subprocess
import sys
import time
import uuid

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
from app.core.backend_protocol import BACKEND_API_REVISION
from app.core.local_video_labels import (
    ENRICHMENT_REQUIRED_STATUS,
    IMPORT_REQUIRED_STATUS,
    NORMALIZED_STATUS,
    RENAME_REQUIRED_STATUS,
)
from app.core.project_paths import PROJECT_ROOT
from app.core.runtime_config import get_backend_port
from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow
from app.gui.data_center_viewer import DataCenterWindow
from app.gui.db_viewer import DatabaseViewerWindow
from app.gui.enrichment_dialog import EnrichmentDialog
from app.gui.i18n import tr
from app.gui.ladder_board_viewer import LadderBoardWindow
from app.gui.path_library_viewer import PathLibraryWindow
from app.gui.task_progress_widget import TaskProgressWidget
from app.gui.video_category_viewer import VideoCategoryViewerWindow


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


class ComboEnrichmentWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        backend_client,
        combo_key,
        limit,
        show_browser,
        cooldown_before_search,
        combo_task_settings=None,
        batch_mode=False,
    ):
        super().__init__()
        self.backend_client = backend_client
        self.combo_key = combo_key
        self.limit = limit
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.combo_task_settings = dict(combo_task_settings or {})
        self.batch_mode = bool(batch_mode)

    def run(self):
        try:
            result = self.backend_client.enrich_combo(
                self.combo_key,
                self.limit,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                combo_task_settings=self.combo_task_settings,
                batch_mode=self.batch_mode,
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


class VidNormApp(QWidget, AsyncTaskHostMixin):
    def __init__(self):
        super().__init__()
        self.pending_renames = []
        self.backend_process = None
        self.backend_instance_token = ''
        self.backend_client = BackendClient()
        self.enrichment_thread = None
        self.enrichment_worker = None
        self.current_enrichment_kind = 'single'
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
        self._init_async_task_host()

        self.ensure_backend_running()
        self.init_ui()
        self.update_enrichment_controls()
        self.reset_progress_widgets()

    def ensure_backend_running(self):
        self.backend_instance_token = uuid.uuid4().hex
        health = self.get_backend_health()
        if health is not None:
            self.stop_backend_on_port()

        backend_script = PROJECT_ROOT / 'backend_server.py'
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.backend_process = subprocess.Popen(
            [sys.executable, str(backend_script), '--instance-token', self.backend_instance_token],
            cwd=str(backend_script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        deadline = time.time() + 5
        while time.time() < deadline:
            health = self.get_backend_health()
            if self.is_expected_backend_instance(health):
                return
            time.sleep(0.2)

        raise RuntimeError(tr('main.backend_start_timeout'))

    def is_backend_alive(self):
        return self.get_backend_health() is not None

    def get_backend_health(self):
        try:
            return self.backend_client.health()
        except Exception:
            return None

    def is_backend_compatible(self, health):
        return bool(health) and str(health.get('backend_revision') or '') == BACKEND_API_REVISION

    def is_expected_backend_instance(self, health):
        return (
            self.is_backend_compatible(health)
            and str((health or {}).get('backend_instance_token') or '').strip() == self.backend_instance_token
        )

    def stop_backend_on_port(self):
        if self.backend_process and self.backend_process.poll() is None:
            self.backend_process.terminate()
            try:
                self.backend_process.wait(timeout=3)
            except Exception:
                pass
            self.backend_process = None
            return

        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        port = str(get_backend_port())
        result = subprocess.run(
            ['netstat', '-ano', '-p', 'tcp'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creation_flags,
        )
        target_pids = set()
        port_token = f':{port}'
        for line in result.stdout.splitlines():
            upper_line = line.upper()
            if 'LISTENING' not in upper_line or port_token not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            local_address = parts[1]
            if port_token not in local_address:
                continue
            pid = str(parts[-1] or '').strip()
            if pid.isdigit():
                target_pids.add(pid)

        for pid in sorted(target_pids):
            subprocess.run(
                ['taskkill', '/PID', pid, '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

        if target_pids:
            time.sleep(0.5)

    def stop_owned_backend(self):
        if self.backend_process and self.backend_process.poll() is None:
            self.backend_process.terminate()
            try:
                self.backend_process.wait(timeout=3)
            except Exception:
                pass
            self.backend_process = None
            return

        health = self.get_backend_health()
        if self.is_expected_backend_instance(health):
            self.stop_backend_on_port()

    def init_ui(self):
        self.setWindowTitle(tr('main.title'))
        self.resize(1000, 700)
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(tr('main.path_placeholder'))
        self.path_input.setReadOnly(True)

        self.btn_browse = QPushButton(tr('main.browse'))
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_path_library = QPushButton(tr('main.path_library'))
        self.btn_path_library.clicked.connect(self.show_path_library)

        top_layout.addWidget(QLabel(tr('main.local_folder')))
        top_layout.addWidget(self.path_input)
        top_layout.addWidget(self.btn_path_library)
        top_layout.addWidget(self.btn_browse)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(tr('main.scan_headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.status_label = QLabel('')
        self.progress_label = QLabel('')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(True)
        self.combo_subtask_widgets = [TaskProgressWidget(self), TaskProgressWidget(self)]
        self.batch_countdown_label = QLabel('')

        button_layout = QVBoxLayout()
        top_button_row = QHBoxLayout()
        bottom_button_row = QHBoxLayout()

        self.btn_video_library = QPushButton(tr('main.video_library'))
        self.btn_video_library.clicked.connect(self.show_video_library)

        self.btn_database = QPushButton(tr('main.data_center'))
        self.btn_database.clicked.connect(self.show_data_center)

        self.btn_view_actors = QPushButton(tr('main.actor_library'))
        self.btn_view_actors.clicked.connect(self.show_actor_viewer)

        self.btn_view_code_prefixes = QPushButton(tr('main.code_prefix_library'))
        self.btn_view_code_prefixes.clicked.connect(self.show_code_prefix_viewer)

        self.btn_tianji = QPushButton(tr('main.video_category'))
        self.btn_tianji.clicked.connect(self.show_video_category_viewer)

        self.btn_ladder_board = QPushButton(tr('main.ladder_board'))
        self.btn_ladder_board.clicked.connect(self.show_ladder_board_viewer)

        self.btn_scan = QPushButton(tr('main.scan_local_videos'))
        self.btn_scan.clicked.connect(self.scan_files)

        self.btn_import_db = QPushButton(tr('main.import_video_library'))
        self.btn_import_db.clicked.connect(self.import_to_database)
        self.btn_import_db.setEnabled(False)

        self.btn_auto_login = QPushButton(tr('main.auto_login'))
        self.btn_auto_login.clicked.connect(self.auto_login)

        self.btn_enrich = QPushButton(tr('main.enrich_info'))
        self.btn_enrich.clicked.connect(self.enrich_video_info)

        self.btn_stop_enrich = QPushButton(tr('main.stop_enrich'))
        self.btn_stop_enrich.clicked.connect(self.stop_enrichment)
        self.btn_stop_enrich.setEnabled(False)

        self.btn_reset_browser_profile = QPushButton(tr('main.reset_browser_profile'))
        self.btn_reset_browser_profile.clicked.connect(self.reset_browser_profile)

        self.btn_status_sync = QPushButton(tr('main.status_sync'))
        self.btn_status_sync.clicked.connect(self.sync_library_statuses)

        self.btn_execute = QPushButton(tr('main.execute_rename'))
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_execute.setEnabled(False)

        top_button_row.addWidget(self.btn_video_library)
        top_button_row.addWidget(self.btn_database)
        top_button_row.addWidget(self.btn_view_actors)
        top_button_row.addWidget(self.btn_view_code_prefixes)
        top_button_row.addWidget(self.btn_tianji)
        top_button_row.addWidget(self.btn_ladder_board)
        top_button_row.addStretch()

        bottom_button_row.addWidget(self.btn_scan)
        bottom_button_row.addWidget(self.btn_import_db)
        bottom_button_row.addWidget(self.btn_auto_login)
        bottom_button_row.addWidget(self.btn_enrich)
        bottom_button_row.addWidget(self.btn_stop_enrich)
        bottom_button_row.addWidget(self.btn_reset_browser_profile)
        bottom_button_row.addWidget(self.btn_status_sync)
        bottom_button_row.addWidget(self.btn_execute)
        bottom_button_row.addStretch()

        button_layout.addLayout(top_button_row)
        button_layout.addLayout(bottom_button_row)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_label)
        main_layout.addWidget(self.progress_bar)
        for combo_subtask_widget in self.combo_subtask_widgets:
            combo_subtask_widget.hide()
            main_layout.addWidget(combo_subtask_widget)
        main_layout.addWidget(self.batch_countdown_label)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, tr('common.select_folder'))
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
            QMessageBox.warning(self, tr('common.prompt'), tr('main.select_folder_first'))
            return False

        def task():
            return {
                'scan_result': self.backend_client.scan_folder(folder_path),
                'show_message': bool(show_message),
            }

        self.start_async_task(task, self._on_scan_finished, tr('common.prompt'))
        return True

    def import_to_database(self):
        if not self.pending_renames:
            return

        folder_path = self.path_input.text()
        plans = list(self.pending_renames)

        def task():
            result = self.backend_client.import_videos(plans)
            scan_result = self.backend_client.scan_folder(folder_path)
            return {
                'success_count': result.get('success_count', 0),
                'scan_result': scan_result,
            }

        self.start_async_task(task, self._on_import_finished, tr('common.prompt'))

    def execute_rename(self):
        if not self.pending_renames:
            return

        renamable_plans = [
            plan
            for plan in self.pending_renames
            if bool(plan.get('can_rename')) and bool(plan.get('needs_rename'))
        ]
        if not renamable_plans:
            QMessageBox.information(self, tr('common.prompt'), tr('main.no_renamable_videos'))
            return

        folder_path = self.path_input.text()

        def task():
            response = self.backend_client.execute_renames(renamable_plans)
            scan_result = self.backend_client.scan_folder(folder_path)
            return {
                'success_count': response.get('success_count', 0),
                'scan_result': scan_result,
            }

        self.start_async_task(task, self._on_execute_rename_finished, tr('common.prompt'))

    def auto_login(self):
        if self.login_thread is not None:
            QMessageBox.information(self, tr('main.login_in_progress_title'), tr('main.login_in_progress_message'))
            return
        self.start_auto_login()

    def start_auto_login(self):
        self.btn_auto_login.setEnabled(False)
        self.status_label.setText(tr('main.login_status'))

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
            QMessageBox.information(
                self,
                tr('main.enrichment_in_progress_title'),
                tr('main.enrichment_in_progress_message'),
            )
            return

        dialog = EnrichmentDialog(self)
        if not dialog.exec_():
            return

        values = dialog.values()
        if dialog.action_mode == 'batch':
            self.start_batch_enrichment(values)
            return
        if dialog.action_mode == 'combo_single':
            self.start_combo_enrichment(
                values['combo_key'],
                values['limit'],
                values['show_browser'],
                values['cooldown_before_search'],
                combo_task_settings=self._build_combo_task_settings_for_mode(
                    values.get('combo_task_settings', {}),
                    use_batch_limit=False,
                ),
                mode='combo_single',
            )
            return
        if dialog.action_mode == 'combo_batch':
            self.start_combo_batch_plan(values)
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
        self.current_enrichment_kind = 'single'
        self.enrichment_mode = mode
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
        if mode == 'batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(
                tr('main.batch_round_running', round_number=self.batch_enrichment_round)
            )
        else:
            self.status_label.setText(tr('main.single_enrichment_running'))
        self.update_enrichment_controls()
        self.reset_progress_widgets(keep_visible=True)
        self.enrichment_progress_timer.start()
        self.refresh_enrichment_progress()
        self.enrichment_thread.started.connect(self.enrichment_worker.run)
        self.enrichment_worker.finished.connect(self.on_enrichment_finished)
        self.enrichment_worker.failed.connect(self.on_enrichment_failed)
        self.enrichment_worker.finished.connect(self.enrichment_thread.quit)
        self.enrichment_worker.failed.connect(self.enrichment_thread.quit)
        self.enrichment_thread.finished.connect(self.cleanup_enrichment_thread)
        self.enrichment_thread.start()

    def start_combo_enrichment(
        self,
        combo_key,
        limit,
        show_browser,
        cooldown_before_search,
        combo_task_settings=None,
        mode='combo_single',
        batch_mode=False,
    ):
        self.current_enrichment_kind = 'combo'
        self.enrichment_mode = mode
        self.enrichment_thread = QThread(self)
        self.enrichment_worker = ComboEnrichmentWorker(
            self.backend_client,
            combo_key,
            limit,
            show_browser,
            cooldown_before_search,
            combo_task_settings=combo_task_settings,
            batch_mode=batch_mode,
        )
        self.enrichment_worker.moveToThread(self.enrichment_thread)
        if mode == 'combo_batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(
                tr('main.combo_round_running', round_number=self.batch_enrichment_round)
            )
        else:
            self.status_label.setText(tr('main.combo_running'))
        self.update_enrichment_controls()
        self.reset_progress_widgets(keep_visible=True)
        self.enrichment_progress_timer.start()
        self.refresh_enrichment_progress()
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
            'task_kind': 'single',
            'limit': values['batch_limit'],
            'interval_minutes': values['batch_interval_minutes'],
            'show_browser': values['show_browser'],
            'cooldown_before_search': values['cooldown_before_search'],
            'target_type': values['target_type'],
            'source_key': values['source_key'],
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            tr(
                'main.batch_started',
                interval_minutes=values['batch_interval_minutes'],
                batch_limit=values['batch_limit'],
            )
        )
        self.update_enrichment_controls()
        self.run_next_batch_enrichment()

    def start_batch_combo_enrichment(self, values):
        combo_task_settings = self._build_combo_task_settings_for_mode(
            values.get('combo_task_settings', {}),
            use_batch_limit=True,
        )
        self.batch_enrichment_active = True
        self.batch_enrichment_config = {
            'task_kind': 'combo',
            'combo_key': values['combo_key'],
            'limit': self._combo_default_limit(combo_task_settings, fallback=values['batch_limit']),
            'interval_minutes': self._combo_batch_interval_minutes(
                combo_task_settings,
                fallback=values['batch_interval_minutes'],
            ),
            'show_browser': values['show_browser'],
            'cooldown_before_search': values['cooldown_before_search'],
            'combo_task_settings': combo_task_settings,
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            tr(
                'main.combo_batch_started',
                interval_minutes=values['batch_interval_minutes'],
                batch_limit=values['batch_limit'],
            )
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

        if self.batch_enrichment_config.get('task_kind') == 'combo':
            self.start_combo_enrichment(
                self.batch_enrichment_config['combo_key'],
                self.batch_enrichment_config['limit'],
                self.batch_enrichment_config['show_browser'],
                self.batch_enrichment_config['cooldown_before_search'],
                combo_task_settings=self.batch_enrichment_config.get('combo_task_settings', {}),
                mode='combo_batch',
            )
            return

        self.start_enrichment(
            self.batch_enrichment_config['limit'],
            self.batch_enrichment_config['show_browser'],
            self.batch_enrichment_config['cooldown_before_search'],
            self.batch_enrichment_config['target_type'],
            self.batch_enrichment_config['source_key'],
            mode='batch',
        )

    def start_combo_batch_plan(self, values):
        combo_task_settings = self._build_combo_task_settings_for_mode(
            values.get('combo_task_settings', {}),
            use_batch_limit=True,
        )
        effective_limit = self._combo_default_limit(combo_task_settings, fallback=values['batch_limit'])
        self.batch_enrichment_active = True
        self.batch_enrichment_config = {
            'task_kind': 'combo_plan',
            'combo_key': values['combo_key'],
            'combo_task_settings': combo_task_settings,
        }
        self.batch_enrichment_round = 0
        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_countdown_label.setText(tr('main.combo_plan_countdown'))
        self.update_enrichment_controls()
        self.start_combo_enrichment(
            values['combo_key'],
            effective_limit,
            values['show_browser'],
            values['cooldown_before_search'],
            combo_task_settings=combo_task_settings,
            mode='combo_batch',
            batch_mode=True,
        )
        self.status_label.setText(tr('main.combo_plan_status'))

    @staticmethod
    def _build_combo_task_settings_for_mode(combo_task_settings, use_batch_limit):
        normalized = {}
        for task_key, task_settings in dict(combo_task_settings or {}).items():
            current = dict(task_settings or {})
            limit_key = 'batch_limit' if use_batch_limit else 'limit'
            normalized[task_key] = {
                'target_type': current.get('target_type'),
                'source_key': current.get('source_key'),
                'limit': max(1, int(current.get(limit_key, current.get('limit', 1)) or 1)),
                'show_browser': bool(current.get('show_browser')),
                'cooldown_before_search': bool(current.get('cooldown_before_search')),
                'batch_interval_minutes': max(1, int(current.get('batch_interval_minutes', 1) or 1)),
            }
        return normalized

    @staticmethod
    def _combo_default_limit(combo_task_settings, fallback=1):
        limits = [
            max(1, int((task_settings or {}).get('limit', 0) or 0))
            for task_settings in dict(combo_task_settings or {}).values()
            if int((task_settings or {}).get('limit', 0) or 0) > 0
        ]
        if limits:
            return max(limits)
        return max(1, int(fallback or 1))

    @staticmethod
    def _combo_batch_interval_minutes(combo_task_settings, fallback=1):
        intervals = [
            max(1, int((task_settings or {}).get('batch_interval_minutes', 0) or 0))
            for task_settings in dict(combo_task_settings or {}).values()
            if int((task_settings or {}).get('batch_interval_minutes', 0) or 0) > 0
        ]
        if intervals:
            return max(intervals)
        return max(1, int(fallback or 1))

    def schedule_next_batch_enrichment(self, last_result=None):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return

        interval_minutes = max(1, int(self.batch_enrichment_config['interval_minutes']))
        interval_seconds = interval_minutes * 60
        self.batch_next_run_at = time.time() + interval_seconds
        self.batch_timer.start(interval_seconds * 1000)
        self.batch_countdown_timer.start()
        if last_result and int(last_result.get('processed_count', 0) or 0) <= 0:
            entity_label = str(last_result.get('entity_label', tr('main.batch_entity_default')) or tr('main.batch_entity_default'))
            message = str(last_result.get('message', '') or '').strip()
            status_text = tr(
                'main.batch_no_items',
                round_number=self.batch_enrichment_round,
                entity_label=entity_label,
                interval_minutes=interval_minutes,
            )
            if message:
                status_text = tr('main.batch_current_hint', status_text=status_text, message=message)
            self.status_label.setText(status_text)
        else:
            self.status_label.setText(
                tr(
                    'main.batch_round_completed',
                    round_number=self.batch_enrichment_round,
                    interval_minutes=interval_minutes,
                )
            )
        self.update_batch_countdown()
        self.update_enrichment_controls()
        self.reset_progress_widgets()

    def stop_batch_enrichment(self, message=None):
        message = message or tr('main.batch_stopped')
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
            self.batch_countdown_label.setText(tr('main.next_batch_soon'))
            return

        if hours > 0:
            countdown_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        else:
            countdown_text = f'{minutes:02d}:{seconds:02d}'
        self.batch_countdown_label.setText(tr('main.batch_countdown', countdown_text=countdown_text))

    def update_enrichment_controls(self):
        enrichment_running = self.enrichment_thread is not None
        self.btn_enrich.setEnabled(not enrichment_running and not self.batch_enrichment_active)
        self.btn_stop_enrich.setEnabled(enrichment_running or self.batch_enrichment_active)

    def refresh_enrichment_progress(self):
        try:
            progress = self.backend_client.get_enrichment_progress()
        except Exception:
            return
        if progress.get('task_kind') == 'combo':
            self.refresh_combo_enrichment_progress(progress)
            return
        self.hide_combo_subtask_progress()

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
        count_unit = str(progress.get('count_unit', '') or tr('main.progress_default_unit'))
        log_path = str(progress.get('log_path', '') or '')

        if not is_running and total_count <= 0 and not message:
            return

        label_text = target_label or tr('main.enrichment_task')
        if source_label:
            label_text = f'{label_text} / {source_label}'
        if current_item:
            label_text = f"{label_text} | {tr('common.current', value=current_item)}"
        elif message:
            label_text = f'{label_text} | {message}'
        if log_path and not is_running:
            label_text = f"{label_text} | {tr('common.log', value=log_path)}"

        self.progress_label.setText(label_text)
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_bar.setValue(int(progress_percent * 10))
        if total_count > 0:
            self.progress_bar.setFormat(
                tr(
                    'main.progress_format',
                    processed_count=processed_count,
                    total_count=total_count,
                    count_unit='',
                    success_count=success_count,
                    failed_count=failed_count,
                    progress_percent=progress_percent,
                ).replace('  |', ' |', 1)
            )
        else:
            self.progress_bar.setFormat(message or tr('common.preparing'))

        if total_count > 0:
            self.progress_bar.setFormat(
                tr(
                    'main.progress_format',
                    processed_count=processed_count,
                    total_count=total_count,
                    count_unit=count_unit,
                    success_count=success_count,
                    failed_count=failed_count,
                    progress_percent=progress_percent,
                )
            )

    def refresh_combo_enrichment_progress(self, progress):
        target_label = str(progress.get('target_label', '') or tr('main.combo_task'))
        message = str(progress.get('message', '') or '')
        current_item = str(progress.get('current_item', '') or '')
        is_running = bool(progress.get('is_running'))
        log_path = str(progress.get('log_path', '') or '')
        subtasks = list((progress.get('subtasks', {}) or {}).values())

        if not is_running and not subtasks and not message:
            return

        label_text = target_label
        if current_item:
            label_text = f"{label_text} | {tr('common.current', value=current_item)}"
        elif message:
            label_text = f'{label_text} | {message}'
        if log_path and not is_running:
            label_text = f"{label_text} | {tr('common.log', value=log_path)}"

        self.progress_label.setText(label_text)
        self.progress_label.show()
        self.progress_bar.hide()

        for index, combo_subtask_widget in enumerate(self.combo_subtask_widgets):
            if index >= len(subtasks):
                combo_subtask_widget.reset(hide_widget=True)
                continue
            task_state = dict(subtasks[index] or {})
            combo_subtask_widget.set_progress(
                title=str(task_state.get('task_label', '') or task_state.get('task_key', tr('common.subtask'))),
                processed_count=int(task_state.get('processed_count', 0) or 0),
                total_count=int(task_state.get('total_count', 0) or 0),
                success_count=int(task_state.get('success_count', 0) or 0),
                failed_count=int(task_state.get('failed_count', 0) or 0),
                progress_percent=float(task_state.get('progress_percent', 0) or 0),
                count_unit=str(task_state.get('count_unit', '') or tr('main.progress_default_unit')),
                current_item=str(task_state.get('current_item', '') or ''),
                message=str(task_state.get('message', '') or ''),
            )
        self.update_combo_batch_countdown_label(progress)

    def update_combo_batch_countdown_label(self, progress):
        if self.enrichment_mode != 'combo_batch' or not self.batch_enrichment_active:
            self.batch_countdown_label.setText('')
            return

        waiting_segments = []
        running_segments = []
        for task_state in (progress.get('subtasks', {}) or {}).values():
            task_state = dict(task_state or {})
            task_label = str(task_state.get('task_label', '') or task_state.get('task_key', tr('common.subtask')))
            detail_message = str(task_state.get('message', '') or '').strip()
            if detail_message.startswith(tr('main.combo_subtask_waiting_prefix')):
                waiting_segments.append(f'{task_label}: {detail_message}')
            elif bool(task_state.get('is_running')):
                running_segments.append(tr('main.combo_subtask_running', task_label=task_label))

        if waiting_segments or running_segments:
            self.batch_countdown_label.setText(' | '.join(waiting_segments + running_segments))
            return

        self.batch_countdown_label.setText(tr('main.combo_waiting_status'))

    def hide_combo_subtask_progress(self):
        for combo_subtask_widget in self.combo_subtask_widgets:
            combo_subtask_widget.reset(hide_widget=True)

    def reset_progress_widgets(self, keep_visible=False):
        self.enrichment_progress_timer.stop()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('0/0 | 0.0%')
        self.progress_label.setText('')
        self.hide_combo_subtask_progress()
        if keep_visible:
            self.progress_bar.show()
            self.progress_label.show()
            return
        self.progress_bar.hide()
        self.progress_label.hide()

    def stop_enrichment(self):
        if self.enrichment_thread is None:
            if self.batch_enrichment_active:
                self.stop_batch_enrichment(tr('main.batch_stopped'))
            return

        self.btn_stop_enrich.setEnabled(False)
        if self.batch_enrichment_active:
            self.batch_timer.stop()
            self.batch_countdown_timer.stop()
            self.batch_next_run_at = None
            self.batch_countdown_label.setText('')
            self.batch_enrichment_active = False
            self.batch_enrichment_config = None
        self.status_label.setText(tr('main.stop_enrichment_requested'))
        try:
            result = self.backend_client.cancel_enrichment()
            self.status_label.setText(result.get('message', tr('main.stop_enrichment_requested_default')))
        except Exception as exc:
            self.update_enrichment_controls()
            self.status_label.setText(tr('main.stop_enrichment_request_failed'))
            QMessageBox.critical(self, tr('main.stop_failed'), str(exc))

    def on_auto_login_finished(self, result):
        QMessageBox.information(
            self,
            tr('main.auto_login_completed'),
            result.get('message', tr('main.auto_login_completed_default')),
        )

    def on_auto_login_failed(self, error_message):
        QMessageBox.critical(self, tr('main.auto_login_failed'), error_message)

    def on_enrichment_finished(self, result):
        mode = self.enrichment_mode
        is_batch_mode = mode in ('batch', 'combo_batch')
        entity_label = result.get('entity_label', tr('main.entity_default'))
        summary = self.build_enrichment_summary(result)

        if result.get('requires_manual_verification'):
            message = result.get('message') or tr('main.manual_verification_message')
            if is_batch_mode:
                self.stop_batch_enrichment(tr('main.manual_verification_batch_stopped'))
            else:
                self.status_label.setText('')
            QMessageBox.warning(self, tr('main.manual_verification_title'), f'{message}\n\n{summary}')
            return

        if mode == 'combo_batch':
            if not self.batch_enrichment_active:
                self.status_label.setText(tr('main.combo_plan_stopped'))
                self.batch_countdown_label.setText('')
                QMessageBox.information(self, tr('main.combo_plan_stopped_title'), summary)
                return

            self.stop_batch_enrichment(tr('main.combo_plan_ended'))
            QMessageBox.information(self, tr('main.combo_plan_ended_title'), summary)
            return

        if is_batch_mode:
            if not self.batch_enrichment_active:
                self.status_label.setText(tr('main.batch_stopped'))
                QMessageBox.information(self, tr('main.batch_stopped_title'), summary)
                return

            self.schedule_next_batch_enrichment(last_result=result)
            return

        title = tr('main.enrichment_stopped_title') if result.get('stopped') else tr('main.enrichment_completed_title')
        QMessageBox.information(self, title, summary)
        self.status_label.setText('')

    def on_enrichment_failed(self, error_message):
        mode = self.enrichment_mode
        if mode in ('batch', 'combo_batch'):
            self.stop_batch_enrichment(tr('main.batch_failed'))
            QMessageBox.critical(self, tr('main.batch_failed_title'), error_message)
            return

        self.status_label.setText('')
        QMessageBox.critical(self, tr('main.enrichment_failed_title'), error_message)

    def build_enrichment_summary(self, result):
        if result.get('task_kind') == 'combo':
            lines = [
                tr('main.combo_summary_title', combo_label=result.get('combo_label', '')),
                tr('main.combo_summary_hint'),
            ]
            for task_key, task_result in (result.get('subtask_results', {}) or {}).items():
                task_label = task_result.get('task_label') or task_result.get('entity_label') or task_key
                count_unit = task_result.get('count_unit') or tr('main.summary_count_unit_default')
                lines.append(
                    tr(
                        'main.combo_summary_task',
                        task_label=task_label,
                        processed_count=task_result.get('processed_count', 0),
                        count_unit=count_unit,
                        success_count=task_result.get('success_count', 0),
                        failed_count=task_result.get('failed_count', 0),
                        remaining_count=task_result.get('remaining_count', 0),
                    )
                )
            if result.get('message'):
                lines.append(tr('common.message', value=result.get('message')))
            if result.get('log_path'):
                lines.append(tr('common.log', value=result.get('log_path')))
            return '\n'.join(lines)

        count_unit = result.get('count_unit') or result.get('entity_label', tr('main.summary_count_unit_default'))
        remaining_label = result.get('remaining_label', tr('common.remaining_default'))
        lines = [
            tr(
                'main.summary_line_processed',
                processed_count=result.get('processed_count', 0),
                count_unit=count_unit,
            ),
            tr('main.summary_line_success', success_count=result.get('success_count', 0)),
            tr('main.summary_line_failed', failed_count=result.get('failed_count', 0)),
            tr(
                'main.summary_line_remaining',
                remaining_label=remaining_label,
                remaining_count=result.get('remaining_count', 0),
                count_unit=count_unit,
            ),
        ]
        if result.get('message'):
            lines.append(tr('common.message', value=result.get('message')))
        if result.get('log_path'):
            lines.append(tr('common.log', value=result.get('log_path')))
        return '\n'.join(lines)

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
        self.current_enrichment_kind = 'single'
        self.enrichment_mode = None
        self.update_enrichment_controls()
        if not self.batch_enrichment_active:
            self.reset_progress_widgets()

    def reset_browser_profile(self):
        answer = QMessageBox.question(
            self,
            tr('main.reset_browser_profile_title'),
            tr('main.reset_browser_profile_message'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: self.backend_client.reset_browser_profile(),
            self._on_reset_browser_profile_finished,
            tr('common.reset_failed'),
        )

    def start_async_task(self, task, success_handler, error_title=None):
        if self.is_async_task_running():
            QMessageBox.information(self, tr('common.task_in_progress'), tr('main.new_button_action_wait'))
            return False
        return super().start_async_task(task, success_handler, error_title)

    def _set_async_busy(self, busy):
        self.btn_browse.setEnabled(not busy)
        self.btn_path_library.setEnabled(not busy)
        self.btn_scan.setEnabled(not busy)
        self.btn_import_db.setEnabled(not busy and any(bool(plan.get('import_required')) for plan in self.pending_renames))
        self.btn_execute.setEnabled(
            not busy and any(bool(plan.get('can_rename') and plan.get('needs_rename')) for plan in self.pending_renames)
        )
        self.btn_reset_browser_profile.setEnabled(not busy)
        self.btn_status_sync.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def _apply_scan_result(self, result):
        result = dict(result or {})
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

    def _on_scan_finished(self, payload):
        scan_result = dict((payload or {}).get('scan_result', {}) or {})
        self._apply_scan_result(scan_result)
        if (payload or {}).get('show_message'):
            QMessageBox.information(
                self,
                tr('main.scan_completed'),
                tr(
                    'main.scan_completed_message',
                    count=scan_result.get('count', 0),
                    import_count=scan_result.get('import_count', 0),
                    rename_count=scan_result.get('rename_count', 0),
                ),
            )

    def _on_import_finished(self, payload):
        self._apply_scan_result((payload or {}).get('scan_result', {}))
        success_count = int((payload or {}).get('success_count', 0) or 0)
        QMessageBox.information(
            self,
            tr('main.import_completed'),
            tr('main.import_completed_message', success_count=success_count),
        )

    def _on_execute_rename_finished(self, payload):
        self._apply_scan_result((payload or {}).get('scan_result', {}))
        success_count = int((payload or {}).get('success_count', 0) or 0)
        QMessageBox.information(
            self,
            tr('main.result'),
            tr('main.rename_completed_message', success_count=success_count),
        )

    def _on_reset_browser_profile_finished(self, result):
        result = dict(result or {})
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr(
                'main.reset_completed_message',
                message=result.get('message', tr('main.reset_completed_default')),
                profile_dir=result.get('profile_dir', ''),
            ),
        )

    def sync_library_statuses(self):
        if self.enrichment_thread is not None or self.batch_enrichment_active:
            QMessageBox.information(
                self,
                tr('main.enrichment_in_progress_title'),
                tr('main.enrichment_in_progress_message'),
            )
            return

        self.start_async_task(
            lambda: self.backend_client.sync_library_statuses(),
            self._on_sync_library_statuses_finished,
            tr('common.operation_failed'),
        )

    def _on_sync_library_statuses_finished(self, result):
        result = dict(result or {})
        QMessageBox.information(
            self,
            tr('main.status_sync_completed_title'),
            tr(
                'main.status_sync_completed_message',
                candidate_code_count=int(result.get('candidate_code_count', 0) or 0),
                shared_code_count=int(result.get('shared_code_count', 0) or 0),
                synced_code_count=int(result.get('synced_code_count', 0) or 0),
                updated_code_prefix_movie_count=int(result.get('updated_code_prefix_movie_count', 0) or 0),
                updated_actor_movie_count=int(result.get('updated_actor_movie_count', 0) or 0),
                updated_prefix_count=int(result.get('updated_prefix_count', 0) or 0),
                updated_actor_count=int(result.get('updated_actor_count', 0) or 0),
                message=str(result.get('message', '') or tr('main.status_sync_completed_default')),
            ),
        )

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

    def show_video_category_viewer(self):
        viewer = VideoCategoryViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_ladder_board_viewer(self):
        viewer = LadderBoardWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_path_library(self):
        viewer = PathLibraryWindow(backend_client=self.backend_client, parent=self)
        if viewer.exec_() and viewer.selected_path:
            self.set_current_folder(viewer.selected_path)

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        if self.enrichment_thread and self.enrichment_thread.isRunning():
            QMessageBox.information(
                self,
                tr('main.enrichment_in_progress_title'),
                tr('main.enrichment_close_wait'),
            )
            event.ignore()
            return
        if self.batch_enrichment_active or self.batch_timer.isActive():
            QMessageBox.information(
                self,
                tr('main.batch_close_wait_title'),
                tr('main.batch_close_wait'),
            )
            event.ignore()
            return
        if self.login_thread and self.login_thread.isRunning():
            QMessageBox.information(
                self,
                tr('main.login_in_progress_title'),
                tr('main.login_close_wait'),
            )
            event.ignore()
            return
        self.stop_owned_backend()
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
