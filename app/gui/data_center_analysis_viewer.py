from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.actor_data_analysis import ACTOR_ANALYSIS_METRICS
from app.core.code_prefix_data_analysis import CODE_PREFIX_ANALYSIS_METRICS
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


def _build_refresh_client(backend_client, minimum_timeout=90):
    base_url = str(getattr(backend_client, 'base_url', '') or '').strip()
    if not base_url:
        return backend_client
    return BackendClient(
        base_url=base_url,
        timeout=max(int(getattr(backend_client, 'timeout', 30) or 30), minimum_timeout),
    )


def _join_items_by_line(items, items_per_line=10):
    grouped_lines = []
    items_per_line = max(1, int(items_per_line or 1))
    for start in range(0, len(items), items_per_line):
        grouped_lines.append('    '.join(items[start:start + items_per_line]))
    return '\n'.join(grouped_lines)


def _apply_uniform_widget_width(widgets, minimum_width=0):
    active_widgets = [widget for widget in list(widgets or []) if widget is not None]
    if not active_widgets:
        return
    target_width = max(widget.sizeHint().width() for widget in active_widgets)
    target_width = max(int(minimum_width or 0), int(target_width or 0))
    for widget in active_widgets:
        widget.setMinimumWidth(target_width)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


class DataAnalysisWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.analysis_windows = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr('data_center.analysis.entry_title'))
        self.resize(520, 220)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        top_label = QLabel(tr('data_center.analysis.entry_hint'))
        top_label.setWordWrap(True)
        layout.addWidget(top_label)

        button_group = QGroupBox(tr('data_center.analysis.metric_group'))
        button_layout = QGridLayout(button_group)
        button_layout.setContentsMargins(12, 12, 12, 12)
        button_layout.setHorizontalSpacing(10)
        button_layout.setVerticalSpacing(10)

        self.btn_actor_analysis = QPushButton(tr('data_center.analysis.actor_entry'))
        self.btn_actor_analysis.setMinimumHeight(36)
        self.btn_actor_analysis.clicked.connect(self.show_actor_analysis_window)
        button_layout.addWidget(self.btn_actor_analysis, 0, 0)

        self.btn_code_prefix_analysis = QPushButton(tr('data_center.analysis.code_prefix_entry'))
        self.btn_code_prefix_analysis.setMinimumHeight(36)
        self.btn_code_prefix_analysis.clicked.connect(self.show_code_prefix_analysis_window)
        button_layout.addWidget(self.btn_code_prefix_analysis, 0, 1)

        layout.addWidget(button_group)
        layout.addStretch()

    def show_actor_analysis_window(self):
        self._open_analysis_window(ActorDataAnalysisWindow(self.backend_client, self))

    def show_code_prefix_analysis_window(self):
        self._open_analysis_window(CodePrefixDataAnalysisWindow(self.backend_client, self))

    def _open_analysis_window(self, window):
        self.analysis_windows.append(window)
        window.finished.connect(lambda _result, current=window: self._forget_analysis_window(current))
        window.show()

    def _forget_analysis_window(self, window):
        self.analysis_windows = [item for item in self.analysis_windows if item is not window]


