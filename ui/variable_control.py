from PyQt5.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QLabel, QMenu, QColorDialog, QSizePolicy
from PyQt5.QtCore import pyqtSignal

class VariableControlItem(QWidget):
    # 信号：变量可见性变化、颜色变化
    visibility_changed = pyqtSignal(str, bool)
    color_changed = pyqtSignal(str, tuple)

    def __init__(self, var_name, color, default_color, checked=True):
        super().__init__()
        self.var_name = var_name
        self.color = color
        self.default_color = default_color

        # 控件布局
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 0, 4, 0)

        # 复选框控制可见性
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.stateChanged.connect(self._emit_visibility)
        layout.addWidget(self.checkbox)

        # 标签显示变量名，右键弹出菜单
        self.label = QLabel(var_name)
        self.label.setStyleSheet(f"color: rgb{color};")
        self.label.setContextMenuPolicy(3)
        self.label.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.label)

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    def _emit_visibility(self):
        """勾选框状态变更时发射可见性信号"""
        self.visibility_changed.emit(self.var_name, self.checkbox.isChecked())

    def show_context_menu(self, pos):
        """右键菜单：更换颜色/默认颜色"""
        menu = QMenu(self)
        change_color_action = menu.addAction("Change color")
        reset_color_action = menu.addAction("Default color")
        action = menu.exec_(self.label.mapToGlobal(pos))
        if action == change_color_action:
            self.change_color()
        elif action == reset_color_action:
            self.reset_color()

    def change_color(self):
        """弹出颜色选择器并应用颜色"""
        color = QColorDialog.getColor()
        if color.isValid():
            rgb = color.getRgb()[:3]
            self.color = rgb
            self.label.setStyleSheet(f"color: rgb{rgb};")
            self.color_changed.emit(self.var_name, rgb)

    def reset_color(self):
        """恢复默认颜色"""
        self.color = self.default_color
        self.label.setStyleSheet(f"color: rgb{self.default_color};")
        self.color_changed.emit(self.var_name, self.default_color)
