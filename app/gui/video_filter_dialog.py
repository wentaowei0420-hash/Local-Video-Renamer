from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.project_paths import VIDEO_FILTER_SETTINGS_FILE
from app.core.video_filter_rules import (
    FILTER_FIELD_CODE,
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

        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(QLabel(hint))

        self.keyword_list = QListWidget()
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

        layout.addWidget(group)

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
        self.setWindowTitle(tr('video.filter.title'))
        self.resize(760, 640)
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

        layout.addWidget(self.code_editor)
        layout.addWidget(self.title_editor)
        layout.addWidget(self.tags_editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_settings(self):
        settings = load_video_filter_settings()
        self.code_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_CODE))
        self.title_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_TITLE))
        self.tags_editor.set_keywords(get_filter_keywords(settings, FILTER_FIELD_JAVTXT_TAGS))

    def build_settings_payload(self):
        return {
            'rules': {
                FILTER_FIELD_CODE: self.code_editor.keywords(),
                FILTER_FIELD_TITLE: self.title_editor.keywords(),
                FILTER_FIELD_JAVTXT_TAGS: self.tags_editor.keywords(),
            }
        }

    def save_and_accept(self):
        try:
            save_video_filter_settings(self.build_settings_payload())
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), tr('video.filter.save_failed', error=exc))
            return

        video_filter_event_bus.rules_saved.emit()
        QMessageBox.information(
            self,
            tr('video.filter.save_success'),
            tr('video.filter.save_success_message', path=VIDEO_FILTER_SETTINGS_FILE),
        )
        self.accept()
