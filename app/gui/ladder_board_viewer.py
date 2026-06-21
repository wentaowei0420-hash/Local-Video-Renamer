from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_VIEW_CANDIDATES,
    LADDER_VIEW_SELECTED,
)
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.i18n import tr
from app.gui.ladder_candidate_panel import LadderCandidatePanel
from app.gui.ladder_selected_panel import LadderSelectedPanel


class LadderBoardWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.current_board_key = LADDER_BOARD_ACTOR
        self.current_view_key = LADDER_VIEW_CANDIDATES
        self.current_board_data = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_board()

    def init_ui(self):
        self.setWindowTitle(tr('ladder.title'))
        self.resize(1260, 760)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)

        board_toggle_layout = QHBoxLayout()
        self.btn_actor_board = QPushButton(tr('ladder.board_actor'))
        self.btn_actor_board.setCheckable(True)
        self.btn_actor_board.clicked.connect(lambda: self.switch_board(LADDER_BOARD_ACTOR))
        self.btn_code_prefix_board = QPushButton(tr('ladder.board_code_prefix'))
        self.btn_code_prefix_board.setCheckable(True)
        self.btn_code_prefix_board.clicked.connect(lambda: self.switch_board(LADDER_BOARD_CODE_PREFIX))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_board(force_refresh=True))
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        board_toggle_layout.addWidget(self.btn_actor_board)
        board_toggle_layout.addWidget(self.btn_code_prefix_board)
        board_toggle_layout.addStretch()
        board_toggle_layout.addWidget(self.last_refreshed_label)
        board_toggle_layout.addWidget(self.btn_refresh)

        view_toggle_layout = QHBoxLayout()
        self.btn_candidates = QPushButton(tr('ladder.view_candidates'))
        self.btn_candidates.setCheckable(True)
        self.btn_candidates.clicked.connect(lambda: self.switch_view(LADDER_VIEW_CANDIDATES))
        self.btn_selected = QPushButton(tr('ladder.view_selected'))
        self.btn_selected.setCheckable(True)
        self.btn_selected.clicked.connect(lambda: self.switch_view(LADDER_VIEW_SELECTED))
        self.summary_label = QLabel('')
        view_toggle_layout.addWidget(self.btn_candidates)
        view_toggle_layout.addWidget(self.btn_selected)
        view_toggle_layout.addStretch()
        view_toggle_layout.addWidget(self.summary_label)

        self.stacked_widget = QStackedWidget()
        self.candidate_panel = LadderCandidatePanel(self)
        self.selected_panel = LadderSelectedPanel(self)
        self.candidate_panel.admit_requested.connect(self.admit_entry)
        self.candidate_panel.detail_requested.connect(self.show_detail)
        self.selected_panel.medal_save_requested.connect(self.save_medal)
        self.selected_panel.detail_requested.connect(self.show_detail)
        self.stacked_widget.addWidget(self.candidate_panel)
        self.stacked_widget.addWidget(self.selected_panel)

        layout.addLayout(board_toggle_layout)
        layout.addLayout(view_toggle_layout)
        layout.addWidget(self.stacked_widget)

        self.set_async_busy_widgets(
            [
                self.btn_actor_board,
                self.btn_code_prefix_board,
                self.btn_candidates,
                self.btn_selected,
                self.btn_refresh,
            ]
        )
        self._refresh_toggle_states()

    def switch_board(self, board_key):
        if self.is_async_task_running() or board_key == self.current_board_key:
            self._refresh_toggle_states()
            return
        self.current_board_key = board_key
        self._refresh_toggle_states()
        self.load_board()

    def switch_view(self, view_key):
        self.current_view_key = view_key
        self._refresh_toggle_states()
        self._apply_view()

    def load_board(self, force_refresh=False):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self.backend_client.get_ladder_board_snapshot(board_key, force_refresh=force_refresh),
            self._on_board_loaded,
            tr('common.read_failed'),
        )

    def admit_entry(self, entity_name, tier):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self._reload_board_after(lambda: self.backend_client.admit_ladder_entry(board_key, entity_name, tier)),
            self._on_board_loaded,
            tr('common.save_failed'),
        )

    def save_medal(self, entity_name, medal):
        board_key = self.current_board_key
        self.start_async_task(
            lambda: self._reload_board_after(
                lambda: self.backend_client.update_ladder_entry_medal(board_key, entity_name, medal)
            ),
            self._on_board_loaded,
            tr('common.save_failed'),
        )

    def _reload_board_after(self, operation):
        operation()
        return self.backend_client.get_ladder_board_snapshot(self.current_board_key)

    def show_detail(self, entity_name):
        if not entity_name:
            return
        entity_type = str((self.current_board_data or {}).get('entity_type', '') or '').strip()
        if entity_type == LADDER_ENTITY_ACTOR:
            viewer = ActorDetailViewerWindow(self.backend_client, entity_name, self)
        else:
            viewer = CodePrefixDetailViewerWindow(self.backend_client, entity_name, self)
        viewer.exec_()

    def _on_board_loaded(self, payload):
        payload = dict(payload or {})
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        board = dict(payload.get('board', payload) or {})
        self.current_board_data = board
        self.candidate_panel.set_rows(board.get('candidates', []) or [])
        self.selected_panel.set_rows(board.get('selected', []) or [])
        self._update_summary()
        self._apply_view()
        self._refresh_toggle_states()

    def _apply_view(self):
        self.stacked_widget.setCurrentIndex(0 if self.current_view_key == LADDER_VIEW_CANDIDATES else 1)

    def _update_summary(self):
        board_key = str((self.current_board_data or {}).get('board_key', self.current_board_key) or self.current_board_key)
        board_label = tr('ladder.board_actor') if board_key == LADDER_BOARD_ACTOR else tr('ladder.board_code_prefix')
        candidate_count = len((self.current_board_data or {}).get('candidates', []) or [])
        selected_count = len((self.current_board_data or {}).get('selected', []) or [])
        self.summary_label.setText(
            tr(
                'ladder.summary',
                board_label=board_label,
                candidate_count=candidate_count,
                selected_count=selected_count,
            )
        )

    def _refresh_toggle_states(self):
        self.btn_actor_board.setChecked(self.current_board_key == LADDER_BOARD_ACTOR)
        self.btn_code_prefix_board.setChecked(self.current_board_key == LADDER_BOARD_CODE_PREFIX)
        self.btn_candidates.setChecked(self.current_view_key == LADDER_VIEW_CANDIDATES)
        self.btn_selected.setChecked(self.current_view_key == LADDER_VIEW_SELECTED)

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