class MetricSelectionWindow(QDialog):
    def __init__(self, backend_client, analysis_type, metric_configs, title_key, hint_key, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.analysis_type = str(analysis_type or '').strip()
        self.metric_configs = tuple(metric_configs or ())
        self.title_key = str(title_key or '').strip()
        self.hint_key = str(hint_key or '').strip()
        self.metric_windows = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(tr(self.title_key))
        self.resize(720, 240)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        top_label = QLabel(tr(self.hint_key))
        top_label.setWordWrap(True)
        layout.addWidget(top_label)

        button_group = QGroupBox(tr('data_center.analysis.metric_group'))
        button_layout = QGridLayout(button_group)
        button_layout.setContentsMargins(12, 12, 12, 12)
        button_layout.setHorizontalSpacing(10)
        button_layout.setVerticalSpacing(10)

        for index, config in enumerate(self.metric_configs):
            button = QPushButton(tr(config['label_key']))
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked=False, item=dict(config): self.open_metric_window(item))
            button_layout.addWidget(button, index // 3, index % 3)

        layout.addWidget(button_group)
        layout.addStretch()

    def open_metric_window(self, metric_config):
        window = MetricAnalysisWindow(self.backend_client, self.analysis_type, metric_config, self)
        self.metric_windows.append(window)
        window.finished.connect(lambda _result, current=window: self._forget_metric_window(current))
        window.show()

    def _forget_metric_window(self, window):
        self.metric_windows = [item for item in self.metric_windows if item is not window]


class ActorDataAnalysisWindow(MetricSelectionWindow):
    def __init__(self, backend_client, parent=None):
        super().__init__(
            backend_client,
            'actor',
            ACTOR_ANALYSIS_METRICS,
            'data_center.analysis.actor_title',
            'data_center.analysis.actor_hint',
            parent=parent,
        )


class CodePrefixDataAnalysisWindow(MetricSelectionWindow):
    def __init__(self, backend_client, parent=None):
        super().__init__(
            backend_client,
            'code_prefix',
            CODE_PREFIX_ANALYSIS_METRICS,
            'data_center.analysis.code_prefix_title',
            'data_center.analysis.code_prefix_hint',
            parent=parent,
        )


class ActorMetricBucketWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, metric_config, bucket_value, bucket_label, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.metric_config = dict(metric_config or {})
        self.metric_key = str(self.metric_config.get('key', '') or '').strip()
        self.bucket_value = int(bucket_value or 0)
        self.bucket_label = str(bucket_label or '').strip()
        self.actor_rows = []
        self.detail_windows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        metric_label = tr(self.metric_config.get('label_key', ''))
        self.setWindowTitle(
            tr(
                'data_center.analysis.actor_bucket_title',
                metric_label=metric_label,
                bucket_label=self.bucket_label,
            )
        )
        self.resize(760, 620)
        self.setWindowModality(Qt.WindowModal)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        top_layout = QHBoxLayout()
        self.summary_label = QLabel(tr('data_center.analysis.actor_bucket_count', count=0))
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.summary_label)
        top_layout.addStretch()
        top_layout.addWidget(self.last_refreshed_label)
        top_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(top_layout)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        self.content_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.content_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        scroll_area.setWidget(self.content_widget)

        self.set_async_busy_widgets([self.btn_refresh])

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: self.refresh_client.get_actor_metric_bucket(
                self.metric_key,
                self.bucket_value,
                force_refresh=force_refresh,
            ),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.actor_rows = list(payload.get('actors', []) or [])
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.summary_label.setText(
            tr('data_center.analysis.actor_bucket_count', count=len(self.actor_rows))
        )
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self._render_rows()

    def _render_rows(self):
        _clear_layout(self.rows_layout)
        if not self.actor_rows:
            empty_label = QLabel(tr('common.no_data'))
            empty_label.setWordWrap(True)
            self.rows_layout.addWidget(empty_label)
            self.rows_layout.addStretch()
            return

        for row in self.actor_rows:
            actor_name = str(row.get('actor_name', '') or '').strip()
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 6, 8, 6)
            row_layout.setSpacing(10)

            name_label = QLabel(actor_name or tr('common.unknown'))
            name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_layout.addWidget(name_label)
            row_layout.addStretch()

            detail_button = QPushButton(tr('actor.detail.detail'))
            detail_button.setMinimumWidth(92)
            detail_button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))
            row_layout.addWidget(detail_button)

            self.rows_layout.addWidget(row_widget)

        self.rows_layout.addStretch()

    def show_actor_detail(self, actor_name):
        if not actor_name:
            return
        viewer = ActorDetailViewerWindow(self.backend_client, actor_name, self)
        self.detail_windows.append(viewer)
        if hasattr(viewer, 'finished'):
            viewer.finished.connect(lambda _result, current=viewer: self._forget_detail_window(current))
        viewer.show()

    def _forget_detail_window(self, window):
        self.detail_windows = [item for item in self.detail_windows if item is not window]

    def detail_navigation_keys(self):
        return [
            str((row or {}).get('actor_name', '') or '').strip()
            for row in self.actor_rows
            if str((row or {}).get('actor_name', '') or '').strip()
        ]

    def neighbor_detail_key(self, current_name, offset):
        names = self.detail_navigation_keys()
        target_name = str(current_name or '').strip()
        if target_name not in names:
            return ''
        index = names.index(target_name) + int(offset or 0)
        if index < 0 or index >= len(names):
            return ''
        return names[index]

    def select_actor_row(self, actor_name):
        return actor_name


class MetricAnalysisWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, analysis_type, metric_config, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.analysis_type = str(analysis_type or '').strip()
        self.metric_config = dict(metric_config or {})
        self.metric_key = str(self.metric_config.get('key', '') or '').strip()
        self.bucket_windows = []
        self.distribution_buttons = []
        self.ranking_item_widgets = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(
            tr(
                'data_center.analysis.metric_title',
                metric_label=tr(self.metric_config.get('label_key', '')),
            )
        )
        self.resize(1380, 760)
        self.setWindowModality(Qt.WindowModal)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        top_layout = QHBoxLayout()
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.last_refreshed_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(top_layout)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        distribution_group = QGroupBox(tr('data_center.analysis.distribution_group'))
        distribution_layout = QVBoxLayout(distribution_group)
        self.distribution_button_widget = QWidget()
        self.distribution_button_layout = QGridLayout(self.distribution_button_widget)
        self.distribution_button_layout.setContentsMargins(0, 0, 0, 0)
        self.distribution_button_layout.setHorizontalSpacing(8)
        self.distribution_button_layout.setVerticalSpacing(8)
        distribution_layout.addWidget(self.distribution_button_widget)
        self.distribution_label = QLabel(tr('common.no_data'))
        self.distribution_label.setWordWrap(True)
        self.distribution_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        distribution_layout.addWidget(self.distribution_label)
        content_layout.addWidget(distribution_group)

        ranking_group = QGroupBox(tr('data_center.analysis.ranking_group'))
        ranking_layout = QVBoxLayout(ranking_group)
        self.ranking_widget = QWidget()
        self.ranking_grid_layout = QGridLayout(self.ranking_widget)
        self.ranking_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.ranking_grid_layout.setHorizontalSpacing(8)
        self.ranking_grid_layout.setVerticalSpacing(8)
        ranking_layout.addWidget(self.ranking_widget)
        self.ranking_label = QLabel(tr('common.no_data'))
        self.ranking_label.setWordWrap(True)
        self.ranking_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ranking_layout.addWidget(self.ranking_label)
        content_layout.addWidget(ranking_group)
        content_layout.addStretch()

        scroll_area.setWidget(content)
        self.set_async_busy_widgets([self.btn_refresh])

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: self.refresh_client.get_metric_analysis(
                self.analysis_type,
                self.metric_key,
                force_refresh=force_refresh,
            )
            or {},
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        analysis = dict(payload.get('analysis', {}) or {})
        distribution_rows = list(analysis.get('distribution_rows', []) or [])
        ranking_rows = list(analysis.get('ranking_rows', []) or [])
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        distribution_items_per_line = int(analysis.get('distribution_items_per_line', 10) or 10)
        ranking_items_per_line = int(analysis.get('ranking_items_per_line', 10) or 10)

        ranking_items = [
            tr(
                'data_center.analysis.ranking_item',
                rank=index + 1,
                name=self._resolve_ranking_row_label(row),
                value=row.get('display_value', ''),
            )
            for index, row in enumerate(ranking_rows)
        ]

        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        self._render_distribution_rows(distribution_rows, distribution_items_per_line)
        self._render_ranking_rows(ranking_items, ranking_items_per_line)

    def _render_distribution_rows(self, distribution_rows, items_per_line):
        clickable_rows = [
            row for row in distribution_rows
            if self._is_clickable_distribution_row(row)
        ]
        fallback_rows = [
            row for row in distribution_rows
            if not self._is_clickable_distribution_row(row)
        ]

        self.distribution_buttons = []
        _clear_layout(self.distribution_button_layout)

        if clickable_rows:
            for index, row in enumerate(clickable_rows):
                button = QPushButton(self._build_distribution_item_text(row))
                button.setMinimumHeight(32)
                button.clicked.connect(
                    lambda _checked=False,
                    bucket_value=int(row.get('bucket_value', 0) or 0),
                    bucket_label=str(row.get('label', '') or '').strip(): self.open_actor_metric_bucket_window(
                        bucket_value,
                        bucket_label,
                    )
                )
                self.distribution_button_layout.addWidget(
                    button,
                    index // max(1, items_per_line),
                    index % max(1, items_per_line),
                )
                self.distribution_buttons.append(button)
            _apply_uniform_widget_width(self.distribution_buttons, minimum_width=104)
            self.distribution_button_widget.show()
        else:
            self.distribution_button_widget.hide()

        label_rows = fallback_rows if clickable_rows else distribution_rows
        label_items = [self._build_distribution_item_text(row) for row in label_rows]
        label_text = (
            _join_items_by_line(label_items, items_per_line=items_per_line)
            if label_items
            else tr('common.no_data')
        )
        self.distribution_label.setText(label_text)
        self.distribution_label.setVisible(bool(label_text))

    def _render_ranking_rows(self, ranking_items, items_per_line):
        self.ranking_item_widgets = []
        _clear_layout(self.ranking_grid_layout)

        if not ranking_items:
            self.ranking_widget.hide()
            self.ranking_label.setText(tr('common.no_data'))
            self.ranking_label.show()
            return

        for index, item_text in enumerate(ranking_items):
            label = QLabel(item_text)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.ranking_grid_layout.addWidget(
                label,
                index // max(1, items_per_line),
                index % max(1, items_per_line),
            )
            self.ranking_item_widgets.append(label)

        _apply_uniform_widget_width(self.ranking_item_widgets, minimum_width=180)
        self.ranking_widget.show()
        self.ranking_label.hide()

    def _is_clickable_distribution_row(self, row):
        return self.analysis_type == 'actor' and row.get('bucket_value') is not None

    def _build_distribution_item_text(self, row):
        current = dict(row or {})
        return tr(
            'detail.distribution_item',
            name=current.get('label', tr('common.unknown')),
            count=current.get('count', 0),
        )

    def open_actor_metric_bucket_window(self, bucket_value, bucket_label):
        if self.analysis_type != 'actor':
            return
        window = ActorMetricBucketWindow(
            self.backend_client,
            self.metric_config,
            bucket_value,
            bucket_label,
            self,
        )
        self.bucket_windows.append(window)
        window.finished.connect(lambda _result, current=window: self._forget_bucket_window(current))
        window.show()

    def _forget_bucket_window(self, window):
        self.bucket_windows = [item for item in self.bucket_windows if item is not window]

    @staticmethod
    def _resolve_ranking_row_label(row):
        current = dict(row or {})
        return (
            str(current.get('label', '') or '').strip()
            or str(current.get('actor_name', '') or '').strip()
            or str(current.get('prefix', '') or '').strip()
            or str(current.get('name', '') or '').strip()
            or tr('common.unknown')
        )
