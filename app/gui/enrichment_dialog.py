import json

from PyQt5.QtCore import QSignalBlocker
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.combo_enrichment import (
    DEFAULT_COMBO_KEY,
    FU_SHUI_COMBO,
    KAN_SHUI_COMBO,
    get_combo_tasks,
    normalize_combo_key,
)
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    normalize_video_enrichment_source,
)
from app.core.enrichment_targets import (
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.core.project_paths import ENRICHMENT_SETTINGS_FILE


SUPPORTED_SOURCE_KEYS = (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
)

DEFAULT_SOURCE_BY_TARGET = {
    VIDEO_LIBRARY_TARGET: DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    CODE_PREFIX_LIBRARY_TARGET: AVFAN_VIDEO_SOURCE,
    ACTOR_LIBRARY_TARGET: AVFAN_VIDEO_SOURCE,
}

DEFAULT_COMBINATION_SETTINGS = {
    'limit': 5,
    'show_browser': False,
    'cooldown_before_search': False,
    'batch_limit': 5,
    'batch_interval_minutes': 30,
}


def build_default_combination_settings(source_key):
    settings = dict(DEFAULT_COMBINATION_SETTINGS)
    settings['source_key'] = source_key
    return settings


DEFAULT_TARGET_SETTINGS = {
    target_type: {
        source_key: build_default_combination_settings(source_key)
        for source_key in SUPPORTED_SOURCE_KEYS
    }
    for target_type in (
        VIDEO_LIBRARY_TARGET,
        CODE_PREFIX_LIBRARY_TARGET,
        ACTOR_LIBRARY_TARGET,
    )
}

DEFAULT_SETTINGS_PAYLOAD = {
    'target_type': VIDEO_LIBRARY_TARGET,
    'selected_source_by_target': dict(DEFAULT_SOURCE_BY_TARGET),
    'selected_combo_key': DEFAULT_COMBO_KEY,
    'target_settings': DEFAULT_TARGET_SETTINGS,
}


def clone_default_target_settings():
    return {
        target_type: {
            source_key: dict(source_settings)
            for source_key, source_settings in source_settings_by_target.items()
        }
        for target_type, source_settings_by_target in DEFAULT_TARGET_SETTINGS.items()
    }


def clone_default_selected_sources():
    return dict(DEFAULT_SOURCE_BY_TARGET)


def is_flat_settings_payload(payload):
    return isinstance(payload, dict) and any(
        key in payload
        for key in (
            'limit',
            'show_browser',
            'cooldown_before_search',
            'batch_limit',
            'batch_interval_minutes',
            'source_key',
        )
    )


def merge_combination_settings(default_values, loaded_values, source_key):
    if not isinstance(loaded_values, dict):
        return

    for key in (
        'limit',
        'show_browser',
        'cooldown_before_search',
        'batch_limit',
        'batch_interval_minutes',
    ):
        if key in loaded_values:
            default_values[key] = loaded_values[key]
    default_values['source_key'] = source_key


def normalize_target_settings(payload):
    settings = clone_default_target_settings()
    loaded_target_settings = payload.get('target_settings', {}) if isinstance(payload, dict) else {}
    if not isinstance(loaded_target_settings, dict):
        return settings

    for target_type, default_source_settings in settings.items():
        loaded_values = loaded_target_settings.get(target_type, {})
        if not isinstance(loaded_values, dict):
            continue

        if is_flat_settings_payload(loaded_values):
            source_key = normalize_video_enrichment_source(loaded_values.get('source_key'))
            merge_combination_settings(default_source_settings[source_key], loaded_values, source_key)
            continue

        for source_key, default_values in default_source_settings.items():
            merge_combination_settings(default_values, loaded_values.get(source_key, {}), source_key)
    return settings


def normalize_selected_sources(payload):
    selected_sources = clone_default_selected_sources()
    if not isinstance(payload, dict):
        return selected_sources

    loaded_selected_sources = payload.get('selected_source_by_target', {})
    if 'selected_source_by_target' in payload and isinstance(loaded_selected_sources, dict):
        for target_type, default_source_key in selected_sources.items():
            selected_sources[target_type] = normalize_video_enrichment_source(
                loaded_selected_sources.get(target_type, default_source_key)
            )
        return selected_sources

    loaded_target_settings = payload.get('target_settings', {})
    if isinstance(loaded_target_settings, dict):
        for target_type, default_source_key in selected_sources.items():
            loaded_values = loaded_target_settings.get(target_type, {})
            if is_flat_settings_payload(loaded_values):
                selected_sources[target_type] = normalize_video_enrichment_source(
                    loaded_values.get('source_key', default_source_key)
                )
    return selected_sources


def load_saved_settings():
    payload = {
        'target_type': DEFAULT_SETTINGS_PAYLOAD['target_type'],
        'selected_source_by_target': clone_default_selected_sources(),
        'selected_combo_key': DEFAULT_SETTINGS_PAYLOAD['selected_combo_key'],
        'target_settings': clone_default_target_settings(),
    }
    if ENRICHMENT_SETTINGS_FILE.exists():
        try:
            loaded = json.loads(ENRICHMENT_SETTINGS_FILE.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                payload['target_type'] = loaded.get('target_type', payload['target_type'])
                payload['selected_source_by_target'] = normalize_selected_sources(loaded)
                payload['selected_combo_key'] = normalize_combo_key(
                    loaded.get('selected_combo_key', payload['selected_combo_key'])
                )
                payload['target_settings'] = normalize_target_settings(loaded)
        except Exception:
            pass
    return payload


def save_saved_settings(target_type, selected_source_by_target, target_settings, selected_combo_key):
    payload = {
        'target_type': target_type,
        'selected_source_by_target': normalize_selected_sources(
            {'selected_source_by_target': selected_source_by_target}
        ),
        'selected_combo_key': normalize_combo_key(selected_combo_key),
        'target_settings': normalize_target_settings({'target_settings': target_settings}),
    }
    ENRICHMENT_SETTINGS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


class EnrichmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.action_mode = 'single'
        self.current_target_type = VIDEO_LIBRARY_TARGET
        self.current_source_key = DEFAULT_SOURCE_BY_TARGET[VIDEO_LIBRARY_TARGET]
        self.current_combo_key = DEFAULT_COMBO_KEY
        self.selected_source_by_target = clone_default_selected_sources()
        self.target_settings = clone_default_target_settings()
        self.setWindowTitle('补全信息')
        self.init_ui()
        self.apply_saved_settings(load_saved_settings())

    def init_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        target_group = QGroupBox('抓取目标')
        target_layout = QHBoxLayout()
        self.target_button_group = QButtonGroup(self)
        self.target_button_group.setExclusive(True)

        self.video_target_button = QRadioButton('视频库')
        self.code_prefix_target_button = QRadioButton('番号库')
        self.actor_target_button = QRadioButton('演员库')

        self.target_button_group.addButton(self.video_target_button)
        self.target_button_group.addButton(self.code_prefix_target_button)
        self.target_button_group.addButton(self.actor_target_button)

        target_layout.addWidget(self.video_target_button)
        target_layout.addWidget(self.code_prefix_target_button)
        target_layout.addWidget(self.actor_target_button)
        target_layout.addStretch()
        target_group.setLayout(target_layout)

        source_group = QGroupBox('补全来源')
        source_layout = QHBoxLayout()
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        self.avfan_source_button = QRadioButton('天限阁')
        self.javtxt_source_button = QRadioButton('辛聚谷')
        self.javtxt_source_button.setToolTip('辛聚谷用于补全视频标题、演员与第二套视频 ID。')
        self.source_button_group.addButton(self.avfan_source_button)
        self.source_button_group.addButton(self.javtxt_source_button)
        source_layout.addWidget(self.avfan_source_button)
        source_layout.addWidget(self.javtxt_source_button)
        source_layout.addStretch()
        source_group.setLayout(source_layout)

        combo_group = QGroupBox('组合任务')
        combo_layout = QHBoxLayout()
        self.combo_button_group = QButtonGroup(self)
        self.combo_button_group.setExclusive(True)
        self.kan_shui_button = QRadioButton('坎水')
        self.fu_shui_button = QRadioButton('府水')
        self.combo_button_group.addButton(self.kan_shui_button)
        self.combo_button_group.addButton(self.fu_shui_button)
        combo_layout.addWidget(self.kan_shui_button)
        combo_layout.addWidget(self.fu_shui_button)
        combo_layout.addStretch()
        combo_group.setLayout(combo_layout)

        self.avfan_source_button.toggled.connect(
            lambda checked: self.on_source_button_toggled(AVFAN_VIDEO_SOURCE, checked)
        )
        self.javtxt_source_button.toggled.connect(
            lambda checked: self.on_source_button_toggled(JAVTXT_VIDEO_SOURCE, checked)
        )
        self.kan_shui_button.toggled.connect(
            lambda checked: self.on_combo_button_toggled(KAN_SHUI_COMBO, checked)
        )
        self.fu_shui_button.toggled.connect(
            lambda checked: self.on_combo_button_toggled(FU_SHUI_COMBO, checked)
        )

        self.video_target_button.toggled.connect(
            lambda checked: self.on_target_button_toggled(VIDEO_LIBRARY_TARGET, checked)
        )
        self.code_prefix_target_button.toggled.connect(
            lambda checked: self.on_target_button_toggled(CODE_PREFIX_LIBRARY_TARGET, checked)
        )
        self.actor_target_button.toggled.connect(
            lambda checked: self.on_target_button_toggled(ACTOR_LIBRARY_TARGET, checked)
        )

        self.limit_input = QSpinBox()
        self.limit_input.setRange(1, 999999)

        self.batch_limit_input = QSpinBox()
        self.batch_limit_input.setRange(1, 999999)

        self.interval_minutes_input = QSpinBox()
        self.interval_minutes_input.setRange(1, 1440)
        self.interval_minutes_input.setSuffix(' 分钟')

        self.show_browser_checkbox = QCheckBox('显示浏览器窗口')
        self.cooldown_checkbox = QCheckBox('冷却 3 分钟后再搜索')

        form_layout.addRow('本次补全数量:', self.limit_input)
        form_layout.addRow('每批补全数量:', self.batch_limit_input)
        form_layout.addRow('批次间隔:', self.interval_minutes_input)
        form_layout.addRow('', self.show_browser_checkbox)
        form_layout.addRow('', self.cooldown_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.batch_button = buttons.addButton('分批补全', QDialogButtonBox.ActionRole)
        self.combo_single_button = buttons.addButton('单次组合任务下发', QDialogButtonBox.ActionRole)
        self.combo_batch_button = buttons.addButton('批次组合任务下发', QDialogButtonBox.ActionRole)
        self.save_button = buttons.addButton('保存配置', QDialogButtonBox.ActionRole)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setText('开始补全')

        buttons.accepted.connect(self.accept_single)
        buttons.rejected.connect(self.reject)
        self.batch_button.clicked.connect(self.accept_batch)
        self.combo_single_button.clicked.connect(self.accept_combo_single)
        self.combo_batch_button.clicked.connect(self.accept_combo_batch)
        self.save_button.clicked.connect(self.save_settings)

        layout.addWidget(target_group)
        layout.addWidget(source_group)
        layout.addWidget(combo_group)
        layout.addLayout(form_layout)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def apply_saved_settings(self, payload):
        self.target_settings = normalize_target_settings(payload)
        self.selected_source_by_target = normalize_selected_sources(payload)
        self.current_combo_key = normalize_combo_key(payload.get('selected_combo_key', DEFAULT_COMBO_KEY))

        target_type = payload.get('target_type', VIDEO_LIBRARY_TARGET)
        if target_type not in self.target_settings:
            target_type = VIDEO_LIBRARY_TARGET

        self.current_target_type = target_type
        self.current_source_key = self.selected_source_by_target.get(
            target_type,
            DEFAULT_SOURCE_BY_TARGET[target_type],
        )

        with QSignalBlocker(self.video_target_button), QSignalBlocker(self.code_prefix_target_button), QSignalBlocker(self.actor_target_button):
            self.video_target_button.setChecked(target_type == VIDEO_LIBRARY_TARGET)
            self.code_prefix_target_button.setChecked(target_type == CODE_PREFIX_LIBRARY_TARGET)
            self.actor_target_button.setChecked(target_type == ACTOR_LIBRARY_TARGET)

        with QSignalBlocker(self.kan_shui_button), QSignalBlocker(self.fu_shui_button):
            self.kan_shui_button.setChecked(self.current_combo_key == KAN_SHUI_COMBO)
            self.fu_shui_button.setChecked(self.current_combo_key == FU_SHUI_COMBO)

        if not any(button.isChecked() for button in (
            self.video_target_button,
            self.code_prefix_target_button,
            self.actor_target_button,
        )):
            self.video_target_button.setChecked(True)
            self.current_target_type = VIDEO_LIBRARY_TARGET
            self.current_source_key = self.selected_source_by_target.get(
                VIDEO_LIBRARY_TARGET,
                DEFAULT_SOURCE_BY_TARGET[VIDEO_LIBRARY_TARGET],
            )

        if not any(button.isChecked() for button in (self.kan_shui_button, self.fu_shui_button)):
            self.kan_shui_button.setChecked(True)
            self.current_combo_key = KAN_SHUI_COMBO

        self.apply_combination_settings(self.current_target_type, self.current_source_key)

    def on_target_button_toggled(self, target_type, checked):
        if not checked:
            return
        self.store_current_target_settings()
        self.current_target_type = target_type
        self.current_source_key = self.selected_source_by_target.get(
            target_type,
            DEFAULT_SOURCE_BY_TARGET[target_type],
        )
        self.apply_combination_settings(target_type, self.current_source_key)

    def on_source_button_toggled(self, source_key, checked):
        if not checked:
            return
        self.store_current_target_settings()
        self.current_source_key = source_key
        self.selected_source_by_target[self.current_target_type] = source_key
        self.apply_combination_settings(self.current_target_type, source_key)

    def on_combo_button_toggled(self, combo_key, checked):
        if not checked:
            return
        self.current_combo_key = normalize_combo_key(combo_key)

    def apply_combination_settings(self, target_type, source_key):
        settings = dict(
            self.target_settings.get(target_type, {}).get(
                source_key,
                DEFAULT_TARGET_SETTINGS[target_type][source_key],
            )
        )
        defaults = DEFAULT_TARGET_SETTINGS[target_type][source_key]

        self.limit_input.setValue(self._to_bounded_int(
            settings.get('limit', defaults['limit']),
            defaults['limit'],
            self.limit_input.minimum(),
            self.limit_input.maximum(),
        ))
        self.batch_limit_input.setValue(self._to_bounded_int(
            settings.get('batch_limit', defaults['batch_limit']),
            defaults['batch_limit'],
            self.batch_limit_input.minimum(),
            self.batch_limit_input.maximum(),
        ))
        self.interval_minutes_input.setValue(self._to_bounded_int(
            settings.get('batch_interval_minutes', defaults['batch_interval_minutes']),
            defaults['batch_interval_minutes'],
            self.interval_minutes_input.minimum(),
            self.interval_minutes_input.maximum(),
        ))
        self.show_browser_checkbox.setChecked(
            bool(settings.get('show_browser', defaults['show_browser']))
        )
        self.cooldown_checkbox.setChecked(
            bool(settings.get('cooldown_before_search', defaults['cooldown_before_search']))
        )

        self.current_target_type = target_type
        self.current_source_key = source_key
        self.selected_source_by_target[target_type] = source_key

        with QSignalBlocker(self.avfan_source_button), QSignalBlocker(self.javtxt_source_button):
            self.avfan_source_button.setChecked(source_key == AVFAN_VIDEO_SOURCE)
            self.javtxt_source_button.setChecked(source_key == JAVTXT_VIDEO_SOURCE)
        self.update_source_controls()

    def store_current_target_settings(self):
        target_type = self.current_target_type
        source_key = self.current_source_key
        self.selected_source_by_target[target_type] = source_key
        self.target_settings.setdefault(target_type, {})
        self.target_settings[target_type][source_key] = {
            'limit': self.limit_input.value(),
            'batch_limit': self.batch_limit_input.value(),
            'batch_interval_minutes': self.interval_minutes_input.value(),
            'show_browser': self.show_browser_checkbox.isChecked(),
            'cooldown_before_search': self.cooldown_checkbox.isChecked(),
            'source_key': source_key,
        }

    def selected_target_type(self):
        return self.current_target_type

    def selected_source_key(self):
        return self.current_source_key

    def selected_combo_key(self):
        return normalize_combo_key(self.current_combo_key)

    def values(self):
        self.store_current_target_settings()
        current_settings = dict(
            self.target_settings[self.selected_target_type()][self.selected_source_key()]
        )
        current_settings['target_type'] = self.selected_target_type()
        current_settings['source_key'] = self.selected_source_key()
        current_settings['combo_key'] = self.selected_combo_key()
        current_settings['combo_task_settings'] = self.build_combo_task_settings(self.selected_combo_key())
        return current_settings

    def build_combo_task_settings(self, combo_key):
        combo_task_settings = {}
        for task_definition in get_combo_tasks(combo_key):
            target_type = task_definition['target_type']
            source_key = task_definition['source_key']
            source_settings = dict(
                self.target_settings.get(target_type, {}).get(
                    source_key,
                    DEFAULT_TARGET_SETTINGS[target_type][source_key],
                )
            )
            combo_task_settings[task_definition['task_key']] = {
                'target_type': target_type,
                'source_key': source_key,
                'limit': self._to_bounded_int(
                    source_settings.get('limit', DEFAULT_TARGET_SETTINGS[target_type][source_key]['limit']),
                    DEFAULT_TARGET_SETTINGS[target_type][source_key]['limit'],
                    self.limit_input.minimum(),
                    self.limit_input.maximum(),
                ),
                'batch_limit': self._to_bounded_int(
                    source_settings.get(
                        'batch_limit',
                        DEFAULT_TARGET_SETTINGS[target_type][source_key]['batch_limit'],
                    ),
                    DEFAULT_TARGET_SETTINGS[target_type][source_key]['batch_limit'],
                    self.batch_limit_input.minimum(),
                    self.batch_limit_input.maximum(),
                ),
                'batch_interval_minutes': self._to_bounded_int(
                    source_settings.get(
                        'batch_interval_minutes',
                        DEFAULT_TARGET_SETTINGS[target_type][source_key]['batch_interval_minutes'],
                    ),
                    DEFAULT_TARGET_SETTINGS[target_type][source_key]['batch_interval_minutes'],
                    self.interval_minutes_input.minimum(),
                    self.interval_minutes_input.maximum(),
                ),
                'show_browser': bool(source_settings.get('show_browser', False)),
                'cooldown_before_search': bool(source_settings.get('cooldown_before_search', False)),
            }
        return combo_task_settings

    def update_source_controls(self):
        is_avfan_source = self.selected_source_key() == AVFAN_VIDEO_SOURCE
        self.cooldown_checkbox.setEnabled(is_avfan_source)
        if not is_avfan_source:
            self.cooldown_checkbox.setChecked(False)

    def accept_single(self):
        self.store_current_target_settings()
        self.action_mode = 'single'
        self.accept()

    def accept_batch(self):
        self.store_current_target_settings()
        self.action_mode = 'batch'
        self.accept()

    def accept_combo_single(self):
        self.store_current_target_settings()
        self.action_mode = 'combo_single'
        self.accept()

    def accept_combo_batch(self):
        self.store_current_target_settings()
        self.action_mode = 'combo_batch'
        self.accept()

    def save_settings(self):
        self.store_current_target_settings()
        try:
            save_saved_settings(
                self.selected_target_type(),
                self.selected_source_by_target,
                self.target_settings,
                self.selected_combo_key(),
            )
        except Exception as exc:
            QMessageBox.critical(self, '保存失败', f'无法保存补全配置：\n{exc}')
            return

        QMessageBox.information(
            self,
            '保存成功',
            f'已保存当前库/来源配置和组合策略到：\n{ENRICHMENT_SETTINGS_FILE}',
        )

    @staticmethod
    def _to_bounded_int(value, fallback, minimum, maximum):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(parsed, maximum))
