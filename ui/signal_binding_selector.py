"""Hierarchical signal selection for visualization inputs."""

from dataclasses import dataclass

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QSizePolicy, QWidget

from ui.task_variable_group import task_section_kind


_CATEGORY_LABELS = {
    "business": "Business",
    "device": "Device",
    "system": "System",
    "node": "Node",
    "task": "Task",
    "derived": "Derived",
    "external": "External",
}
_CATEGORY_ORDER = {key: order for order, key in enumerate(_CATEGORY_LABELS)}


@dataclass(frozen=True)
class SignalChoice:
    variable: str
    category: str
    category_label: str
    owner: str
    owner_label: str
    signal_label: str
    order: tuple


def _task_parts(variable, descriptor):
    owner = str(descriptor.get("owner") or "").strip()
    direction = descriptor.get("direction")
    display_name = str(
        descriptor.get("display_name") or descriptor.get("name") or ""
    ).strip()
    if direction not in (None, ""):
        direction = int(direction)

    parts = variable.split(".")
    if not owner and len(parts) >= 3 and parts[1].lower() in ("input", "output"):
        owner = parts[0]
    if direction in (None, "") and len(parts) >= 3:
        direction_name = parts[1].lower()
        if direction_name == "input":
            direction = 0
        elif direction_name == "output":
            direction = 1
    if not display_name:
        display_name = parts[-1]
    return owner or "Task", direction, display_name


def signal_choice(variable, descriptor=None):
    variable = str(variable)
    descriptor = dict(descriptor or {})
    kind = str(descriptor.get("descriptor_kind") or "").lower()
    category = str(descriptor.get("category") or "").lower()

    if kind in ("task_port", "task_latency") or category == "task" or (
        ".input." in variable.lower() or ".output." in variable.lower()
    ):
        owner, direction, display_name = _task_parts(variable, descriptor)
        task_id = descriptor.get("task_id")
        task_domain = (
            task_section_kind(task_id) if task_id not in (None, "") else ""
        )
        domain = task_domain or "task"
        direction_label = {0: "Input", 1: "Output"}.get(direction, "Runtime")
        task_order = descriptor.get("task_order")
        task_order = int(
            task_order if task_order not in (None, "") else task_id or 0
        )
        slot = descriptor.get("slot")
        slot = int(slot if slot not in (None, "") else 0)
        return SignalChoice(
            variable=variable,
            category=domain,
            category_label=_CATEGORY_LABELS[domain],
            owner=owner,
            owner_label=owner,
            signal_label=f"{direction_label} / {display_name}",
            order=(
                _CATEGORY_ORDER[domain],
                task_order,
                int(direction) if direction in (0, 1) else 2,
                slot,
                display_name.lower(),
            ),
        )

    if kind == "data_node" or category == "dataflow":
        group = str(descriptor.get("group") or "").strip()
        if not group:
            section = str(descriptor.get("section") or "").strip()
            group = section.split("/", 1)[-1] if section else "Dataflow"
        display_name = str(
            descriptor.get("display_name")
            or descriptor.get("name")
            or variable.split(".")[-1]
        )
        group_order = descriptor.get("group_order")
        group_order = int(group_order if group_order not in (None, "") else 0)
        node_no = descriptor.get("node_no")
        node_no = int(node_no if node_no not in (None, "") else 0)
        return SignalChoice(
            variable=variable,
            category="node",
            category_label=_CATEGORY_LABELS["node"],
            owner=group,
            owner_label=group,
            signal_label=display_name,
            order=(
                _CATEGORY_ORDER["node"],
                group_order,
                node_no,
                display_name.lower(),
            ),
        )

    if variable.startswith(("Mocap_", "Wing1_", "Wing2_")):
        owner = "MoCap"
    elif variable in ("F_X", "F_Y", "F_Z", "T_X", "T_Y", "T_Z"):
        owner = "Bota FT"
    else:
        owner = str(descriptor.get("owner") or descriptor.get("section") or "Other")
    domain = "derived" if category == "derived" else "external"
    display_name = str(
        descriptor.get("display_name")
        or descriptor.get("name")
        or variable
    )
    return SignalChoice(
        variable=variable,
        category=domain,
        category_label=_CATEGORY_LABELS[domain],
        owner=owner,
        owner_label=owner,
        signal_label=display_name,
        order=(
            _CATEGORY_ORDER[domain],
            owner.lower(),
            display_name.lower(),
        ),
    )


