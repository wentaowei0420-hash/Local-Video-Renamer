from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QLabel, QWidget

from app.gui.i18n import tr


class DetailSummaryGrid(QWidget):
    def __init__(self, columns=2, parent=None):
        super().__init__(parent)
        self.columns = max(1, int(columns or 1))
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setHorizontalSpacing(24)
        self.layout.setVerticalSpacing(12)
        self.value_labels = {}

    def set_items(self, items):
        self._clear_layout()
        self.value_labels = {}

        for index, (key, title, value) in enumerate(items):
            row = index // self.columns
            column = (index % self.columns) * 2

            title_label = QLabel(str(title))
            title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

            value_label = QLabel(str(value))
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

            self.layout.addWidget(title_label, row, column)
            self.layout.addWidget(value_label, row, column + 1)
            self.value_labels[key] = value_label

        self.layout.setColumnStretch(self.columns * 2 - 1, 1)

    def set_value(self, key, value):
        label = self.value_labels.get(key)
        if label is not None:
            label.setText(str(value))

    def _clear_layout(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def format_distribution_summary(rows, key_name, empty_text=None, items_per_line=1):
    if not rows:
        return empty_text or tr('common.empty')

    items = [
        tr(
            'detail.distribution_item',
            name=row.get(key_name, tr('common.unknown')),
            count=row.get('video_count', 0),
        )
        for row in rows
    ]
    return _join_items_by_line(items, items_per_line)


def format_update_frequency_summary(stats):
    stats = dict(stats or {})
    rate = stats.get('videos_per_month')
    if rate is None:
        return tr('common.empty')
    return tr('detail.update_frequency_value', rate=f'{float(rate):.2f}')


def _join_items_by_line(items, items_per_line):
    grouped_lines = []
    items_per_line = max(1, int(items_per_line or 1))
    for start in range(0, len(items), items_per_line):
        grouped_lines.append('    '.join(items[start:start + items_per_line]))
    return '\n'.join(grouped_lines)
