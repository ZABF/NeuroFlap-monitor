from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyleOptionGroupBox,
    QVBoxLayout,
)

from ui.theme import PANEL_BG_HEX, TEXT_HEX, set_section_kind


def task_section_kind(task_id):
    category_base = int(task_id) & 0xF000
    return {
        0x2000: "business",
        0x3000: "device",
        0x1000: "system",
    }.get(category_base, "")


def task_display_order(task_id):
    task_id = int(task_id)
    category_order = {
        "business": 0,
        "device": 1,
        "system": 2,
    }.get(task_section_kind(task_id), 3)
    return category_order, task_id


class _LatencyLabel(QLabel):
    selected = pyqtSignal(str)
    WIDTH = 84

    def __init__(self, var_name):
        super().__init__("-- us")
        self.var_name = var_name
        self.setFixedWidth(self.WIDTH)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"color: {TEXT_HEX}; background-color: {PANEL_BG_HEX}; padding: 0 2px;")
        self.setToolTip(var_name)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.var_name)
        super().mousePressEvent(event)

    def set_selected(self, selected):
        font = QFont(self.font())
        font.setBold(bool(selected))
        self.setFont(font)


class TaskVariableGroup(QGroupBox):
    latency_selected = pyqtSignal(str)

    def __init__(self, task_id, task_name, latency_var_name):
        super().__init__(str(task_name))
        self.task_id = int(task_id)
        self.task_name = str(task_name)
        self.latency_var_name = str(latency_var_name)
        set_section_kind(self, task_section_kind(self.task_id))

        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.input_layout = self._port_column()
        self.output_layout = self._port_column()
        root.addLayout(self.input_layout)

        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.VLine)
        self.divider.setFrameShadow(QFrame.Sunken)
        self.divider.setVisible(False)
        root.addWidget(self.divider)
        root.addLayout(self.output_layout)

        self.latency_label = _LatencyLabel(self.latency_var_name)
        self.latency_label.setParent(self)
        self.latency_label.selected.connect(self.latency_selected)
        self._update_minimum_width()

    @staticmethod
    def _column_minimum_width(layout):
        width = 0
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is None:
                continue
            width = max(width, widget.minimumWidth(), widget.sizeHint().width())
        return width

    def _update_minimum_width(self):
        title_width = self.fontMetrics().horizontalAdvance(self.task_name)
        title_minimum = title_width + self.latency_label.width() + 28

        input_width = self._column_minimum_width(self.input_layout)
        output_width = self._column_minimum_width(self.output_layout)
        content_minimum = input_width + output_width + 12
        if input_width and output_width:
            content_minimum += self.divider.sizeHint().width() + 12

        self.setMinimumWidth(max(title_minimum, content_minimum))
        self.updateGeometry()

    def _position_latency_label(self):
        option = QStyleOptionGroupBox()
        self.initStyleOption(option)
        title_rect = self.style().subControlRect(
            QStyle.CC_GroupBox,
            option,
            QStyle.SC_GroupBoxLabel,
            self,
        )
        hint = self.latency_label.sizeHint()
        x = title_rect.right() + 5
        y = title_rect.center().y() - hint.height() // 2
        self.latency_label.setGeometry(x, y, hint.width(), hint.height())
        self.latency_label.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_latency_label()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_latency_label()

    @staticmethod
    def _port_column():
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        return column

    @staticmethod
    def _append_control(layout, widget):
        layout.addWidget(widget, alignment=Qt.AlignLeft)

    def add_port_control(self, direction, control):
        target = self.input_layout if int(direction) == 0 else self.output_layout
        self._append_control(target, control)

    @staticmethod
    def _clear_port_controls(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def set_port_controls(self, inputs, outputs):
        self._clear_port_controls(self.input_layout)
        self._clear_port_controls(self.output_layout)
        for control in inputs:
            self.add_port_control(0, control)
        for control in outputs:
            self.add_port_control(1, control)
        self.divider.setVisible(bool(inputs and outputs))
        self._update_minimum_width()

    def update_latency(self, latency_us):
        self.latency_label.setText(f"{int(latency_us)} us")
        self._position_latency_label()

    def reset_latency(self):
        self.latency_label.setText("-- us")
        self._position_latency_label()

    def set_identity(self, task_name, latency_var_name):
        self.task_name = str(task_name)
        self.latency_var_name = str(latency_var_name)
        self.setTitle(self.task_name)
        self.latency_label.var_name = self.latency_var_name
        self.latency_label.setToolTip(self.latency_var_name)
        self._update_minimum_width()
        self._position_latency_label()

    def set_latency_selected(self, selected):
        self.latency_label.set_selected(selected)
