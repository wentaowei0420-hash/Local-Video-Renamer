from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialog, QGridLayout, QGroupBox, QVBoxLayout

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, CODE_PREFIX_LIBRARY_TARGET, VIDEO_LIBRARY_TARGET
from app.gui.enrichment_summary_widgets import SummaryCard
from app.gui.i18n import tr


class DataCenterWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.load_data)
        self.init_ui()
        self.load_data()
        self.refresh_timer.start()

    def init_ui(self):
        self.setWindowTitle(tr('data_center.title'))
        self.resize(1240, 520)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        summary_group = QGroupBox(tr('data_center.progress_group'))
        summary_layout = QGridLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)

        self.video_avfan_card = SummaryCard(tr('data_center.video_avfan'))
        self.video_javtxt_card = SummaryCard(tr('data_center.video_javtxt'))
        self.code_prefix_avfan_card = SummaryCard(tr('data_center.code_prefix_avfan'))
        self.code_prefix_javtxt_card = SummaryCard(tr('data_center.code_prefix_javtxt'))
        self.actor_avfan_card = SummaryCard(tr('data_center.actor_avfan'))
        self.actor_javtxt_card = SummaryCard(tr('data_center.actor_javtxt'))

        summary_layout.addWidget(self.video_avfan_card, 0, 0)
        summary_layout.addWidget(self.video_javtxt_card, 0, 1)
        summary_layout.addWidget(self.code_prefix_avfan_card, 1, 0)
        summary_layout.addWidget(self.code_prefix_javtxt_card, 1, 1)
        summary_layout.addWidget(self.actor_avfan_card, 2, 0)
        summary_layout.addWidget(self.actor_javtxt_card, 2, 1)

        layout.addWidget(summary_group)
        self.setLayout(layout)

    def load_data(self):
        try:
            summary = self.backend_client.get_data_center_summary() or {}
        except Exception as exc:
            print(tr('data_center.read_failed', error=exc))
            return

        try:
            progress = self.backend_client.get_enrichment_progress() or {}
        except Exception:
            progress = {}

        live_progress_map = self._build_live_progress_map(progress)
        video_summary = summary.get('video_library', {}).get('sources', {})
        code_prefix_summary = summary.get('code_prefix_library', {}).get('sources', {})
        actor_summary = summary.get('actor_library', {}).get('sources', {})

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
        self.code_prefix_avfan_card.set_summary(
            code_prefix_summary.get(AVFAN_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((CODE_PREFIX_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE)),
        )
        self.code_prefix_javtxt_card.set_summary(
            code_prefix_summary.get(JAVTXT_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((CODE_PREFIX_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE)),
        )
        self.actor_avfan_card.set_summary(
            actor_summary.get(AVFAN_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE)),
        )
        self.actor_javtxt_card.set_summary(
            actor_summary.get(JAVTXT_VIDEO_SOURCE, {}),
            live_progress=live_progress_map.get((ACTOR_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE)),
        )

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
