from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
)
from app.core.enrichment_targets import (
    ACTOR_BIRTHDAY_TARGET,
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_analysis_viewer import DataAnalysisWindow, _build_refresh_client
from app.gui.enrichment_summary_widgets import SummaryCard
from app.gui.i18n import tr


class DataCenterWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self._pending_close = False
        self._startup_refresh_pending = True
        self.analysis_window = None
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('data_center.title'))
        self.resize(1240, 640)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        self.last_refresh_duration_label = QLabel(tr('common.duration', value=tr('common.empty')))
        self.btn_analysis = QPushButton(tr('data_center.analysis.entry'))
        self.btn_analysis.clicked.connect(self.show_analysis_window)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.last_refreshed_label)
        top_layout.addWidget(self.last_refresh_duration_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_analysis)
        top_layout.addWidget(self.btn_refresh)
        layout.addLayout(top_layout)

        summary_group = QGroupBox(tr('data_center.progress_group'))
        summary_layout = QGridLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)

        self.video_avfan_card = SummaryCard(tr('data_center.video_avfan'))
        self.video_javtxt_card = SummaryCard(tr('data_center.video_javtxt'))
        self.video_supplement_card = SummaryCard(tr('data_center.video_supplement'))
        self.code_prefix_avfan_card = SummaryCard(tr('data_center.code_prefix_avfan'))
        self.code_prefix_javtxt_card = SummaryCard(tr('data_center.code_prefix_javtxt'))
        self.code_prefix_supplement_card = SummaryCard(tr('data_center.code_prefix_supplement'))
        self.actor_avfan_card = SummaryCard(tr('data_center.actor_avfan'))
        self.actor_javtxt_card = SummaryCard(tr('data_center.actor_javtxt'))
        self.actor_binghuo_card = SummaryCard(tr('data_center.actor_binghuo'))
        self.actor_baomu_card = SummaryCard(tr('data_center.actor_baomu'))
        self.actor_supplement_card = SummaryCard(tr('data_center.actor_supplement'))

        summary_layout.addWidget(self.video_avfan_card, 0, 0)
        summary_layout.addWidget(self.video_javtxt_card, 0, 1)
        summary_layout.addWidget(self.video_supplement_card, 0, 2)
        summary_layout.addWidget(self.code_prefix_avfan_card, 1, 0)
        summary_layout.addWidget(self.code_prefix_javtxt_card, 1, 1)
        summary_layout.addWidget(self.code_prefix_supplement_card, 1, 2)
        summary_layout.addWidget(self.actor_avfan_card, 2, 0)
        summary_layout.addWidget(self.actor_javtxt_card, 2, 1)
        summary_layout.addWidget(self.actor_supplement_card, 2, 2)
        summary_layout.addWidget(self.actor_binghuo_card, 3, 0)
        summary_layout.addWidget(self.actor_baomu_card, 3, 1)

        layout.addWidget(summary_group)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_refresh, self.btn_analysis])

    def load_data(self, force_refresh=False):
        if self._pending_close or self.is_async_task_running():
            return

        self.start_async_task(
            lambda: {
                **dict(self.refresh_client.get_data_center_summary(force_refresh=force_refresh) or {}),
                'progress': self.refresh_client.get_enrichment_progress() or {},
            },
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        result = dict(result or {})
        if self._pending_close:
            return
        summary = result.get('summary', {}) or {}
        refreshed_at = str(result.get('refreshed_at', '') or '').strip() or tr('common.empty')
        refresh_duration_text = str(result.get('refresh_duration_text', '') or '').strip() or tr('common.empty')
        progress = result.get('progress', {}) or {}
        live_progress_map = self._build_live_progress_map(progress)
        video_summary = summary.get('video_library', {}).get('sources', {})
        code_prefix_summary = summary.get('code_prefix_library', {}).get('sources', {})
        actor_summary = summary.get('actor_library', {}).get('sources', {})
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self.last_refresh_duration_label.setText(tr('common.duration', value=refresh_duration_text))

        self.video_avfan_card.set_summary(
            video_summary.get(AVFAN_VIDEO_SOURCE, {}),
            show_terminal_details=True,
            live_progress=live_progress_map.get((VIDEO_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE)),
        )
        self.video_javtxt_card.set_summary(
            video_summary.get(JAVTXT_VIDEO_SOURCE, {}),
            show_terminal_details=True,
            live_progress=live_progress_map.get((VIDEO_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE)),
        )
        self.video_supplement_card.set_summary(
            video_summary.get(SUPPLEMENT_TASK_SOURCE, {}),
            show_terminal_details=False,
            live_progress=live_progress_map.get((VIDEO_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE)),
        )
        self.code_prefix_avfan_card.set_summary(
            code_prefix_summary.get(AVFAN_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((CODE_PREFIX_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE)),
        )
        self.code_prefix_javtxt_card.set_summary(
            code_prefix_summary.get(JAVTXT_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((CODE_PREFIX_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE)),
        )
        self.code_prefix_supplement_card.set_summary(
            code_prefix_summary.get(SUPPLEMENT_TASK_SOURCE, {}),
            show_terminal_details=False,
            live_progress=live_progress_map.get((CODE_PREFIX_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE)),
        )
        self.actor_avfan_card.set_summary(
            actor_summary.get(AVFAN_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE)),
        )
        self.actor_javtxt_card.set_summary(
            actor_summary.get(JAVTXT_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE)),
        )
        self.actor_supplement_card.set_summary(
            actor_summary.get(SUPPLEMENT_TASK_SOURCE, {}),
            show_terminal_details=False,
            live_progress=live_progress_map.get((ACTOR_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE)),
        )
        self.actor_binghuo_card.set_summary(
            actor_summary.get(BINGHUO_ACTOR_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_BIRTHDAY_TARGET, BINGHUO_ACTOR_SOURCE)),
        )
        self.actor_baomu_card.set_summary(
            actor_summary.get(BAOMU_ACTOR_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_BIRTHDAY_TARGET, BAOMU_ACTOR_SOURCE)),
        )
        if self._startup_refresh_pending:
            self._startup_refresh_pending = False
            self.load_data(force_refresh=True)

    def _handle_async_task_failed(self, message):
        if self._pending_close:
            return
        print(tr('data_center.read_failed', error=message))

    def _cleanup_async_task_thread(self):
        super()._cleanup_async_task_thread()
        if self._pending_close:
            self.accept()

    def closeEvent(self, event):
        self._pending_close = True
        if self.is_async_task_running():
            event.ignore()
            return
        super().closeEvent(event)

    def show_analysis_window(self):
        self.analysis_window = DataAnalysisWindow(self.backend_client, self)
        self.analysis_window.show()

    def _build_live_progress_map(self, progress):
        live_progress_map = {}
        progress = dict(progress or {})
        if progress.get('task_kind') == 'combo':
            for task_state in (progress.get('subtasks', {}) or {}).values():
                self._register_live_progress(live_progress_map, task_state)
            return live_progress_map

        self._register_live_progress(live_progress_map, progress)
        return live_progress_map

    @staticmethod
    def _register_live_progress(live_progress_map, progress_state):
        progress_state = dict(progress_state or {})
        target_type = str(progress_state.get('target_type', '') or '').strip()
        source_key = str(progress_state.get('source_key', '') or '').strip()
        total_count = int(progress_state.get('total_count', 0) or 0)
        processed_count = int(progress_state.get('processed_count', 0) or 0)
        is_running = bool(progress_state.get('is_running'))
        message = str(progress_state.get('message', '') or '').strip()
        current_item = str(progress_state.get('current_item', '') or '').strip()

        if not target_type or not source_key:
            return
        if not is_running and total_count <= 0 and processed_count <= 0 and not message and not current_item:
            return

        live_progress_map[(target_type, source_key)] = progress_state