def build_signal_choices(variables, descriptors=None):
    descriptors = descriptors or {}
    return sorted(
        (signal_choice(name, descriptors.get(name)) for name in set(variables)),
        key=lambda choice: choice.order,
    )


class SignalBindingSelector(QWidget):
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._choices = []
        self._by_category = {}
        self._by_owner = {}

        self.category_combo = QComboBox(self)
        self.owner_combo = QComboBox(self)
        self.signal_combo = QComboBox(self)
        self.category_combo.setMinimumContentsLength(7)
        self.owner_combo.setMinimumContentsLength(12)
        self.signal_combo.setMinimumContentsLength(14)
        self.category_combo.setFixedWidth(100)
        self.owner_combo.setFixedWidth(130)
        self.signal_combo.setMinimumWidth(138)
        adjust_policy = QComboBox.AdjustToMinimumContentsLengthWithIcon
        self.category_combo.setSizeAdjustPolicy(adjust_policy)
        self.owner_combo.setSizeAdjustPolicy(adjust_policy)
        self.signal_combo.setSizeAdjustPolicy(adjust_policy)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.category_combo)
        layout.addWidget(self.owner_combo)
        layout.addWidget(self.signal_combo, 1)

        self.category_combo.currentIndexChanged.connect(self._category_changed)
        self.owner_combo.currentIndexChanged.connect(self._owner_changed)
        self.signal_combo.currentIndexChanged.connect(self._signal_changed)

    def currentData(self):
        return self.signal_combo.currentData() or ""

    def findData(self, variable):
        for index, choice in enumerate(self._choices):
            if choice.variable == variable:
                return index
        return -1

    def set_choices(self, choices, selected=""):
        self._updating = True
        self._choices = list(choices)
        self._by_category = {}
        for choice in self._choices:
            self._by_category.setdefault(choice.category, []).append(choice)

        selected_choice = next(
            (choice for choice in self._choices if choice.variable == selected),
            None,
        )
        self.category_combo.clear()
        self.category_combo.addItem("Not bound", "")
        seen = set()
        for choice in self._choices:
            if choice.category in seen:
                continue
            seen.add(choice.category)
            self.category_combo.addItem(choice.category_label, choice.category)
        category = selected_choice.category if selected_choice else ""
        self.category_combo.setCurrentIndex(
            max(0, self.category_combo.findData(category))
        )
        owner = selected_choice.owner if selected_choice else ""
        self._populate_owners(category, owner)
        self._populate_signals(
            category,
            owner,
            selected,
        )
        self._updating = False
        self._update_tooltip()

    def _populate_owners(self, category, selected_owner=""):
        self.owner_combo.clear()
        self._by_owner = {}
        for choice in self._by_category.get(category, ()):
            self._by_owner.setdefault(choice.owner, []).append(choice)
        for owner, choices in self._by_owner.items():
            self.owner_combo.addItem(choices[0].owner_label, owner)
        self.owner_combo.setEnabled(bool(self._by_owner))
        selected = self.owner_combo.findData(selected_owner)
        self.owner_combo.setCurrentIndex(max(0, selected))

    def _populate_signals(self, category, owner, selected=""):
        self.signal_combo.clear()
        choices = self._by_owner.get(owner, ()) if category else ()
        for choice in choices:
            self.signal_combo.addItem(choice.signal_label, choice.variable)
        self.signal_combo.setEnabled(bool(choices))
        selected_index = self.signal_combo.findData(selected)
        self.signal_combo.setCurrentIndex(max(0, selected_index))

    def _category_changed(self):
        if self._updating:
            return
        self._updating = True
        category = self.category_combo.currentData() or ""
        self._populate_owners(category)
        owner = self.owner_combo.currentData() or ""
        self._populate_signals(category, owner)
        self._updating = False
        self._selection_changed()

    def _owner_changed(self):
        if self._updating:
            return
        self._updating = True
        category = self.category_combo.currentData() or ""
        owner = self.owner_combo.currentData() or ""
        self._populate_signals(category, owner)
        self._updating = False
        self._selection_changed()

    def _signal_changed(self):
        if not self._updating:
            self._selection_changed()

    def _selection_changed(self):
        self._update_tooltip()
        self.selectionChanged.emit()

    def _update_tooltip(self):
        variable = self.currentData()
        self.setToolTip(variable)
        self.signal_combo.setToolTip(variable)
