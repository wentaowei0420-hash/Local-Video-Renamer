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


class ActorDetailViewerWindow(QDialog):
    def __init__(self, backend_client, actor_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.actor_name = actor_name
        self.detail = {}
        video_filter_event_bus.rules_saved.connect(self.on_filter_rules_saved)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('actor.detail.title', actor_name=self.actor_name))
        self.resize(1380, 980)

        root_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QGroupBox()
        content.setStyleSheet('QGroupBox { border: 0; margin-top: 0; }')
        scroll_area.setWidget(content)

        layout = QVBoxLayout(content)

        basic_group = QGroupBox(tr('actor.detail.basic_group'))
        basic_layout = QVBoxLayout(basic_group)
        self.basic_grid = DetailSummaryGrid(columns=2)
        self.basic_grid.set_items(
            [
                ('name', tr('actor.detail.name'), ''),
                ('actor_id', tr('actor.detail.actor_id'), ''),
                ('age', tr('actor.detail.age'), ''),
                ('birthday', tr('actor.detail.birthday'), ''),
                ('local_total', tr('actor.detail.local_total'), ''),
            ]
        )
        basic_layout.addWidget(self.basic_grid)

        local_group = QGroupBox(tr('actor.detail.local_group'))
        local_layout = QVBoxLayout(local_group)
        self.local_grid = DetailSummaryGrid(columns=1)
        self.local_grid.set_items(
            [
                ('local_prefix', tr('actor.detail.local_prefix'), ''),
                ('local_year', tr('actor.detail.local_year'), ''),
            ]
        )
        local_layout.addWidget(self.local_grid)

        web_group = QGroupBox(tr('actor.detail.web_group'))
        web_layout = QVBoxLayout(web_group)
        self.web_grid = DetailSummaryGrid(columns=2)
        self.web_grid.set_items(
            [
                ('web_status', tr('actor.detail.web_status'), ''),
                ('web_total', tr('actor.detail.web_total'), ''),
                ('web_pages', tr('actor.detail.web_pages'), ''),
                ('eligible_video_count', tr('actor.detail.eligible_video_count'), ''),
                ('web_earliest', tr('actor.detail.web_earliest'), ''),
                ('web_latest', tr('actor.detail.web_latest'), ''),
                ('eligible_enriched_video_count', tr('actor.detail.eligible_enriched_video_count'), ''),
                ('web_last_enriched', tr('actor.detail.web_last_enriched'), ''),
                ('web_prefix', tr('actor.detail.web_prefix'), ''),
                ('web_year', tr('actor.detail.web_year'), ''),
            ]
        )
        web_layout.addWidget(self.web_grid)

        local_movie_group = QGroupBox(tr('actor.detail.local_movie_group'))
        local_movie_layout = QVBoxLayout(local_movie_group)
        self.local_movie_count_label = QLabel(tr('actor.detail.local_movie_count', count=0))
        self.btn_local_movie_detail = QPushButton(tr('actor.detail.detail'))
        self.btn_local_movie_detail.clicked.connect(self.show_local_movie_detail)
        local_movie_top_layout = QHBoxLayout()
        local_movie_top_layout.addWidget(self.local_movie_count_label)
        local_movie_top_layout.addStretch()
        local_movie_top_layout.addWidget(self.btn_local_movie_detail)
        local_movie_layout.addLayout(local_movie_top_layout)

        web_movie_group = QGroupBox(tr('actor.detail.web_movie_group'))
        web_movie_layout = QVBoxLayout(web_movie_group)
        self.web_movie_count_label = QLabel(tr('actor.detail.web_movie_count', count=0))
        self.btn_web_movie_detail = QPushButton(tr('actor.detail.detail'))
        self.btn_web_movie_detail.clicked.connect(self.show_web_movie_detail)
        web_movie_top_layout = QHBoxLayout()
        web_movie_top_layout.addWidget(self.web_movie_count_label)
        web_movie_top_layout.addStretch()
        web_movie_top_layout.addWidget(self.btn_web_movie_detail)
        web_movie_layout.addLayout(web_movie_top_layout)

        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addWidget(local_movie_group)
        layout.addWidget(web_movie_group)
        layout.addStretch()

    def load_data(self):
        try:
            self.detail = self.backend_client.get_actor_detail(self.actor_name)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.read_failed'), tr('actor.detail.read_failed', error=exc))
            self.reject()
            return

        self.basic_grid.set_value('name', self.detail.get('name', ''))
        self.basic_grid.set_value('actor_id', self.detail.get('actor_id', '') or tr('common.empty'))
        self.basic_grid.set_value('age', self.detail.get('age', '') or tr('common.empty'))
        self.basic_grid.set_value('birthday', self.detail.get('birthday', '') or tr('common.empty'))
        self.basic_grid.set_value('local_total', str(self.detail.get('local_video_count', 0)))

        self.local_grid.set_value(
            'local_prefix',
            format_distribution_summary(self.detail.get('local_prefix_distribution', []), 'prefix', items_per_line=3),
        )
        self.local_grid.set_value(
            'local_year',
            format_distribution_summary(self.detail.get('local_year_distribution', []), 'year', items_per_line=3),
        )

        self.web_grid.set_value('web_status', self.detail.get('web_enrichment_status', '') or tr('actor.detail.web_status_default'))
        self.web_grid.set_value('web_total', str(self.detail.get('web_total_videos', 0)))
        self.web_grid.set_value('web_pages', str(self.detail.get('web_total_pages', 0)))
        self.web_grid.set_value('eligible_video_count', str(self.detail.get('eligible_video_count', 0)))
        self.web_grid.set_value('web_earliest', self.detail.get('web_earliest_release_date', '') or tr('common.empty'))
        self.web_grid.set_value('web_latest', self.detail.get('web_latest_release_date', '') or tr('common.empty'))
        self.web_grid.set_value(
            'eligible_enriched_video_count',
            str(self.detail.get('eligible_enriched_video_count', 0)),
        )
        self.web_grid.set_value('web_last_enriched', self.detail.get('web_last_enriched_at', '') or tr('common.empty'))
        self.web_grid.set_value(
            'web_prefix',
            format_distribution_summary(self.detail.get('web_prefix_distribution', []), 'prefix', items_per_line=3),
        )
        self.web_grid.set_value(
            'web_year',
            format_distribution_summary(self.detail.get('web_year_distribution', []), 'year', items_per_line=3),
        )

        local_rows = list(self.detail.get('local_videos', []) or [])
        web_rows = list(self.detail.get('web_movies', []) or [])
        self.local_movie_count_label.setText(tr('actor.detail.local_movie_count', count=len(local_rows)))
        self.web_movie_count_label.setText(tr('actor.detail.web_movie_count', count=len(web_rows)))
        self.btn_local_movie_detail.setEnabled(bool(local_rows))
        self.btn_web_movie_detail.setEnabled(bool(web_rows))

    def show_local_movie_detail(self):
        rows = list(self.detail.get('local_videos', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('actor.detail.local_movie_no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('actor.detail.local_movie_title', actor_name=self.actor_name),
            table_title=tr('actor.detail.local_movie_table_title', actor_name=self.actor_name),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def show_web_movie_detail(self):
        rows = list(self.detail.get('web_movies', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('actor.detail.web_movie_no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('actor.detail.web_movie_title', actor_name=self.actor_name),
            table_title=tr('actor.detail.web_movie_table_title', actor_name=self.actor_name),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def on_filter_rules_saved(self):
        if self.isVisible():
            self.load_data()
