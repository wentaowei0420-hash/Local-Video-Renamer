from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.i18n import tr


class SegmentedSummaryProgressBar(QFrame):
    SCALE = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completed_percent = 0.0
        self._terminal_percent = 0.0

        self.setObjectName('summaryProgressBar')
        self.setMinimumHeight(24)
        self.setStyleSheet(
            '''
            QFrame#summaryProgressBar {
                background: #f7f7f7;
                border: 1px solid #b8b8b8;
                border-radius: 3px;
            }
            QFrame#summaryProgressBlue {
                background: #1e88e5;
                border: none;
            }
            QFrame#summaryProgressRed {
                background: #d32f2f;
                border: none;
            }
            QFrame#summaryProgressEmpty {
                background: transparent;
                border: none;
            }
            '''
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.blue_segment = QFrame(self)
        self.blue_segment.setObjectName('summaryProgressBlue')
        self.red_segment = QFrame(self)
        self.red_segment.setObjectName('summaryProgressRed')
        self.empty_segment = QFrame(self)
        self.empty_segment.setObjectName('summaryProgressEmpty')
        self.percent_label = QLabel('0.0%', self)
        self.percent_label.setAlignment(Qt.AlignCenter)
        self.percent_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.percent_label.setStyleSheet('background: transparent; color: #222222; border: none;')

        layout.addWidget(self.blue_segment)
        layout.addWidget(self.red_segment)
        layout.addWidget(self.empty_segment)
        self._apply_segment_stretches()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.percent_label.setGeometry(self.rect())

    def set_progress(self, completed_percent, terminal_percent):
        self._completed_percent = max(0.0, min(float(completed_percent or 0.0), 100.0))
        self._terminal_percent = max(0.0, min(float(terminal_percent or 0.0), self._completed_percent))
        self.percent_label.setText(f'{self._completed_percent:.1f}%')
        self._apply_segment_stretches()
        self._apply_label_style()

    def _apply_segment_stretches(self):
        blue_stretch = max(int(round((self._completed_percent - self._terminal_percent) * 10)), 0)
        red_stretch = max(int(round(self._terminal_percent * 10)), 0)
        empty_stretch = max(self.SCALE - blue_stretch - red_stretch, 0)

        layout = self.layout()
        layout.setStretch(0, blue_stretch)
        layout.setStretch(1, red_stretch)
        layout.setStretch(2, empty_stretch)

        self.blue_segment.setVisible(blue_stretch > 0)
        self.red_segment.setVisible(red_stretch > 0)
        self.empty_segment.setVisible(empty_stretch > 0)

    def _apply_label_style(self):
        if self._completed_percent >= 45.0:
            color = '#ffffff'
        else:
            color = '#222222'
        self.percent_label.setStyleSheet(f'background: transparent; color: {color}; border: none;')


class SummaryCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName('summaryCard')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.count_label = QLabel(
            tr(
                'enrichment.summary.count',
                count_label=tr('enrichment.summary.count_default'),
                enriched_count=0,
                total_count=0,
            )
        )
        self.detail_label = QLabel(
            tr(
                'enrichment.summary.detail_full',
                pending_label=tr('enrichment.summary.pending_default'),
                pending_count=0,
                success_count=0,
                failed_count=0,
                no_search_count=0,
                no_detail_count=0,
            )
        )
        self.live_label = QLabel('')
        self.live_label.hide()
        self.progress_bar = SegmentedSummaryProgressBar()

        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.live_label)
        layout.addWidget(self.progress_bar)

    def set_summary(self, summary, show_terminal_details=True, live_progress=None):
        total_count = int(summary.get('total_count', 0) or 0)
        completed_count = int(summary.get('completed_count', summary.get('enriched_count', 0)) or 0)
        success_count = int(summary.get('success_count', completed_count) or 0)
        pending_count = int(summary.get('pending_count', 0) or 0)
        failed_count = int(summary.get('failed_count', 0) or 0)
        no_search_count = int(summary.get('no_search_count', 0) or 0)
        no_detail_count = int(summary.get('no_detail_count', 0) or 0)
        progress_percent = float(summary.get('progress_percent', 0) or 0)
        count_label = str(summary.get('count_label', '') or tr('enrichment.summary.count_default'))
        pending_label = str(summary.get('pending_label', '') or tr('enrichment.summary.pending_default'))
        terminal_percent = 0.0
        if total_count > 0:
            terminal_percent = round(((no_search_count + no_detail_count) / total_count) * 100.0, 1)

        self.title_label.setText(str(summary.get('label', '')))
        self.count_label.setText(
            tr(
                'enrichment.summary.count',
                count_label=count_label,
                enriched_count=completed_count,
                total_count=total_count,
            )
        )
        if show_terminal_details:
            self.detail_label.setText(
                tr(
                    'enrichment.summary.detail_full',
                    pending_label=pending_label,
                    pending_count=pending_count,
                    success_count=success_count,
                    failed_count=failed_count,
                    no_search_count=no_search_count,
                    no_detail_count=no_detail_count,
                )
            )
        else:
            self.detail_label.setText(
                tr(
                    'enrichment.summary.detail_pending_only',
                    pending_label=pending_label,
                    pending_count=pending_count,
                )
            )

        display_percent = progress_percent
        if live_progress:
            live_total_count = int(live_progress.get('total_count', 0) or 0)
            live_processed_count = int(live_progress.get('processed_count', 0) or 0)
            live_success_count = int(live_progress.get('success_count', 0) or 0)
            live_failed_count = int(live_progress.get('failed_count', 0) or 0)
            live_count_unit = str(live_progress.get('count_unit', '') or tr('enrichment.summary.count_unit_default'))
            live_message = str(live_progress.get('message', '') or '')
            current_item = str(live_progress.get('current_item', '') or '')

            progress_delta = min(max(live_processed_count, 0), max(pending_count, 0))
            if total_count > 0:
                display_percent = round(((completed_count + progress_delta) / total_count) * 100.0, 1)

            segments = [
                tr(
                    'enrichment.summary.live',
                    processed_count=live_processed_count,
                    total_count=live_total_count,
                    count_unit=live_count_unit,
                ),
                tr('common.success', count=live_success_count),
                tr('common.failed', count=live_failed_count),
            ]
            if current_item:
                segments.append(tr('common.current', value=current_item))
            elif live_message:
                segments.append(live_message)
            self.live_label.setText(' | '.join(segments))
            self.live_label.show()
        else:
            self.live_label.hide()
            self.live_label.setText('')

        self.progress_bar.set_progress(display_percent, terminal_percent)
