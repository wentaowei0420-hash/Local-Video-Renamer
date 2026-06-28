from copy import deepcopy

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.project_paths import VIDEO_FILTER_SETTINGS_FILE
from app.core.video_filter_rules import (
    FILTER_FIELD_CODE,
    FILTER_FIELD_CO_STAR_CODE,
    FILTER_FIELD_JAVTXT_TAGS,
    FILTER_FIELD_TITLE,
    get_filter_keywords,
)
from app.core.video_filter_settings import load_video_filter_settings, save_video_filter_settings
from app.gui.video_filter_events import video_filter_event_bus
from app.gui.i18n import tr


class KeywordRuleEditor(QWidget):
    def __init__(self, title, hint, parent=None):
        super().__init__(parent)
        self._init_ui(title, hint)

    def _init_ui(self, title, hint):
        layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

        self.group = QGroupBox(title)
        self.group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.group.setMinimumWidth(0)
        group_layout = QVBoxLayout(self.group)

        self.hint_label = QLabel(hint)
        self.hint_label.setWordWrap(True)
        self.hint_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.hint_label.setMinimumWidth(0)
        group_layout.addWidget(self.hint_label)

        self.keyword_list = QListWidget()
        self.keyword_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.keyword_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        group_layout.addWidget(self.keyword_list)

        input_row = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.returnPressed.connect(self.add_keyword)
        self.btn_add = QPushButton(tr('video.filter.add_rule'))
        self.btn_add.clicked.connect(self.add_keyword)
        self.btn_delete = QPushButton(tr('video.filter.delete_rule'))
        self.btn_delete.clicked.connect(self.delete_selected_keyword)
        input_row.addWidget(self.keyword_input)
        input_row.addWidget(self.btn_add)
        input_row.addWidget(self.btn_delete)
        group_layout.addLayout(input_row)

        layout.addWidget(self.group)

    def set_keywords(self, keywords):
        self.keyword_list.clear()
        for keyword in keywords or []:
            self.keyword_list.addItem(str(keyword or '').strip())

    def keywords(self):
        values = []
        seen = set()
        for index in range(self.keyword_list.count()):
            keyword = self.keyword_list.item(index).text().strip()
            lowered = keyword.lower()
            if not keyword or lowered in seen:
                continue
            seen.add(lowered)
            values.append(keyword)
        return values

    def add_keyword(self):
        keyword = self.keyword_input.text().strip()
        if not keyword:
            return
        lowered = keyword.lower()
        existing = {self.keyword_list.item(index).text().strip().lower() for index in range(self.keyword_list.count())}
        if lowered not in existing:
            self.keyword_list.addItem(keyword)
        self.keyword_input.clear()
        self.keyword_input.setFocus()

    def delete_selected_keyword(self):
        selected_items = list(self.keyword_list.selectedItems())
        for item in selected_items:
            self.keyword_list.takeItem(self.keyword_list.row(item))


class VideoFilterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_payload = None
        self.setWindowTitle(tr('video.filter.title'))
        self.resize(1680, 420)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('video.filter.description')))

        self.code_editor = KeywordRuleEditor(
            tr('video.filter.group.code'),
            tr('video.filter.group.code_hint'),
            self,
        )
        self.title_editor = KeywordRuleEditor(
            tr('video.filter.group.title'),
            tr('video.filter.group.title_hint'),
            self,
        )
        self.tags_editor = KeywordRuleEditor(
            tr('video.filter.group.javtxt_tags'),
            tr('video.filter.group.javtxt_tags_hint'),
            self,
        )
        self.co_star_code_editor = KeywordRuleEditor(
            tr('video.filter.group.co_star_code'),
            tr('video.filter.group.co_star_code_hint'),
            self,
        )

        self.editor_grid = QGridLayout()
        self.editor_grid.setHorizontalSpacing(16)
        self.editor_grid.setVerticalSpacing(10)
        self.editor_grid.addWidget(self.code_editor, 0, 0)
        self.editor_grid.addWidget(self.title_editor, 0, 1)
        self.editor_grid.addWidget(self.tags_editor, 0, 2)
        self.editor_grid.addWidget(self.co_star_code_editor, 0, 3)
        self.editor_grid.setColumnStretch(0, 1)
        self.editor_grid.setColumnStretch(1, 1)
        self.editor_grid.setColumnStretch(2, 1)
        self.editor_grid.setColumnStretch(3, 1)

        layout.addLayout(self.editor_grid)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.save_changes)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _load_settings(self):
        settings = load_video_filter_settings()
        self.code_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_CODE))
        self.title_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_TITLE))
        self.tags_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_JAVTXT_TAGS))
        self.co_star_code_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_CO_STAR_CODE))
        self._saved_payload = self.build_settings_payload()

    def build_settings_payload(self):
        return {
            'rules': {
                FILTER_FIELD_CODE: self.code_editor.keywords(),
                FILTER_FIELD_TITLE: self.title_editor.keywords(),
                FILTER_FIELD_JAVTXT_TAGS: self.tags_editor.keywords(),
                FILTER_FIELD_CO_STAR_CODE: self.co_star_code_editor.keywords(),
            }
        }

    def has_unsaved_changes(self):
        if self._saved_payload is None:
            return False
        return self.build_settings_payload() != self._saved_payload

    def save_changes(self):
        payload = self.build_settings_payload()
        try:
            save_video_filter_settings(payload)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), tr('video.filter.save_failed', error=exc))
            return False

        self._saved_payload = deepcopy(payload)
        video_filter_event_bus.rules_saved.emit()
        QMessageBox.information(
            self,
            tr('video.filter.save_success'),
            tr('video.filter.save_success_message', path=VIDEO_FILTER_SETTINGS_FILE),
        )
        return True

    def _can_discard_unsaved_changes(self):
        if not self.has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self,
            tr('video.filter.unsaved_changes_title'),
            tr('video.filter.unsaved_changes_message'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def reject(self):
        if not self._can_discard_unsaved_changes():
            return
        super().reject()

    def closeEvent(self, event):
        if not self._can_discard_unsaved_changes():
            event.ignore()
            return
        self.setResult(QDialog.Rejected)
        self.hide()
        event.accept()
