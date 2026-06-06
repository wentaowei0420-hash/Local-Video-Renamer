from html import escape

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.ladder_board import normalize_ladder_medal_text, split_ladder_medals
from app.gui.i18n import tr


class MedalEditDialog(QDialog):
    def __init__(self, entity_name, medal_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('ladder.selected.medal_dialog_title', entity_name=entity_name))
        self.resize(420, 280)

        layout = QVBoxLayout(self)

        hint_label = QLabel(tr('ladder.selected.medal_dialog_hint'))
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(str(medal_text or ''))
        self.editor.setPlaceholderText(tr('ladder.selected.medal_placeholder'))
        layout.addWidget(self.editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def medal_text(self):
        return normalize_ladder_medal_text(self.editor.toPlainText())


class LadderSelectedPanel(QWidget):
    medal_save_requested = pyqtSignal(str, str)
    detail_requested = pyqtSignal(str)
    _TIER_MEDAL_STYLES = {
        'S': {
            'border': '#c89b2f',
            'background': '#f6e7b6',
            'text': '#6f4a00',
        },
        'A': {
            'border': '#b96a3b',
            'background': '#f6d8c3',
            'text': '#7a3513',
        },
        'B': {
            'border': '#6d9dc5',
            'background': '#dcecf8',
            'text': '#1f5378',
        },
        'C': {
            'border': '#7ca37c',
            'background': '#dcefdc',
            'text': '#2f5d2f',
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._medal_widgets = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(tr('ladder.selected.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().sectionResized.connect(self._refresh_row_heights)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self._medal_widgets = {}
        self.table.setRowCount(0)

        for row_index, row in enumerate(self.rows):
            entity_name = str((row or {}).get('display_name', '') or '').strip()
            tier = str((row or {}).get('tier', '') or '').strip().upper()
            medal_text = normalize_ladder_medal_text((row or {}).get('medal', ''))
            medals = list((row or {}).get('medals') or split_ladder_medals(medal_text))
            self.table.insertRow(row_index)

            name_item = QTableWidgetItem(entity_name)
            tier_item = QTableWidgetItem(tier)
            tier_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, tier_item)
            self.table.setCellWidget(row_index, 2, self._build_medal_widget(entity_name, tier, medal_text, medals))
            self.table.setCellWidget(row_index, 3, self._build_action_widget(entity_name))
            self.table.setCellWidget(row_index, 4, self._build_detail_button(entity_name))

        self._refresh_row_heights()

    def _build_medal_widget(self, entity_name, tier, medal_text, medals):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        label.setMargin(4)
        label.setText(self._build_medal_html(tier, medals))
        self._medal_widgets[entity_name] = {
            'label': label,
            'medal_text': medal_text,
            'button': None,
        }
        return label

    def _build_action_widget(self, entity_name):
        state = self._medal_widgets.get(entity_name) or {}
        medal_text = str(state.get('medal_text', '') or '').strip()
        button = QPushButton(
            tr('ladder.selected.edit_medal') if medal_text else tr('ladder.selected.add_medal')
        )
        button.clicked.connect(lambda _checked=False, name=entity_name: self._handle_action_clicked(name))
        if state is not None:
            state['button'] = button
            self._medal_widgets[entity_name] = state
        return button

    def _build_detail_button(self, entity_name):
        button = QPushButton(tr('ladder.detail'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self.detail_requested.emit(name))
        return button

    def _handle_action_clicked(self, entity_name):
        state = self._medal_widgets.get(str(entity_name or '').strip())
        if not state:
            return

        dialog = MedalEditDialog(entity_name, state.get('medal_text', ''), self)
        if dialog.exec_() != QDialog.Accepted:
            return

        medal_text = dialog.medal_text()
        if medal_text == str(state.get('medal_text', '') or ''):
            return
        self.medal_save_requested.emit(entity_name, medal_text)

    def _build_medal_html(self, tier, medals):
        if not medals:
            return f'<span style="color:#888888;">{escape(tr("ladder.selected.medal_empty"))}</span>'

        palette = dict(self._TIER_MEDAL_STYLES.get(str(tier or '').strip().upper(), self._TIER_MEDAL_STYLES['C']))
        chips = []
        for medal in medals:
            chips.append(
                (
                    '<span style="display:inline-block; margin:0 6px 6px 0; '
                    f'padding:3px 10px; border:1px solid {palette["border"]}; border-radius:10px; '
                    f'background-color:{palette["background"]}; color:{palette["text"]};">'
                    f'{escape(str(medal or ""))}'
                    '</span>'
                )
            )
        return ''.join(chips)

    def _refresh_row_heights(self, *_args):
        self.table.resizeRowsToContents()
