from PyQt5.QtCore import QEvent, QMimeData, QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLayout,
    QStyle,
    QStyleOptionGroupBox,
    QWidget,
)


class ReorderableSectionContainer(QWidget):
    """Owns the visual order of horizontally arranged section group boxes."""

    order_changed = pyqtSignal(list)
    MIME_TYPE = "application/x-neuroflap-section"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self.grid = QGridLayout(self)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid.setSizeConstraint(QLayout.SetMinimumSize)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)

        self._order = []
        self._widgets = {}
        self._section_for_widget = {}
        self._pressed_section = None
        self._press_pos = QPoint()
        self._drag_original_order = None

        self._drop_indicator = QFrame(self)
        self._drop_indicator.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_indicator.setStyleSheet(
            "border: 2px dashed #4EA1FF; background-color: transparent;"
        )
        self._drop_indicator.hide()

    def section_order(self):
        return list(self._order)

    def set_sections(self, order, widgets):
        widgets = {str(key): widget for key, widget in widgets.items() if widget is not None}
        normalized = [str(key) for key in order if str(key) in widgets]
        normalized.extend(key for key in widgets if key not in normalized)

        for widget in set(self._widgets.values()) - set(widgets.values()):
            widget.removeEventFilter(self)
            widget.unsetCursor()
        for key, widget in widgets.items():
            if widget not in self._section_for_widget:
                widget.installEventFilter(self)
                widget.setAttribute(Qt.WA_Hover, True)
                widget.setCursor(Qt.ArrowCursor)

        self._widgets = widgets
        self._section_for_widget = {widget: key for key, widget in widgets.items()}
        self._order = normalized
        self._relayout()

    def move_section(self, section, target_index, emit=True):
        section = str(section)
        if section not in self._order:
            return False
        remaining = [key for key in self._order if key != section]
        target_index = max(0, min(int(target_index), len(remaining)))
        reordered = list(remaining)
        reordered.insert(target_index, section)
        if reordered == self._order:
            return False
        self._order = reordered
        self._relayout()
        if emit:
            self.order_changed.emit(self.section_order())
        return True

    def _relayout(self):
        while self.grid.count():
            self.grid.takeAt(0)
        for index, section in enumerate(self._order):
            widget = self._widgets.get(section)
            if widget is not None:
                self.grid.addWidget(widget, 0, index, alignment=Qt.AlignTop | Qt.AlignLeft)
        self.adjustSize()

    def _show_drop_indicator(self, section):
        widget = self._widgets.get(str(section))
        if widget is None:
            self._drop_indicator.hide()
            return
        self._drop_indicator.setGeometry(widget.geometry().adjusted(-2, -2, 2, 2))
        self._drop_indicator.raise_()
        self._drop_indicator.show()

    def _hide_drop_indicator(self):
        self._drop_indicator.hide()

    @staticmethod
    def _is_title_press(widget, pos):
        if not isinstance(widget, QGroupBox):
            return False
        option = QStyleOptionGroupBox()
        widget.initStyleOption(option)
        title_rect = widget.style().subControlRect(
            QStyle.CC_GroupBox,
            option,
            QStyle.SC_GroupBoxLabel,
            widget,
        )
        return title_rect.adjusted(-4, -3, 4, 3).contains(pos)

    def eventFilter(self, watched, event):
        section = self._section_for_widget.get(watched)
        if section is None:
            return super().eventFilter(watched, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._is_title_press(watched, event.pos()):
                self._pressed_section = section
                self._press_pos = event.pos()
        elif event.type() == QEvent.HoverMove:
            cursor = Qt.OpenHandCursor if self._is_title_press(watched, event.pos()) else Qt.ArrowCursor
            watched.setCursor(cursor)
        elif event.type() == QEvent.HoverLeave:
            watched.setCursor(Qt.ArrowCursor)
        elif event.type() == QEvent.MouseMove and self._pressed_section == section:
            if event.buttons() & Qt.LeftButton:
                distance = (event.pos() - self._press_pos).manhattanLength()
                if distance >= 10:
                    self._start_drag(section, watched, self._press_pos)
                    self._pressed_section = None
                    return True
        elif event.type() == QEvent.MouseButtonRelease:
            self._pressed_section = None

        return super().eventFilter(watched, event)

    def _start_drag(self, section, widget, hot_spot):
        self._drag_original_order = self.section_order()
        self._show_drop_indicator(section)
        drag = QDrag(widget)
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, section.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(widget.grab())
        drag.setHotSpot(hot_spot)
        widget.setCursor(Qt.ClosedHandCursor)
        result = drag.exec_(Qt.MoveAction)
        widget.setCursor(Qt.ArrowCursor)
        if result != Qt.MoveAction and self._drag_original_order is not None:
            self._order = self._drag_original_order
            self._relayout()
        self._hide_drop_indicator()
        self._drag_original_order = None

    def _dragged_section(self, event):
        mime = event.mimeData()
        if not mime.hasFormat(self.MIME_TYPE):
            return None
        try:
            section = bytes(mime.data(self.MIME_TYPE)).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None
        return section if section in self._widgets else None

    def dragEnterEvent(self, event):
        if self._dragged_section(event) is not None:
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        section = self._dragged_section(event)
        if section is None:
            event.ignore()
            return

        remaining = [key for key in self._order if key != section]
        target_index = len(remaining)
        for index, key in enumerate(remaining):
            widget = self._widgets[key]
            if event.pos().x() < widget.geometry().center().x():
                target_index = index
                break
        self.move_section(section, target_index, emit=False)
        self._show_drop_indicator(section)
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._hide_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._dragged_section(event) is None:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self._hide_drop_indicator()
        self.order_changed.emit(self.section_order())
