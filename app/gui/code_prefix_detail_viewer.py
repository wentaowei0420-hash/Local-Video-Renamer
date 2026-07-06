from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from app.core.ladder_board import LADDER_BOARD_CODE_PREFIX, LADDER_TIERS
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_analysis_viewer import _build_refresh_client
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary, format_update_frequency_summary
from app.gui.i18n import tr
from app.gui.video_category_batch_action_widget import VideoCategoryBatchActionWidget
from app.gui.video_category_update_events import video_category_update_event_bus
from app.gui.video_filter_events import video_filter_event_bus
from app.gui.video_list_detail_viewer import VideoListDetailWindow


class CodePrefixDetailViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, prefix, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self._init_async_task_host()
        self._init_deferred_reload(self._perform_deferred_load)
        video_filter_event_bus.rules_saved.connect(self.on_filter_rules_saved)
        video_category_update_event_bus.categories_updated.connect(self.on_video_categories_updated)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('code_prefix.detail.title', prefix=self.prefix))
        self.resize(1380, 920)

        root_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QGroupBox()
        content.setStyleSheet('QGroupBox { border: 0; margin-top: 0; }')
        scroll_area.setWidget(content)

        layout = QVBoxLayout(content)

        action_group = QGroupBox(tr('detail.action_group'))
        action_group.setStyleSheet(
            'QGroupBox { margin-top: 14px; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }'
        )
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(12, 18, 12, 10)
        action_layout.setSpacing(10)
        self.btn_prev_item = QPushButton(tr('detail.prev_item'))
        self.btn_prev_item.clicked.connect(self.show_previous_item)
        action_layout.addWidget(self.btn_prev_item)
        self.btn_next_item = QPushButton(tr('detail.next_item'))
        self.btn_next_item.clicked.connect(self.show_next_item)
        action_layout.addWidget(self.btn_next_item)
        self.btn_copy_prefix = QPushButton(tr('code_prefix.detail.copy_prefix'))
        self.btn_copy_prefix.clicked.connect(self.copy_prefix)
        action_layout.addWidget(self.btn_copy_prefix)
        self.btn_open_web = QPushButton(tr('detail.open_web'))
        self.btn_open_web.clicked.connect(self.open_web_page)
        action_layout.addWidget(self.btn_open_web)
        self.tier_combo = QComboBox()
        for tier in LADDER_TIERS:
            self.tier_combo.addItem(tier, tier)
        self.tier_combo.setMinimumHeight(30)
        self.tier_combo.setMinimumWidth(78)
        action_layout.addWidget(self.tier_combo)
        self.btn_update_tier = QPushButton(tr('detail.update_tier'))
        self.btn_update_tier.clicked.connect(self.update_ladder_tier)
        action_layout.addWidget(self.btn_update_tier)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        action_layout.addWidget(self.btn_refresh)
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        action_layout.addWidget(self.last_refreshed_label)
        for button in (
            self.btn_prev_item,
            self.btn_next_item,
            self.btn_copy_prefix,
            self.btn_open_web,
            self.btn_update_tier,
            self.btn_refresh,
        ):
            button.setMinimumHeight(30)
            button.setMinimumWidth(92)
        action_layout.addStretch()

        summary_group = QGroupBox(tr('code_prefix.detail.summary_group'))
        summary_layout = QVBoxLayout(summary_group)
        self.summary_grid = DetailSummaryGrid(columns=5)
        self.summary_grid.set_items(
            [
                ('prefix', tr('code_prefix.detail.prefix'), ''),
                ('ladder_tier', tr('code_prefix.detail.ladder_tier'), ''),
                ('update_status', tr('code_prefix.detail.update_status'), ''),
                ('video_count', tr('code_prefix.detail.video_count'), ''),
                ('total_pages', tr('code_prefix.detail.total_pages'), ''),
                ('total_videos', tr('code_prefix.detail.total_videos'), ''),
                ('eligible_video_count', tr('code_prefix.detail.eligible_video_count'), ''),
                ('eligible_enriched_video_count', tr('code_prefix.detail.eligible_enriched_video_count'), ''),
                ('earliest_date', tr('code_prefix.detail.earliest_date'), ''),
                ('latest_date', tr('code_prefix.detail.latest_date'), ''),
            ]
        )
        summary_layout.addWidget(self.summary_grid)
        self.last_enriched_grid = DetailSummaryGrid(columns=1)
        self.last_enriched_grid.set_items(
            [
                ('last_enriched', tr('code_prefix.detail.last_enriched'), ''),
                ('update_frequency', tr('code_prefix.detail.update_frequency'), ''),
            ]
        )
        summary_layout.addWidget(self.last_enriched_grid)

        stats_group = QGroupBox(tr('code_prefix.detail.stats_group'))
        stats_layout = QVBoxLayout(stats_group)
        self.stats_grid = DetailSummaryGrid(columns=1)
        self.stats_grid.set_items(
            [
                ('year_distribution', tr('code_prefix.detail.year_distribution'), ''),
                ('top_actors', tr('code_prefix.detail.top_actors'), ''),
                ('video_categories', tr('code_prefix.detail.video_categories'), ''),
            ]
        )
        stats_layout.addWidget(self.stats_grid)
        self.category_batch_widget = VideoCategoryBatchActionWidget()
        self.category_batch_widget.apply_button.clicked.connect(self.apply_uncategorized_video_category)
        stats_layout.addWidget(self.category_batch_widget)

        local_movie_group = QGroupBox(tr('code_prefix.detail.local_movie_group'))
        local_movie_layout = QVBoxLayout(local_movie_group)
        self.local_movie_count_label = QLabel(tr('code_prefix.detail.local_movie_count', count=0))
        self.btn_local_movie_detail = QPushButton(tr('code_prefix.detail.detail'))
        self.btn_local_movie_detail.clicked.connect(self.show_local_movie_detail)
        local_movie_top_layout = QHBoxLayout()
        local_movie_top_layout.addWidget(self.local_movie_count_label)
        local_movie_top_layout.addStretch()
        local_movie_top_layout.addWidget(self.btn_local_movie_detail)
        local_movie_layout.addLayout(local_movie_top_layout)

        movie_group = QGroupBox(tr('code_prefix.detail.movie_group'))
        movie_layout = QVBoxLayout(movie_group)
        self.movie_count_label = QLabel(tr('code_prefix.detail.movie_count', count=0))
        self.btn_movie_detail = QPushButton(tr('code_prefix.detail.detail'))
        self.btn_movie_detail.clicked.connect(self.show_movie_detail)
        movie_top_layout = QHBoxLayout()
        movie_top_layout.addWidget(self.movie_count_label)
        movie_top_layout.addStretch()
        movie_top_layout.addWidget(self.btn_movie_detail)
        movie_layout.addLayout(movie_top_layout)

        layout.addWidget(action_group)
        layout.addWidget(summary_group)
        layout.addWidget(stats_group)
        layout.addWidget(local_movie_group)
        layout.addWidget(movie_group)
        layout.addStretch()
        self.set_async_busy_widgets(
            [
                self.btn_prev_item,
                self.btn_next_item,
                self.btn_copy_prefix,
                self.btn_open_web,
                self.tier_combo,
                self.btn_update_tier,
                self.btn_refresh,
                self.btn_local_movie_detail,
                self.btn_movie_detail,
                self.category_batch_widget.apply_button,
                self.category_batch_widget.combo,
            ]
        )

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            self._deferred_force_refresh = self._deferred_force_refresh or bool(force_refresh)
            self.schedule_deferred_reload(0)
            return
        self.start_async_task(
            lambda: self._load_detail_payload(force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _perform_deferred_load(self):
        force_refresh = self._deferred_force_refresh
        self._deferred_force_refresh = False
        self.load_data(force_refresh=force_refresh)

    def _load_detail_payload(self, force_refresh=False):
        if hasattr(self.refresh_client, 'get_code_prefix_detail_snapshot'):
            return self.refresh_client.get_code_prefix_detail_snapshot(self.prefix, force_refresh=force_refresh)
        detail = self.backend_client.get_code_prefix_detail(self.prefix)
        return {
            'prefix_detail': dict(detail or {}),
            'refreshed_at': '',
            'cache_hit': False,
        }

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.detail = dict(payload.get('prefix_detail', payload.get('detail', payload or {})) or {})
        self.last_refreshed_label.setText(
            tr('data_center.last_refreshed', value=str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty'))
        )
        self._apply_detail_to_widgets()
        if self._startup_refresh_pending:
            self._startup_refresh_pending = False
            if bool(payload.get('cache_hit')):
                self.load_data(force_refresh=True)

    def _apply_detail_to_widgets(self):
        self.summary_grid.set_value('prefix', self.detail.get('prefix', ''))
        self.summary_grid.set_value('ladder_tier', self.detail.get('ladder_tier', '') or tr('common.empty'))
        self.summary_grid.set_value(
            'update_status',
            tr(f"detail.update_status.{self.detail.get('update_status', 'inactive')}"),
        )
        self.summary_grid.set_value('video_count', str(self.detail.get('video_count', 0)))
        self.summary_grid.set_value('total_pages', str(self.detail.get('avfan_total_pages', 0)))
        self.summary_grid.set_value('total_videos', str(self.detail.get('avfan_total_videos', 0)))
        self.summary_grid.set_value('eligible_video_count', str(self.detail.get('eligible_video_count', 0)))
        self.summary_grid.set_value(
            'eligible_enriched_video_count',
            str(self.detail.get('eligible_enriched_video_count', 0)),
        )
        self.summary_grid.set_value('earliest_date', self.detail.get('earliest_release_date', '') or tr('common.empty'))
        self.summary_grid.set_value('latest_date', self.detail.get('latest_release_date', '') or tr('common.empty'))
        self.last_enriched_grid.set_value('last_enriched', self.detail.get('last_enriched_at', '') or tr('common.empty'))
        self.last_enriched_grid.set_value(
            'update_frequency',
            format_update_frequency_summary(self.detail.get('update_frequency', {})),
        )
        self.stats_grid.set_value(
            'year_distribution',
            format_distribution_summary(self.detail.get('year_distribution', []), 'year', items_per_line=10),
        )
        self.stats_grid.set_value(
            'top_actors',
            format_distribution_summary(self.detail.get('top_actors', []), 'name', items_per_line=7),
        )
        self.stats_grid.set_value(
            'video_categories',
            format_distribution_summary(self.detail.get('video_category_distribution', []), 'name', items_per_line=4),
        )
        self.category_batch_widget.set_busy(False)
        self.category_batch_widget.set_uncategorized_count(
            self.detail.get('uncategorized_eligible_video_count', 0)
        )

        local_rows = list(self.detail.get('local_videos', []) or [])
        rows = list(self.detail.get('movies', []) or [])
        self.local_movie_count_label.setText(tr('code_prefix.detail.local_movie_count', count=len(local_rows)))
        self.movie_count_label.setText(tr('code_prefix.detail.movie_count', count=len(rows)))
        self.btn_local_movie_detail.setEnabled(bool(local_rows))
        self.btn_movie_detail.setEnabled(bool(rows))
        self.btn_open_web.setEnabled(bool(str(self.detail.get('web_url', '') or '').strip()))
        self._sync_tier_combo()
        self._refresh_navigation_buttons()

    def copy_prefix(self):
        prefix = str(self.detail.get('prefix', '') or self.prefix).strip().upper()
        if prefix:
            QApplication.clipboard().setText(prefix)

    def open_web_page(self):
        target_url = str(self.detail.get('web_url', '') or '').strip()
        if not target_url:
            QMessageBox.information(self, tr('common.no_data'), tr('detail.open_web_missing'))
            return
        if not QDesktopServices.openUrl(QUrl(target_url)):
            QMessageBox.warning(self, tr('common.operation_failed'), tr('detail.open_web_failed', url=target_url))

    def show_previous_item(self):
        self._jump_to_neighbor(-1)

    def show_next_item(self):
        self._jump_to_neighbor(1)

    def update_ladder_tier(self):
        selected_tier = str(self.tier_combo.currentData() or '').strip().upper()
        if not selected_tier:
            return
        try:
            self.backend_client.admit_ladder_entry(LADDER_BOARD_CODE_PREFIX, self.prefix, selected_tier)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), str(exc))
            return
        self.detail['ladder_tier'] = selected_tier
        self.summary_grid.set_value('ladder_tier', selected_tier)
        self._refresh_parent_after_tier_update()
        QMessageBox.information(
            self,
            tr('common.save_success'),
            tr('detail.update_tier_completed', tier=selected_tier),
        )

    def apply_uncategorized_video_category(self):
        selected_category = self.category_batch_widget.selected_category()
        if not selected_category:
            QMessageBox.information(
                self,
                tr('common.prompt'),
                tr('code_prefix.detail.category_batch_select_first'),
            )
            return

        pending_count = int(self.detail.get('uncategorized_eligible_video_count', 0) or 0)
        if pending_count <= 0:
            QMessageBox.information(
                self,
                tr('common.no_data'),
                tr('code_prefix.detail.category_batch_empty'),
            )
            return

        self.category_batch_widget.set_busy(True)
        try:
            result = self.backend_client.update_code_prefix_uncategorized_video_category(self.prefix, selected_category)
        except Exception as exc:
            self.category_batch_widget.set_busy(False)
            QMessageBox.critical(
                self,
                tr('common.operation_failed'),
                tr('code_prefix.detail.category_batch_failed', error=exc),
            )
            return

        video_category_update_event_bus.categories_updated.emit()
        QMessageBox.information(
            self,
            tr('code_prefix.detail.category_batch_completed_title'),
            tr(
                'code_prefix.detail.category_batch_completed',
                count=int((result or {}).get('matched_count', 0) or 0),
                category=selected_category,
            ),
        )

    def show_local_movie_detail(self):
        rows = list(self.detail.get('local_videos', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('code_prefix.detail.local_movie_no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('code_prefix.detail.local_movie_title', prefix=self.prefix),
            table_title=tr('code_prefix.detail.local_movie_table_title', prefix=self.prefix),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def show_movie_detail(self):
        rows = list(self.detail.get('movies', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('code_prefix.detail.no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('code_prefix.detail.movie_title', prefix=self.prefix),
            table_title=tr('code_prefix.detail.movie_table_title', prefix=self.prefix),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def on_filter_rules_saved(self):
        if self.isVisible():
            self.load_data(force_refresh=True)

    def on_video_categories_updated(self):
        if self.isVisible():
            self.load_data(force_refresh=True)

    def _detail_host(self):
        detail_host = self.parent()
        if detail_host is None or not hasattr(detail_host, 'neighbor_detail_key'):
            return None
        return detail_host

    def _refresh_navigation_buttons(self):
        detail_host = self._detail_host()
        if detail_host is None:
            self.btn_prev_item.setEnabled(False)
            self.btn_next_item.setEnabled(False)
            return
        self.btn_prev_item.setEnabled(bool(detail_host.neighbor_detail_key(self.prefix, -1)))
        self.btn_next_item.setEnabled(bool(detail_host.neighbor_detail_key(self.prefix, 1)))

    def _jump_to_neighbor(self, offset):
        detail_host = self._detail_host()
        if detail_host is None:
            self._refresh_navigation_buttons()
            return
        target_prefix = detail_host.neighbor_detail_key(self.prefix, offset)
        if target_prefix:
            self._switch_prefix(target_prefix)
            return
        self._refresh_navigation_buttons()

    def _switch_prefix(self, prefix):
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self.setWindowTitle(tr('code_prefix.detail.title', prefix=self.prefix))
        if hasattr(self.parent(), 'select_prefix_row'):
            self.parent().select_prefix_row(self.prefix)
        self.load_data()

    def _sync_tier_combo(self):
        current_tier = str((self.detail or {}).get('ladder_tier', '') or '').strip().upper()
        combo_index = self.tier_combo.findData(current_tier or LADDER_TIERS[0])
        self.tier_combo.setCurrentIndex(max(combo_index, 0))

    def _refresh_parent_after_tier_update(self):
        parent = self.parent()
        if hasattr(parent, 'load_board'):
            parent.load_board()
            return
        if hasattr(parent, 'load_data'):
            parent.load_data(force_refresh=True)
