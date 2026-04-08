from PyQt5.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QLabel, QMenu, QColorDialog, QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal


class VariableControlItem(QWidget):
    visibility_changed = pyqtSignal(str, bool)
    color_changed = pyqtSignal(str, tuple)

    def __init__(self, var_name, color, default_color, checked=True):
        super().__init__()
        self.var_name = var_name
        self.color = color
        self.default_color = default_color

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.setFixedWidth(16)
        self.checkbox.stateChanged.connect(self._emit_visibility)
        layout.addWidget(self.checkbox)

        self.label = QLabel(var_name)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._apply_label_style(color)
        self.label.setWordWrap(False)
        self.label.setContextMenuPolicy(3)
        self.label.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.label)

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

    def _emit_visibility(self):
        self.visibility_changed.emit(self.var_name, self.checkbox.isChecked())

    def _apply_label_style(self, rgb):
        self.label.setStyleSheet(f"color: rgb{rgb};")

    def show_context_menu(self, pos):
        menu = QMenu(self)
        change_color_action = menu.addAction("Change color")
        reset_color_action = menu.addAction("Default color")
        action = menu.exec_(self.label.mapToGlobal(pos))
        if action == change_color_action:
            self.change_color()
        elif action == reset_color_action:
            self.reset_color()

    def change_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            rgb = color.getRgb()[:3]
            self.color = rgb
            self._apply_label_style(rgb)
            self.color_changed.emit(self.var_name, rgb)

    def reset_color(self):
        self.color = self.default_color
        self._apply_label_style(self.default_color)
        self.color_changed.emit(self.var_name, self.default_color)
