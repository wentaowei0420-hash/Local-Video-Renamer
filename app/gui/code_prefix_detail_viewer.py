from PyQt5.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary
from app.gui.i18n import tr
from app.gui.video_filter_events import video_filter_event_bus
from app.gui.video_list_detail_viewer import VideoListDetailWindow


class CodePrefixDetailViewerWindow(QDialog):
    def __init__(self, backend_client, prefix, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        video_filter_event_bus.rules_saved.connect(self.on_filter_rules_saved)
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

        summary_group = QGroupBox(tr('code_prefix.detail.summary_group'))
        summary_layout = QVBoxLayout(summary_group)
        self.summary_grid = DetailSummaryGrid(columns=2)
        self.summary_grid.set_items(
            [
                ('prefix', tr('code_prefix.detail.prefix'), ''),
                ('video_count', tr('code_prefix.detail.video_count'), ''),
                ('total_pages', tr('code_prefix.detail.total_pages'), ''),
                ('total_videos', tr('code_prefix.detail.total_videos'), ''),
                ('eligible_video_count', tr('code_prefix.detail.eligible_video_count'), ''),
                ('eligible_enriched_video_count', tr('code_prefix.detail.eligible_enriched_video_count'), ''),
                ('earliest_date', tr('code_prefix.detail.earliest_date'), ''),
                ('latest_date', tr('code_prefix.detail.latest_date'), ''),
                ('last_enriched', tr('code_prefix.detail.last_enriched'), ''),
            ]
        )
        summary_layout.addWidget(self.summary_grid)

        stats_group = QGroupBox(tr('code_prefix.detail.stats_group'))
        stats_layout = QVBoxLayout(stats_group)
        self.stats_grid = DetailSummaryGrid(columns=1)
        self.stats_grid.set_items(
            [
                ('year_distribution', tr('code_prefix.detail.year_distribution'), ''),
                ('top_actors', tr('code_prefix.detail.top_actors'), ''),
            ]
        )
        stats_layout.addWidget(self.stats_grid)

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

        layout.addWidget(summary_group)
        layout.addWidget(stats_group)
        layout.addWidget(movie_group)
        layout.addStretch()

    def load_data(self):
        try:
            self.detail = self.backend_client.get_code_prefix_detail(self.prefix)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.read_failed'), tr('code_prefix.detail.read_failed', error=exc))
            self.reject()
            return

        self.summary_grid.set_value('prefix', self.detail.get('prefix', ''))
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
        self.summary_grid.set_value('last_enriched', self.detail.get('last_enriched_at', '') or tr('common.empty'))
        self.stats_grid.set_value(
            'year_distribution',
            format_distribution_summary(self.detail.get('year_distribution', []), 'year', items_per_line=3),
        )
        self.stats_grid.set_value(
            'top_actors',
            format_distribution_summary(self.detail.get('top_actors', []), 'name', items_per_line=2),
        )

        rows = list(self.detail.get('movies', []) or [])
        self.movie_count_label.setText(tr('code_prefix.detail.movie_count', count=len(rows)))
        self.btn_movie_detail.setEnabled(bool(rows))

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
            self.load_data()
