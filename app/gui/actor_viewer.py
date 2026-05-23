from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.actor_detail_viewer import ActorDetailViewerWindow


class ActorViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.editing_actor_name = None
        self.editing_row = None
        self.action_buttons = {}
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('作者库')
        self.resize(1220, 540)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入演员、作者ID、生日、年龄或补全状态实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        btn_reset = QPushButton('选中重置')
        btn_reset.clicked.connect(self.reset_selected_rows)

        btn_refresh = QPushButton('刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_reset)
        top_layout.addWidget(btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            '演员',
            '作者ID',
            '生日',
            '年龄',
            '补全状态',
            '详情',
            '操作',
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        self.clear_edit_state()
        self.table.setRowCount(0)
        try:
            self.rows = self.backend_client.list_actors()
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'读取作者库失败: {exc}')

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('name', ''),
                row_data.get('actor_id', ''),
                row_data.get('birthday', ''),
                row_data.get('age', ''),
                row_data.get('enrichment_status', ''),
            )

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (1, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            actor_name = row_data.get('name', '')
            self.table.setCellWidget(row_idx, 5, self.build_detail_button(actor_name))
            self.table.setCellWidget(row_idx, 6, self.build_action_buttons(actor_name))

    def build_detail_button(self, actor_name):
        button = QPushButton('查看详情')
        button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, actor_name):
        edit_button = QPushButton('修改')
        edit_button.clicked.connect(lambda _checked=False, value=actor_name: self.handle_edit_button(value))

        delete_button = QPushButton('删除')
        delete_button.clicked.connect(lambda _checked=False, value=actor_name: self.delete_actor(value))

        self.action_buttons[actor_name] = {
            'edit': edit_button,
            'delete': delete_button,
        }

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_actor_detail(self, actor_name):
        if not actor_name:
            return
        viewer = ActorDetailViewerWindow(
            backend_client=self.backend_client,
            actor_name=actor_name,
            parent=self,
        )
        viewer.exec_()

    def filter_data(self, text):
        self.clear_edit_state()
        try:
            self.rows = self.backend_client.list_actors(text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选作者库失败: {exc}')

    def clear_edit_state(self):
        self.editing_actor_name = None
        self.editing_row = None

    def refresh_current_view(self):
        search_text = self.search_input.text().strip()
        if search_text:
            self.filter_data(search_text)
            return
        self.load_data()

    def handle_edit_button(self, actor_name):
        if self.editing_actor_name is None:
            self.start_actor_edit(actor_name)
            return

        if self.editing_actor_name != actor_name:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的演员行。')
            return

        self.confirm_actor_edit()

    def start_actor_edit(self, actor_name):
        row = self.find_row_by_actor_name(actor_name)
        if row < 0:
            QMessageBox.warning(self, '提示', f'未找到演员：{actor_name}')
            return

        self.editing_actor_name = actor_name
        self.editing_row = row
        self.set_actor_cell_editable(row, True)

        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText('确认')

        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_actor_edit(self):
        if self.editing_actor_name is None or self.editing_row is None:
            return

        item = self.table.item(self.editing_row, 0)
        old_name = self.editing_actor_name
        if item is None:
            self.clear_edit_state()
            return

        new_name = item.text().strip()
        self.set_actor_cell_editable(self.editing_row, False)

        if not new_name:
            item.setText(old_name)
            self.reset_row_button_text(old_name)
            self.clear_edit_state()
            QMessageBox.warning(self, '提示', '演员名称不能为空')
            return

        try:
            self.backend_client.rename_actor(old_name, new_name)
        except Exception as exc:
            item.setText(old_name)
            self.reset_row_button_text(old_name)
            self.clear_edit_state()
            QMessageBox.critical(self, '修改失败', f'修改演员名称失败：\n{exc}')
            return

        self.clear_edit_state()
        self.refresh_current_view()
        QMessageBox.information(self, '修改完成', f'已将演员 {old_name} 修改为 {new_name}。')

    def reset_row_button_text(self, actor_name):
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText('修改')

    def set_actor_cell_editable(self, row, editable):
        item = self.table.item(row, 0)
        if item is None:
            return
        flags = item.flags()
        if editable:
            item.setFlags(flags | Qt.ItemIsEditable)
            return
        item.setFlags(flags & ~Qt.ItemIsEditable)

    def find_row_by_actor_name(self, actor_name):
        target = str(actor_name or '').strip()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip() == target:
                return row
        return -1

    def delete_actor(self, actor_name):
        if self.editing_actor_name is not None:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的演员行。')
            return

        answer = QMessageBox.question(
            self,
            '确认删除',
            f'确定删除演员 {actor_name} 吗？\n这会从作者库移除该演员，并清除对应的网页补全数据。',
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self.backend_client.delete_actor(actor_name)
        except Exception as exc:
            QMessageBox.critical(self, '删除失败', f'删除演员失败：\n{exc}')
            return

        self.refresh_current_view()
        QMessageBox.information(self, '删除完成', f'已删除演员 {actor_name}。')

    def reset_selected_rows(self):
        actor_names = self.selected_actor_names()
        if not actor_names:
            QMessageBox.information(self, '未选择', '请先选中要重置的演员行。')
            return

        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(actor_names)} 个演员补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        try:
            reset_count = self.backend_client.reset_actor_enrichments(actor_names)
        except Exception as exc:
            QMessageBox.critical(self, '重置失败', f'重置演员补全状态失败：\n{exc}')
            return

        self.load_data()
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个演员的补全状态。')

    def selected_actor_names(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        actor_names = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                actor_names.append(item.text().strip())
        return actor_names
