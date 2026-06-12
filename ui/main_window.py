from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLabel, QSpinBox, QGridLayout, QMessageBox, QLineEdit, QComboBox, QFrame, QTabWidget, QGroupBox,
    QScrollArea, QLayout, QColorDialog, QDoubleSpinBox
)
from PyQt5.QtCore import QEvent, QPointF, QTimer, Qt
from bisect import bisect_left
import math
from pyqtgraph.exporters import CSVExporter
import pyqtgraph as pg
import time
from datetime import datetime
import os
import serial.tools.list_ports

from data_transporter import DataTransporter
from ui.RelativeTimeAxis import RelativeTimeAxis
from data_model import DataModel
from data_receiver import DataReceiver
from data_transporter_thread import DataTransporterThread
from ui.variable_control import VariableControlItem
from waveform_capture import WaveformCaptureWindow
from enum import Enum

'''
CURRENT STATE  |    start           stop            clear
IDLE           |    RUNNING         ----            ----                
RUNNING        |    ----            STOPPING        CLEARING
STOPPED        |    RUNNING         ----            CLEARING

STOPPING -> redraw current plot data -> STOPPED
CLEARING -> (clear all points) -> IDLE

Plot data pipeline:
DataModel source -> curve transform -> time-window clip -> PlotWidget.
AutoX controls the clip window rule. Pan/zoom controls the ViewBox and exits
AutoX, but does not rewrite t_now_line. Pause exits AutoX/AutoY and freezes
t_now_line; resume restores the Auto states from before pause.
'''


class PlotState(Enum):
    IDLE = 0  # 鍒濆鏈帴鏀?
    RUNNING = 1  # 姝ｅ湪鎺ユ敹
    STOPPING = 2  # 姝ｅ湪鏆傚仠
    STOPPED = 3  # 鎺ユ敹鏆傚仠
    CLEARING = 4  # 姝ｅ湪娓呴櫎鏁版嵁


class PlotWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor v2.3.0")

        self.tf_variables = ["F_X", "F_Y", "F_Z", "T_X", "T_Y", "T_Z"]
        self.mocap_variable_templates = [
            ("Mocap_pitch", True), ("Mocap_roll", True), ("Mocap_yaw", True),
            ("Mocap_X", True), ("Mocap_Y", True), ("Mocap_Z", True),
            ("Mocap_AVX", False), ("Mocap_AVY", False), ("Mocap_AVZ", False),
            ("Mocap_AAX", False), ("Mocap_AAY", False), ("Mocap_AAZ", False),
            ("Mocap_SpeedX", True), ("Mocap_SpeedY", True), ("Mocap_SpeedZ", True),
            ("Mocap_AccX", True), ("Mocap_AccY", True), ("Mocap_AccZ", True),
            ("Mocap_Speed", True), ("Mocap_Acc", True),
            ("Mocap_qx", False), ("Mocap_qy", False), ("Mocap_qz", False), ("Mocap_qw", False),
            ("Mocap_Quality", False),
            ("Wing1_pitch", True), ("Wing1_roll", True), ("Wing1_yaw", True),
            ("Wing1_X", True), ("Wing1_Y", True), ("Wing1_Z", True),
            ("Wing1_AVX", False), ("Wing1_AVY", False), ("Wing1_AVZ", False),
            ("Wing1_AAX", False), ("Wing1_AAY", False), ("Wing1_AAZ", False),
            ("Wing1_SpeedX", True), ("Wing1_SpeedY", True), ("Wing1_SpeedZ", True),
            ("Wing1_AccX", True), ("Wing1_AccY", True), ("Wing1_AccZ", True),
            ("Wing1_Speed", True), ("Wing1_Acc", True),
            ("Wing1_qx", False), ("Wing1_qy", False), ("Wing1_qz", False), ("Wing1_qw", False),
            ("Wing1_Quality", False),
            ("Wing2_pitch", True), ("Wing2_roll", True), ("Wing2_yaw", True),
            ("Wing2_X", True), ("Wing2_Y", True), ("Wing2_Z", True),
            ("Wing2_AVX", False), ("Wing2_AVY", False), ("Wing2_AVZ", False),
            ("Wing2_AAX", False), ("Wing2_AAY", False), ("Wing2_AAZ", False),
            ("Wing2_SpeedX", True), ("Wing2_SpeedY", True), ("Wing2_SpeedZ", True),
            ("Wing2_AccX", True), ("Wing2_AccY", True), ("Wing2_AccZ", True),
            ("Wing2_Speed", True), ("Wing2_Acc", True),
            ("Wing2_qx", False), ("Wing2_qy", False), ("Wing2_qz", False), ("Wing2_qw", False),
            ("Wing2_Quality", False),
            ("Marker_Id", False), ("Marker_Group", False),
            ("Marker_X", False), ("Marker_Y", False), ("Marker_Z", False),
        ]

        # All plotted variables: TF fixed + MoCap fixed + ESP32 dynamic.
        self.signal_variables = []
        self.dynamic_signal_variables = []
        self.default_visible_count = 8

        # 缁樺浘绐楀彛
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.enableAutoRange(axis=1, enable=False)
        self.view_box = self.plot_widget.getViewBox()
        self.view_box.sigRangeChangedManually.connect(self.manual_scroll)
        self.curves = {}  # 鍙橀噺鍚?-> 鏇茬嚎
        self.colors = {}  # 褰撳墠棰滆壊
        self.default_colors = {}  # 榛樿棰滆壊
        self.curve_transforms = {}
        self.selected_var_name = None
        self.selected_curve_focus_active = False
        self.selected_hover_point = None
        self.hover_hit_px = 48.0
        self._plot_mouse_press_curve_selected = False
        self._updating_selected_controls = False
        self.fully_plotted = False
        self.auto_scroll_enabled = True
        self.auto_scroll_enabled_before_pause = True
        self.auto_y_enabled = True
        self.auto_y_enabled_before_pause = True

        # 鏃堕棿杞村彉閲?
        self.reception_start_time = time.time() * 1000  # ms
        self.window_start = time.time() * 1000  # ms 鍒濆涓虹▼搴忓惎鍔ㄦ椂
        self.window_now = time.time() * 1000
        # 鏁版嵁妯″瀷涓庢敹鍙戝櫒
        self.sdk_ip = "172.16.23.64"
        self.esp32_ip = "192.168.4.1"
        self.esp32_port = 28090
        self.rigid_id = "Rigid_Body"
        self.rigid_wing1_id = "Rigid_Wing_L"
        self.rigid_wing2_id = "Rigid_Wing_R"
        static_variables = self.tf_variables + [name for name, _ in self.mocap_variable_templates]
        self.data_model = DataModel(static_variables)
        # self.data_transporter = None
        self.data_transporter = DataTransporter(self.esp32_ip, self.esp32_port)
        self.data_receiver = DataReceiver(self.data_model, self)
        self.data_receiver.start()
        # 瀛愮獥鍙?
        self.waveform_capture_window = None

        # csv filename edit
        self.export_filename_edit = QLineEdit(self)
        self.export_filename_edit.setFixedWidth(130)  # 鍗曚綅鏄儚绱?
        self.export_filename_edit.setPlaceholderText("filename")

        # CSV export button
        self.export_button = QPushButton("Export CSV", self)
        self.export_button.clicked.connect(self.export_csv)

        self.window_spin = QSpinBox()
        self.window_spin.setRange(1, 60)
        self.fixed_window_seconds = 5
        self.window_spin.setValue(self.fixed_window_seconds)
        self.window_spin.setSuffix(" s")
        self.window_spin.valueChanged.connect(self.update_window_duration)

        self.auto_x = QCheckBox("AutoX")
        self.auto_x.setChecked(True)
        self.auto_x.stateChanged.connect(self.set_auto_scroll_enabled)

        self.auto_y = QCheckBox("AutoY")
        self.auto_y.setChecked(True)
        self.auto_y.stateChanged.connect(self.set_auto_y_enabled)

        # ===== 涓嬮儴鎺ユ敹鎺у埗鍖?=====

        self.toggle_reception_btn = QPushButton("Start Receive")
        self.toggle_reception_btn.setStyleSheet("background-color: orange")
        self.toggle_reception_btn.clicked.connect(self.toggle_reception)

        self.clear_btn = QPushButton("Clear Plot")
        self.clear_btn.clicked.connect(self.clear_data)

        self.auto_scale_btn = QPushButton("Auto Scale")
        self.auto_scale_btn.setStyleSheet("background-color: lightblue")
        self.auto_scale_btn.clicked.connect(self.auto_scale_all)

        self.open_capture_btn = QPushButton("Waveform Capture")
        self.open_capture_btn.clicked.connect(self.open_waveform_capture)

        self.nf_ip_input = QLineEdit(self.esp32_ip)
        self.nf_ip_input.setFixedWidth(140)
        self.nf_port_input = QLineEdit("28080")
        self.nf_port_input.setFixedWidth(80)
        self.nf_connect_btn = QPushButton("Connect")
        self.nf_connect_btn.clicked.connect(self.connect_nfv1)
        self.nf_disconnect_btn = QPushButton("Disconnect")
        self.nf_disconnect_btn.clicked.connect(self.disconnect_nfv1)
        self.nf_status_label = QLabel("● Disconnected")
        self.nf_status_label.setStyleSheet("color: #808080;")
        self.nf_local_ip_label = QLabel("0.0.0.0")
        self.nf_busy_label = QLabel("")
        self.nf_busy_label.setVisible(False)

        # ===== 鍙橀噺鍕鹃€夊尯鍩?=====
        self.var_controls = {}
        self.signal_export_grid = None
        self.signal_export_scroll = None
        self.signal_export_container = None
        self.signal_export_count = 0
        self.signal_export_sections = {}
        self.signal_export_section_order = []
        self.tf_signal_grid = None
        self.tf_signal_count = 0
        self.mocap_signal_grid = None
        self.mocap_signal_count = 0
        self.dynamic_signal_sections = {}

        # Variable area: split by tabs.
        variable_layout = QHBoxLayout()

        # === 宸﹁竟 ESP32鍙橀噺===

        # === 鍙宠竟 鍏跺畠鍙橀噺===

        # 涓插彛閫夋嫨涓庤繛鎺ュ姏浼犳劅鍣ㄦ寜閽?
        port_label = QLabel("Bota Port:")

        self.serial_combo = QComboBox()
        self.serial_combo.setFixedWidth(130)
        self.refresh_serial_ports()

        self.toggle_bota_btn = QPushButton("Connect Sensor")
        self.toggle_bota_btn.setStyleSheet("background-color: orange")
        self.toggle_bota_btn.setCheckable(True)
        self.toggle_bota_btn.clicked.connect(self.toggle_bota_connection)

        # Bias 璁剧疆鎸夐挳
        self.bias_button = QPushButton("Bias")
        self.bias_button.setStyleSheet("background-color: lightblue")
        self.bias_button.clicked.connect(self.data_receiver.set_ft_bias)
        # self.bias_button.clicked.connect(self.data_receiver.set_ft_bias)  # 鍋囪浣犲湪 data_receiver 涓畾涔変簡 set_ft_bias 鏂规硶

        # 鍔涗紶鎰熷櫒鐘舵€佹樉绀?
        self.bota_status_label = QLabel("state:" + self.data_receiver.bota_state)
        self.bota_status_label.setFixedHeight(24)
        self.bota_status_label.setAlignment(Qt.AlignCenter)

        # TF fixed variables + ESP32 dynamic variables.
        tf_signal_grid = QGridLayout()
        self.tf_signal_grid = tf_signal_grid

        # Dynamic signal controls from ESP32 schema response.
        signal_export_scroll = QScrollArea()
        signal_export_scroll.setWidgetResizable(False)
        signal_export_scroll.setFrameShape(QFrame.NoFrame)
        signal_export_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        signal_export_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        signal_export_container = QWidget()
        signal_export_grid = QGridLayout(signal_export_container)
        signal_export_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        signal_export_grid.setSizeConstraint(QLayout.SetMinimumSize)
        signal_export_grid.setContentsMargins(0, 0, 0, 0)
        signal_export_grid.setHorizontalSpacing(8)
        signal_export_grid.setVerticalSpacing(8)
        signal_export_scroll.setWidget(signal_export_container)
        self.signal_export_scroll = signal_export_scroll
        self.signal_export_container = signal_export_container
        self.signal_export_grid = signal_export_grid

        # MoCap fixed variables.
        mocap_signal_grid = QGridLayout()
        self.mocap_signal_grid = mocap_signal_grid

        # 鎺ユ敹mocap琛?
        mocap_rx_layout = QHBoxLayout()
        mocap_rx_layout.addWidget(QLabel("MoCap SDK IP:"))

        # 娣诲姞 IP 杈撳叆妗嗭紝璁剧疆榛樿鍊?
        self.mocap_ip_input = QLineEdit()
        self.mocap_ip_input.setText(self.sdk_ip)
        self.mocap_ip_input.setFixedWidth(130)  # 鍙€夛細闄愬埗瀹藉害
        mocap_rx_layout.addWidget(self.mocap_ip_input)

        mocap_rx_layout.addWidget(QLabel("Rigid:"))
        self.mocap_rigid_input = QLineEdit()
        self.mocap_rigid_input.setText(self.rigid_id)
        self.mocap_rigid_input.setFixedWidth(130)  # 鍙€夛細闄愬埗瀹藉害
        mocap_rx_layout.addWidget(self.mocap_rigid_input)

        mocap_rx_layout.addWidget(QLabel("Wing1:"))
        self.mocap_rigid_wing1_input = QLineEdit()
        self.mocap_rigid_wing1_input.setText(self.rigid_wing1_id)
        self.mocap_rigid_wing1_input.setFixedWidth(130)  # 鍙€夛細闄愬埗瀹藉害
        mocap_rx_layout.addWidget(self.mocap_rigid_wing1_input)

        mocap_rx_layout.addWidget(QLabel("Wing2:"))
        self.mocap_rigid_wing2_input = QLineEdit()
        self.mocap_rigid_wing2_input.setText(self.rigid_wing2_id)
        self.mocap_rigid_wing2_input.setFixedWidth(130)  # 鍙€夛細闄愬埗瀹藉害
        mocap_rx_layout.addWidget(self.mocap_rigid_wing2_input)

        mocap_rx_layout.addStretch()

        self.R_MoCap_button = QPushButton("Receive from MoCap")
        self.R_MoCap_button.setStyleSheet("background-color: orange")
        self.R_MoCap_button.setCheckable(True)
        self.R_MoCap_button.clicked.connect(self.toggle_mocap)
        mocap_rx_layout.addWidget(self.R_MoCap_button)

        # 鍥炰紶esp琛?
        mocap_tx_layout = QHBoxLayout()
        mocap_tx_layout.addWidget(QLabel("ESP32 UDP IP:"))

        # 娣诲姞 IP 杈撳叆妗嗭紝璁剧疆榛樿鍊?
        self.esp32_rx_ip_input = QLineEdit()
        self.esp32_rx_ip_input.setText("192.168.4.1")
        self.esp32_rx_ip_input.setFixedWidth(130)  # 鍙€夛細闄愬埗瀹藉害

        mocap_tx_layout.addWidget(self.esp32_rx_ip_input)

        mocap_tx_layout.addWidget(QLabel("PORT:"))

        self.esp32_rx_port_input = QLineEdit()
        self.esp32_rx_port_input.setText("28090")
        self.esp32_rx_port_input.setFixedWidth(100)  # 鍙€夛細闄愬埗瀹藉害
        mocap_tx_layout.addWidget(self.esp32_rx_port_input)

        mocap_tx_layout.addStretch()

        self.T_Esp32_button = QPushButton("Transport to ESP32")
        self.T_Esp32_button.setStyleSheet("background-color: orange")
        self.T_Esp32_button.setCheckable(True)
        self.T_Esp32_button.clicked.connect(self.toggle_transport)
        mocap_tx_layout.addWidget(self.T_Esp32_button)

        for var_name in self.tf_variables:
            self._register_static_variable(
                var_name=var_name,
                checked=False,
                grid=self.tf_signal_grid,
                columns=3,
                count_attr="tf_signal_count",
                show_control=True,
            )

        for var_name, visible in self.mocap_variable_templates:
            self._register_static_variable(
                var_name=var_name,
                checked=False,
                grid=self.mocap_signal_grid,
                columns=6,
                count_attr="mocap_signal_count",
                show_control=visible,
            )

        port_layout = QHBoxLayout()
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.serial_combo)
        port_layout.addWidget(self.toggle_bota_btn)
        port_layout.addWidget(self.bota_status_label)
        port_layout.addStretch()
        port_layout.addWidget(self.bias_button)

        neuroflap_page = QWidget()
        neuroflap_page_layout = QVBoxLayout(neuroflap_page)
        neuroflap_page_layout.setContentsMargins(4, 4, 4, 4)
        neuroflap_page_layout.setSpacing(3)
        nfv1_ctrl_layout = QHBoxLayout()
        nfv1_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        nfv1_ctrl_layout.setSpacing(6)
        nfv1_ctrl_layout.addWidget(QLabel("Local IP:"))
        nfv1_ctrl_layout.addWidget(self.nf_local_ip_label)
        nfv1_ctrl_layout.addWidget(QLabel("ESP32 IP:"))
        nfv1_ctrl_layout.addWidget(self.nf_ip_input)
        nfv1_ctrl_layout.addWidget(QLabel("Port:"))
        nfv1_ctrl_layout.addWidget(self.nf_port_input)
        nfv1_ctrl_layout.addWidget(self.nf_connect_btn)
        nfv1_ctrl_layout.addWidget(self.nf_disconnect_btn)
        nfv1_ctrl_layout.addWidget(self.nf_status_label)
        nfv1_ctrl_layout.addStretch()
        neuroflap_page_layout.addLayout(nfv1_ctrl_layout)
        neuroflap_page_layout.addWidget(self.nf_busy_label)
        neuroflap_page_layout.addWidget(QLabel("ESP32 Signal Export (Dynamic):"))
        neuroflap_page_layout.addWidget(signal_export_scroll, 1)

        bota_page = QWidget()
        bota_page_layout = QVBoxLayout(bota_page)
        bota_page_layout.addLayout(port_layout)
        bota_page_layout.addWidget(QLabel("Bota FT Variables (Fixed 6):"))
        bota_page_layout.addLayout(tf_signal_grid)
        bota_page_layout.addStretch()

        mocap_page = QWidget()
        mocap_page_layout = QVBoxLayout(mocap_page)
        mocap_page_layout.addLayout(mocap_rx_layout)
        mocap_page_layout.addLayout(mocap_tx_layout)
        mocap_page_layout.addWidget(QLabel("MoCap Variables:"))
        mocap_page_layout.addLayout(mocap_signal_grid)
        mocap_page_layout.addStretch()

        tab_widget = QTabWidget()
        tab_widget.addTab(neuroflap_page, "NeuroFlap")
        tab_widget.addTab(bota_page, "Bota FT")
        tab_widget.addTab(mocap_page, "MoCap")

        # 浜岀骇甯冨眬
        setting_layout = QHBoxLayout()
        setting_layout.addWidget(QLabel("CSV Filename:"))
        setting_layout.addWidget(self.export_filename_edit)
        setting_layout.addWidget(self.export_button)
        setting_layout.addStretch()
        setting_layout.addWidget(QLabel("Window Width:"))
        setting_layout.addWidget(self.window_spin)
        setting_layout.addWidget(self.auto_x)
        setting_layout.addWidget(self.auto_y)

        control_layout = QHBoxLayout()
        control_layout.addWidget(self.toggle_reception_btn)
        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.auto_scale_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.open_capture_btn)

        selected_plot_layout = QHBoxLayout()
        selected_plot_layout.setContentsMargins(0, 0, 0, 0)
        selected_plot_layout.setSpacing(6)
        self.selected_plot_value = QLabel("-")
        self.selected_plot_value.setMinimumWidth(180)
        self.selected_coord_value = QLabel("")
        self.selected_coord_value.setMinimumWidth(150)

        self.selected_color_btn = QPushButton()
        self.selected_color_btn.setFixedSize(42, 22)
        self.selected_color_btn.clicked.connect(self.change_selected_curve_color)

        self.selected_phase_spin = QDoubleSpinBox()
        self.selected_phase_spin.setRange(-3600000.0, 3600000.0)
        self.selected_phase_spin.setDecimals(3)
        self.selected_phase_spin.setSingleStep(10.0)
        self.selected_phase_spin.setSuffix(" ms")
        self.selected_phase_spin.valueChanged.connect(self._selected_transform_changed)

        self.selected_offset_spin = QDoubleSpinBox()
        self.selected_offset_spin.setRange(-1000000000.0, 1000000000.0)
        self.selected_offset_spin.setDecimals(6)
        self.selected_offset_spin.setSingleStep(1.0)
        self.selected_offset_spin.valueChanged.connect(self._selected_transform_changed)

        self.selected_scale_spin = QDoubleSpinBox()
        self.selected_scale_spin.setRange(-1000000000.0, 1000000000.0)
        self.selected_scale_spin.setDecimals(6)
        self.selected_scale_spin.setSingleStep(0.1)
        self.selected_scale_spin.valueChanged.connect(self._selected_transform_changed)

        selected_plot_layout.addWidget(QLabel("Selected plot:"))
        selected_plot_layout.addWidget(self.selected_plot_value)
        selected_plot_layout.addWidget(self.selected_coord_value)
        selected_plot_layout.addWidget(QLabel("color:"))
        selected_plot_layout.addWidget(self.selected_color_btn)
        selected_plot_layout.addWidget(QLabel("phase:"))
        selected_plot_layout.addWidget(self.selected_phase_spin)
        selected_plot_layout.addWidget(QLabel("offset:"))
        selected_plot_layout.addWidget(self.selected_offset_spin)
        selected_plot_layout.addWidget(QLabel("scale:"))
        selected_plot_layout.addWidget(self.selected_scale_spin)
        selected_plot_layout.addStretch()
        self._update_selected_controls()

        hline_1 = QFrame()
        hline_1.setFrameShape(QFrame.HLine)
        hline_1.setFrameShadow(QFrame.Sunken)
        hline_1.setLineWidth(1)

        variable_layout.addWidget(tab_widget, 1)

        # 涓€绾у竷灞€
        main_layout = QVBoxLayout()
        main_layout.addLayout(setting_layout)
        main_layout.addWidget(self.plot_widget, 1)
        main_layout.addLayout(selected_plot_layout)
        main_layout.addLayout(control_layout)
        main_layout.addWidget(hline_1)  # 鈫?鎻掑叆姘村钩鍒嗛殧绾?
        main_layout.addLayout(variable_layout)
        self.setLayout(main_layout)
        self.setFocusPolicy(Qt.StrongFocus)
        self.plot_widget.setFocusPolicy(Qt.StrongFocus)
        self.plot_widget.setMouseTracking(True)
        self.plot_widget.viewport().setMouseTracking(True)
        self.plot_widget.installEventFilter(self)
        self.plot_widget.viewport().installEventFilter(self)

        # 鐢诲竷鍐呯敾鍏夋爣鏄剧ず鏁板瓧绛?
        self.now_line = pg.InfiniteLine(angle=90, movable=False,
                                        pen=pg.mkPen('y', width=2, style=Qt.CustomDashLine, dash=[5, 5, 1, 5]))
        self.begin_line = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen('y', width=2, style=Qt.CustomDashLine, dash=[5, 5, 1, 5]))
        self.plot_widget.addItem(self.now_line)
        self.plot_widget.addItem(self.begin_line)
        self.selected_hover_marker = pg.ScatterPlotItem(
            size=11,
            pen=pg.mkPen((255, 255, 255), width=2),
            brush=pg.mkBrush(255, 64, 64, 210),
        )
        self.selected_hover_marker.setVisible(False)
        self.plot_widget.addItem(self.selected_hover_marker)
        hover_pen = pg.mkPen((255, 0, 0, 235), width=1, style=Qt.DashLine)
        self.selected_hover_vline = pg.InfiniteLine(angle=90, movable=False, pen=hover_pen)
        self.selected_hover_hline = pg.InfiniteLine(angle=0, movable=False, pen=hover_pen)
        self.selected_hover_vline.setVisible(False)
        self.selected_hover_hline.setVisible(False)
        self.plot_widget.addItem(self.selected_hover_vline)
        self.plot_widget.addItem(self.selected_hover_hline)

        # self.plot_widget.showAxis('top', show=True)
        # self.x_axis = self.plot_widget.getAxis('top')
        self.x_axis = RelativeTimeAxis(orientation='top')
        self.plot_widget.getPlotItem().setAxisItems({'top': self.x_axis})
        self.x_axis.setStyle(showValues=True)
        self.x_axis.setTextPen(QPen(Qt.yellow))

        # 瀹氭椂鍣ㄧ敤浜庡埛鏂版洸绾?
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(20)

        # 瀹氭椂鍣ㄧ敤浜庡埛鏂板厜鏍?
        self.axis_timer = QTimer()
        self.axis_timer.timeout.connect(self.update_cursor)
        self.axis_timer.start(5)

        # 瀹氭椂鍣ㄧ敤浜庡畾鏃跺鐞嗘暟鎹?
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.data_receiver.process_data)
        self.data_timer.start(20)

        # 瀹氭椂鍣ㄧ敤浜庡畾鏃跺湪capture window鐢诲浘
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.update_capture_plot)
        self.capture_timer.start(50)

        # 閫氱敤鍔熻兘瀹氭椂鍣?
        self.misc_timer = QTimer()
        self.misc_timer.timeout.connect(self.update_misc_tasks)
        self.misc_timer.start(200)  # 200ms 鎴栨牴鎹綘瀹為檯闇€姹傝皟鏁?

        self.plot_state = PlotState.IDLE
        self.last_plot_state = PlotState.IDLE
        self.update_nfv1_status()

    def toggle_mocap(self):
        # HACK: multi rigid
        self.data_receiver.sdk_ip = self.mocap_ip_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 IP
        self.data_receiver.rigid_id = self.mocap_rigid_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 Rigid
        self.data_receiver.wing1_id = self.mocap_rigid_wing1_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 Rigid
        self.data_receiver.wing2_id = self.mocap_rigid_wing2_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 Rigid
        if self.R_MoCap_button.isChecked():
            # Start
            self.R_MoCap_button.setText("Receiving...")
            self.R_MoCap_button.setStyleSheet("background-color: lightgreen")
            # 鍙戣捣杩炴帴骞跺湪杩炴帴鎴愬姛鍚庡惎鍔ㄦ帴鏀剁嚎绋?
            self.data_receiver.connect_mocap()
        else:
            # Stop
            self.R_MoCap_button.setText("Receive from MoCap")
            self.R_MoCap_button.setStyleSheet("background-color: orange")
            self.data_receiver.disconnect_mocap()

    def toggle_transport(self):
        # try:
        #     ip = self.esp32_rx_ip_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 IP
        #     port = int(self.esp32_rx_port_input.text().strip())
        # except ValueError:
        #     QMessageBox.warning(self, "Input Error", "Port must be an integer")
        #     return
        #
        # if self.T_Esp32_button.isChecked():
        #     # Start Transport
        #     self.T_Esp32_button.setText("Transporting...")
        #     self.T_Esp32_button.setStyleSheet("background-color: lightgreen")
        #
        #     # 濡傛灉宸插瓨鍦ㄦ棫绾跨▼涓斿凡鍋滄锛屽垱寤烘柊绾跨▼瀹炰緥
        #     if self.data_transporter is None or not self.data_transporter.is_alive():
        #         self.data_transporter = DataTransporterThread(ip, port)
        #         self.data_transporter.start()
        #         print("Transport thread built ")
        #     # 寮€鍚彂閫佸紑鍏筹紙鐢?DataReceiver 浣跨敤锛?
        #     self.data_receiver.transport_enabled = True
        #     print("Transport enable ")
        # else:
        #     # Stop Transport
        #     self.T_Esp32_button.setText("Transport to ESP32")
        #     self.T_Esp32_button.setStyleSheet("background-color: orange")
        #     # 鍏抽棴鍙戦€佸紑鍏筹紝蹇呰鏃朵篃鍋滅嚎绋?
        #     self.data_receiver.transport_enabled = False
        #     print("Transport disenable ")
        #
        #     if self.data_transporter:
        #         self.data_transporter.stop()
        #         self.data_transporter.join(timeout=1.0)
        #         self.data_transporter = None  # 蹇呴』閲嶇疆浠ュ厑璁镐笅娆￠噸鏂板垱寤?
        try:
            self.data_transporter.ip = self.esp32_rx_ip_input.text().strip()  # 鑾峰彇鐢ㄦ埛杈撳叆 IP
            self.data_transporter.port = int(self.esp32_rx_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Port must be an integer")
            return

        if self.T_Esp32_button.isChecked():
            # Start Transport
            self.T_Esp32_button.setText("Transporting...")
            self.T_Esp32_button.setStyleSheet("background-color: lightgreen")

            # 寮€鍚彂閫佸紑鍏筹紙鐢?DataReceiver 浣跨敤锛?
            self.data_receiver.transport_enabled = True
            print("Transport enable ")
        else:
            # Stop Transport
            self.T_Esp32_button.setText("Transport to ESP32")
            self.T_Esp32_button.setStyleSheet("background-color: orange")
            # 鍏抽棴鍙戦€佸紑鍏筹紝蹇呰鏃朵篃鍋滅嚎绋?
            self.data_receiver.transport_enabled = False
            print("Transport disenable ")

    def connect_nfv1(self):
        target_ip = self.nf_ip_input.text().strip()
        if not target_ip:
            QMessageBox.warning(self, "Input Error", "ESP32 IP cannot be empty.")
            return
        try:
            target_port = int(self.nf_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Port must be an integer.")
            return
        self.data_receiver.connect_nfv1(target_ip, target_port)
        self.update_nfv1_status()

    def disconnect_nfv1(self):
        self.data_receiver.disconnect_nfv1()
        self.update_nfv1_status()

    def update_nfv1_status(self):
        status = self.data_receiver.get_nfv1_status()
        state = status.get("state", "disconnected")
        local_ip = status.get("local_ip", "0.0.0.0")
        self.nf_local_ip_label.setText(f"{local_ip}")

        if state == "connected":
            self.nf_status_label.setText("● Connected")
            self.nf_status_label.setStyleSheet("color: #2ca02c;")
        elif state == "connecting":
            self.nf_status_label.setText("● Connecting")
            self.nf_status_label.setStyleSheet("color: #f0ad4e;")
        elif state == "busy":
            self.nf_status_label.setText("● Busy")
            self.nf_status_label.setStyleSheet("color: #d9534f;")
        else:
            self.nf_status_label.setText("● Disconnected")
            self.nf_status_label.setStyleSheet("color: #808080;")

        busy_ip = status.get("busy_owner_ip", "")
        busy_port = int(status.get("busy_owner_port", 0))
        if busy_ip:
            self.nf_busy_label.setText(f"Occupied by: {busy_ip}:{busy_port}")
            self.nf_busy_label.setStyleSheet("color: #d9534f;")
        else:
            last_error = status.get("last_error", "")
            self.nf_busy_label.setText(last_error if last_error else "")
            self.nf_busy_label.setStyleSheet("color: #666666;")
        self.nf_busy_label.setVisible(bool(self.nf_busy_label.text()))

        self.nf_connect_btn.setEnabled(state != "connected")
        self.nf_disconnect_btn.setEnabled(state in ("connected", "connecting"))

    def update_misc_tasks(self):
        self.update_bota_status_label()
        self.update_nfv1_status()
        self.refresh_serial_ports()

    def update_bota_status_label(self):
        state = self.data_receiver.bota_state
        self.bota_status_label.setText("State: " + state)
        if state == "Disconnect":
            self.bota_status_label.setStyleSheet("color: Red;")
        elif state == "Connecting...":
            self.bota_status_label.setStyleSheet("color: Orange;")
        elif state == "Connected":
            self.bota_status_label.setStyleSheet("color: Green;")

    def refresh_serial_ports(self):
        """Refresh available serial ports."""
        current = self.serial_combo.currentText()
        ports = [port.device for port in serial.tools.list_ports.comports()]
        existing = [self.serial_combo.itemText(i) for i in range(self.serial_combo.count())]
        if ports == existing:
            return
        self.serial_combo.blockSignals(True)
        self.serial_combo.clear()
        for port in ports:
            self.serial_combo.addItem(port)
        if current:
            idx = self.serial_combo.findText(current)
            if idx >= 0:
                self.serial_combo.setCurrentIndex(idx)
        self.serial_combo.blockSignals(False)

    def toggle_bota_connection(self):
        if self.toggle_bota_btn.isChecked():
            selected_port = self.serial_combo.currentText()
            if selected_port:
                self.data_receiver.connect_ft(selected_port)
                self.toggle_bota_btn.setText("Disconnect Sensor")
                self.toggle_bota_btn.setStyleSheet("background-color: lightblue")
            else:
                QMessageBox.warning(self, "No Port Selected", "Please select a serial port.")
                self.toggle_bota_btn.setChecked(False)
        else:
            self.data_receiver.disconnect_ft()
            self.toggle_bota_btn.setText("Connect Sensor")
            self.toggle_bota_btn.setStyleSheet("background-color: orange")

    def export_csv(self):
        """Export the current plot to CSV."""
        # 1. 鑷姩鍋滄鏁版嵁鎺ユ敹
        if self.plot_state == PlotState.RUNNING:
            self.toggle_reception()

        # 2. 鍑嗗淇濆瓨鐩綍
        export_dir = "./csv_data"
        os.makedirs(export_dir, exist_ok=True)

        # 3. 鑾峰彇璺緞锛堣嚜鍔ㄥ懡鍚嶆垨鐢ㄦ埛鑷畾涔夛級
        user_input = self.export_filename_edit.text().strip()
        if user_input:
            path = os.path.join(export_dir, user_input)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(export_dir, f"{timestamp}_waveform.csv")

        # 4. 纭繚鎵╁睍鍚嶆纭?
        base, ext = os.path.splitext(path)
        if ext.lower() != ".csv":
            ext = ".csv"
            base = path  # 鐢ㄦ埛鍙兘娌″啓鎵╁睍鍚?
        final_path = base + ext

        # 5. 閬垮厤閲嶅悕锛岃嚜鍔ㄥ姞 _1, _2 绛?
        counter = 1
        while os.path.exists(final_path):
            final_path = f"{base}_{counter}{ext}"
            counter += 1
            # 6. 鎵ц瀵煎嚭
        try:
            exporter = CSVExporter(self.plot_widget.getPlotItem())
            exporter.export(final_path)
            QMessageBox.information(self, "Export successful", f"CSV file exported to锛歕n{final_path}")
            # 鍙€夛細鍐欏洖璺緞鍒拌緭鍏ユ
            # self.export_filename_edit.setText(final_path)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", f"\n{str(e)}")

    def update_capture_plot(self):
        if self.waveform_capture_window:
            if self.waveform_capture_window.isVisible():
                self.waveform_capture_window.update_from_main()

    def open_waveform_capture(self):
        if not self.waveform_capture_window:
            self.waveform_capture_window = WaveformCaptureWindow(self)
        self.waveform_capture_window.show()

    def update_window_duration(self, value):
        self.fixed_window_seconds = value

    def _set_auto_checkboxes_silent(self, auto_x, auto_y):
        self.auto_x.blockSignals(True)
        self.auto_y.blockSignals(True)
        self.auto_x.setChecked(bool(auto_x))
        self.auto_y.setChecked(bool(auto_y))
        self.auto_y.blockSignals(False)
        self.auto_x.blockSignals(False)

    def set_auto_scroll_enabled(self, state):
        enabled = (state == Qt.Checked)
        if self.auto_scroll_enabled == enabled:
            return
        self.auto_scroll_enabled = enabled
        self.refresh_all_curves(visible_only=True)

    def set_auto_y_enabled(self, state):
        self.auto_y_enabled = (state == Qt.Checked)
        self.plot_widget.enableAutoRange(axis=1, enable=False)
        if self.auto_y_enabled:
            self._apply_auto_y_range()

    def manual_scroll(self):
        auto_x_was_enabled = self.auto_scroll_enabled
        if self.auto_y_enabled:
            self.auto_y_enabled = False
            self.auto_y.setChecked(False)
        if self.auto_scroll_enabled:
            self.auto_scroll_enabled = False
            self.auto_x.setChecked(False)
        if auto_x_was_enabled:
            self.refresh_all_curves(visible_only=True)

    def get_default_color(self, var_name):
        """Return the default curve color for a variable."""
        color_map = {
            # === PID ===
            "Target_posx": (100, 200, 100), "Target_posy": (200, 100, 100), "Target_posz": (100, 100, 200),
            "Target_pitch": (100, 200, 100), "Target_roll": (200, 100, 100),
            "RLS_posx": (0, 150, 0), "RLS_posy": (150, 0, 0), "RLS_posz": (0, 0, 150),
            "RLS_pitch": (0, 150, 0), "RLS_roll": (150, 0, 0),
            "Pitch_offset": (0, 200, 0), "Roll_offset": (200, 0, 0),
            "Pitch_p": (0, 180, 0), "Roll_p": (180, 0, 0),
            "Left_A": (100, 100, 100), "Right_A": (150, 150, 150),

            # === Attitude_ESP ===
            "pitch": (0, 200, 0), "roll": (200, 0, 0), "yaw": (0, 0, 200),
            "pitch_6": (0, 150, 0), "roll_6": (150, 0, 0), "yaw_6": (0, 0, 150),
            "pitch_Mocap": (0, 255, 0), "roll_Mocap": (255, 0, 0), "yaw_Mocap": (0, 0, 255),
            "alt": (128, 0, 128),

            # === Servo ===
            "pwm1": (0, 120, 0), "pwm2": (0, 180, 0),
            "ang1": (255, 140, 0), "ang2": (210, 105, 30),

            # === ADC ===
            "adc": (100, 149, 237), "freq": (65, 105, 225), "vol": (30, 144, 255),

            # === IMU ===
            "q0": (100, 100, 100), "q1": (130, 130, 130), "q2": (160, 160, 160), "q3": (190, 190, 190),
            "mx": (255, 102, 178), "my": (204, 0, 102), "mz": (153, 0, 76),
            "acc.x": (0, 200, 0), "acc.y": (200, 0, 0), "acc.z": (0, 0, 200),
            "gyro.x": (0, 180, 0), "gyro.y": (180, 0, 0), "gyro.z": (0, 0, 180),
            "vx": (0, 150, 0), "vy": (150, 0, 0), "vz": (0, 0, 150),

            # === Force ===
            "F_X": (0, 200, 0), "F_Y": (200, 0, 0), "F_Z": (0, 0, 200),
            "T_X": (0, 150, 0), "T_Y": (150, 0, 0), "T_Z": (0, 0, 150),

            # === Attitude_Mocap 涓讳綋 ===
            "Mocap_pitch": (0, 200, 0), "Mocap_roll": (200, 0, 0), "Mocap_yaw": (0, 0, 200),
            "Mocap_X": (0, 200, 0), "Mocap_Y": (200, 0, 0), "Mocap_Z": (0, 0, 200),
            "Mocap_SpeedX": (0, 180, 0), "Mocap_SpeedY": (180, 0, 0), "Mocap_SpeedZ": (0, 0, 180),
            "Mocap_AccX": (0, 150, 0), "Mocap_AccY": (150, 0, 0), "Mocap_AccZ": (0, 0, 150),
            "Mocap_Speed": (100, 100, 255), "Mocap_Acc": (255, 100, 0),
            "Mocap_qx": (160, 0, 160), "Mocap_qy": (190, 0, 190), "Mocap_qz": (220, 0, 220), "Mocap_qw": (250, 0, 250),
            "Mocap_Quality": (200, 150, 0),

            # === Wing1 ===
            "Wing1_pitch": (0, 150, 0), "Wing1_roll": (150, 0, 0), "Wing1_yaw": (0, 0, 150),
            "Wing1_X": (0, 150, 0), "Wing1_Y": (150, 0, 0), "Wing1_Z": (0, 0, 150),
            "Wing1_SpeedX": (0, 130, 0), "Wing1_SpeedY": (130, 0, 0), "Wing1_SpeedZ": (0, 0, 130),
            "Wing1_AccX": (0, 110, 0), "Wing1_AccY": (110, 0, 0), "Wing1_AccZ": (0, 0, 110),
            "Wing1_Speed": (80, 80, 255), "Wing1_Acc": (255, 80, 0),
            "Wing1_qx": (120, 0, 120), "Wing1_qy": (140, 0, 140), "Wing1_qz": (160, 0, 160), "Wing1_qw": (180, 0, 180),
            "Wing1_Quality": (160, 120, 0),

            # === Wing2 ===
            "Wing2_pitch": (0, 255, 100), "Wing2_roll": (255, 100, 100), "Wing2_yaw": (100, 100, 255),
            "Wing2_X": (0, 255, 100), "Wing2_Y": (255, 100, 100), "Wing2_Z": (100, 100, 255),
            "Wing2_SpeedX": (0, 220, 100), "Wing2_SpeedY": (220, 100, 100), "Wing2_SpeedZ": (100, 100, 220),
            "Wing2_AccX": (0, 180, 100), "Wing2_AccY": (180, 100, 100), "Wing2_AccZ": (100, 100, 180),
            "Wing2_Speed": (60, 60, 255), "Wing2_Acc": (255, 60, 0),
            "Wing2_qx": (200, 0, 200), "Wing2_qy": (220, 0, 220), "Wing2_qz": (240, 0, 240), "Wing2_qw": (255, 0, 255),
            "Wing2_Quality": (220, 180, 0),

            # === Marker ===
            "Marker_Id": (128, 128, 128), "Marker_Group": (100, 100, 100),
            "Marker_X": (0, 180, 0), "Marker_Y": (180, 0, 0), "Marker_Z": (0, 0, 180),
        }

        if var_name in color_map:
            return color_map[var_name]

        seed = 0
        for idx, ch in enumerate(var_name):
            seed += (idx + 1) * ord(ch)
        return (
            80 + (seed * 3) % 140,
            80 + (seed * 5) % 140,
            80 + (seed * 7) % 140,
        )

    def toggle_reception(self):
        now = time.time() * 1000  # ms
        if self.plot_state == PlotState.IDLE:
            print(self.plot_state)
            self.data_receiver.first_ft_received_flag = False
            self.data_receiver.first_udp_received_flag = False
            self.data_model.clear()  # 闃叉娈嬬暀鏁版嵁
            self.reception_start_time = now
            unix_time = time.time_ns() / 1000
            # print(f"The latest window t0 corresponds to the unix time {unix_time} us")
            self.auto_x.setChecked(True)
            self.auto_y.setChecked(True)
            self.toggle_reception_btn.setText("Pause")
            self.toggle_reception_btn.setStyleSheet("background-color: lightblue")
            self.plot_state = PlotState.RUNNING
            return

        if self.plot_state == PlotState.RUNNING:
            print(self.plot_state)
            # self.data_receiver.stop()
            self.auto_scroll_enabled_before_pause = self.auto_scroll_enabled
            self.auto_y_enabled_before_pause = self.auto_y_enabled
            self.auto_scroll_enabled = False
            self.auto_y_enabled = False
            self._set_auto_checkboxes_silent(False, False)
            self.plot_widget.enableAutoRange(axis=1, enable=False)
            self.toggle_reception_btn.setText("Disable...")
            self.toggle_reception_btn.setStyleSheet("background-color: gray")
            self.plot_state = PlotState.STOPPING

            self.update_plot()

            self.toggle_reception_btn.setText("Resume")
            self.toggle_reception_btn.setStyleSheet("background-color: orange")
            self.plot_state = PlotState.STOPPED
            return

        if self.plot_state == PlotState.STOPPED:
            print(self.plot_state)
            self.toggle_reception_btn.setText("Pause")
            self.toggle_reception_btn.setStyleSheet("background-color: lightblue")
            self.auto_scroll_enabled = bool(self.auto_scroll_enabled_before_pause)
            self.auto_y_enabled = bool(self.auto_y_enabled_before_pause)
            self._set_auto_checkboxes_silent(self.auto_scroll_enabled, self.auto_y_enabled)
            self.plot_state = PlotState.RUNNING
            self.refresh_all_curves(visible_only=True)
            return


    def auto_scale_all(self):
        self.auto_x.setChecked(True)
        self.auto_y.setChecked(True)

    @staticmethod
    def _default_curve_transform():
        return {"phase_ms": 0.0, "scale": 1.0, "offset": 0.0}

    def _get_curve_transform(self, var_name):
        return self.curve_transforms.get(var_name, self._default_curve_transform())

    @staticmethod
    def _is_default_curve_transform(transform):
        return (
            abs(float(transform.get("phase_ms", 0.0))) < 1e-9 and
            abs(float(transform.get("scale", 1.0)) - 1.0) < 1e-12 and
            abs(float(transform.get("offset", 0.0))) < 1e-12
        )

    def _curve_source_data(self, var_name):
        return self.data_model.get_series(var_name, None)

    def _transform_curve_data(self, var_name, ts, vs):
        transform = self._get_curve_transform(var_name)
        if self._is_default_curve_transform(transform):
            return ts, vs

        phase_ms = float(transform.get("phase_ms", 0.0))
        scale = float(transform.get("scale", 1.0))
        offset = float(transform.get("offset", 0.0))

        ts_out = [float(t) + phase_ms for t in ts] if abs(phase_ms) >= 1e-9 else ts
        vs_out = [(float(v) * scale) + offset for v in vs]
        return ts_out, vs_out

    def _clip_window_range(self):
        clip_end = self.window_now
        if self.auto_scroll_enabled:
            return clip_end - self.fixed_window_seconds * 1000, clip_end
        return self.reception_start_time, clip_end

    def _clip_curve_to_time_window(self, ts, vs):
        window_start, window_end = self._clip_window_range()
        clipped_ts = []
        clipped_vs = []
        for t, v in zip(ts, vs):
            if window_start <= t <= window_end:
                clipped_ts.append(t)
                clipped_vs.append(v)
        return clipped_ts, clipped_vs

    def _curve_plot_data(self, var_name):
        ts, vs = self._curve_source_data(var_name)
        if not ts:
            return [], []

        ts, vs = self._transform_curve_data(var_name, ts, vs)
        return self._clip_curve_to_time_window(ts, vs)

    def refresh_curve(self, var_name, update_auto_y=True):
        curve = self.curves.get(var_name)
        if curve is None:
            return

        if self.plot_state == PlotState.IDLE:
            curve.setData([], [])
            self._hide_selected_hover_point()
            return

        ts_plot, vs_plot = self._curve_plot_data(var_name)
        curve.setData(ts_plot, vs_plot)
        if var_name == self.selected_var_name:
            self._update_selected_hover_point()
        if update_auto_y:
            self._apply_auto_y_range()

    def refresh_all_curves(self, visible_only=False):
        for var_name in self.signal_variables:
            curve = self.curves.get(var_name)
            if curve is None or (visible_only and not curve.isVisible()):
                continue
            self.refresh_curve(var_name, update_auto_y=False)
        self._apply_auto_y_range()

    @staticmethod
    def _color_button_style(rgb):
        return f"background-color: rgb{rgb}; border: 1px solid #606060;"

    def _update_selected_color_button(self, rgb):
        self.selected_color_btn.setStyleSheet(self._color_button_style(rgb))

    @staticmethod
    def _value_style(is_active):
        return "color: #d00000;" if is_active else ""

    def _update_transform_control_styles(self, transform, has_selection):
        if not has_selection:
            self.selected_phase_spin.setStyleSheet("")
            self.selected_offset_spin.setStyleSheet("")
            self.selected_scale_spin.setStyleSheet("")
            return

        phase = float(transform.get("phase_ms", 0.0))
        offset = float(transform.get("offset", 0.0))
        scale = float(transform.get("scale", 1.0))
        self.selected_phase_spin.setStyleSheet(self._value_style(abs(phase) >= 1e-9))
        self.selected_offset_spin.setStyleSheet(self._value_style(abs(offset) >= 1e-12))
        self.selected_scale_spin.setStyleSheet(self._value_style(abs(scale - 1.0) >= 1e-12))

    def _update_selected_controls(self):
        var_name = self.selected_var_name
        has_selection = bool(var_name and var_name in self.curves)
        transform = self._get_curve_transform(var_name) if has_selection else self._default_curve_transform()
        color = self.colors.get(var_name, (64, 64, 64)) if has_selection else (48, 48, 48)

        self._updating_selected_controls = True
        self.selected_plot_value.setText(var_name if has_selection else "-")
        self._update_selected_color_button(color)
        self.selected_color_btn.setEnabled(has_selection)
        self.selected_phase_spin.setEnabled(has_selection)
        self.selected_offset_spin.setEnabled(has_selection)
        self.selected_scale_spin.setEnabled(has_selection)
        self.selected_phase_spin.setValue(float(transform.get("phase_ms", 0.0)))
        self.selected_offset_spin.setValue(float(transform.get("offset", 0.0)))
        self.selected_scale_spin.setValue(float(transform.get("scale", 1.0)))
        self._update_transform_control_styles(transform, has_selection)
        if not has_selection:
            self.selected_coord_value.setText("")
            self.selected_coord_value.setStyleSheet("")
        self._updating_selected_controls = False

    def _store_curve_transform(self, var_name, transform, update_controls=True):
        if var_name not in self.curves:
            return

        if self._is_default_curve_transform(transform):
            self.curve_transforms.pop(var_name, None)
        else:
            self.curve_transforms[var_name] = dict(transform)

        self.refresh_curve(var_name)
        if update_controls and var_name == self.selected_var_name:
            self._update_selected_controls()

    def _selected_transform_changed(self, *_args):
        if self._updating_selected_controls:
            return

        var_name = self.selected_var_name
        if not var_name or var_name not in self.curves:
            return

        transform = {
            "phase_ms": float(self.selected_phase_spin.value()),
            "scale": float(self.selected_scale_spin.value()),
            "offset": float(self.selected_offset_spin.value()),
        }
        self._update_transform_control_styles(transform, True)
        self._store_curve_transform(var_name, transform, update_controls=False)

    def shift_curve_phase(self, var_name, delta_ms):
        transform = dict(self._get_curve_transform(var_name))
        transform["phase_ms"] = float(transform.get("phase_ms", 0.0)) + float(delta_ms)
        self._store_curve_transform(var_name, transform)

    def shift_curve_offset(self, var_name, delta):
        transform = dict(self._get_curve_transform(var_name))
        transform["offset"] = float(transform.get("offset", 0.0)) + float(delta)
        self._store_curve_transform(var_name, transform)

    def reset_curve_transform(self, var_name):
        self._store_curve_transform(var_name, self._default_curve_transform())

    def _curve_pen_width(self, var_name):
        return 4 if var_name == self.selected_var_name and self.selected_curve_focus_active else 2

    def _update_curve_pen(self, var_name):
        curve = self.curves.get(var_name)
        if curve is None:
            return
        color = self.colors.get(var_name, self.get_default_color(var_name))
        curve.setPen(pg.mkPen(color=color, width=self._curve_pen_width(var_name)))

    def _set_selected_curve_focus_active(self, active):
        if self.selected_curve_focus_active == active:
            return
        self.selected_curve_focus_active = active
        if self.selected_var_name in self.curves:
            self._update_curve_pen(self.selected_var_name)
        if not active:
            self._hide_selected_hover_point()

    def select_curve(self, var_name):
        if var_name not in self.curves:
            return

        self._plot_mouse_press_curve_selected = True
        previous = self.selected_var_name
        self.selected_var_name = var_name
        self.selected_curve_focus_active = True
        if previous and previous in self.curves and previous != var_name:
            self._update_curve_pen(previous)
            self._hide_selected_hover_point()
        self._update_curve_pen(var_name)
        self._update_selected_controls()
        self._update_selected_hover_point()
        self.plot_widget.setFocus()

    def change_selected_curve_color(self):
        var_name = self.selected_var_name
        if not var_name or var_name not in self.curves:
            return

        current = self.colors.get(var_name, self.get_default_color(var_name))
        dialog = QColorDialog(QColor(*current), self.window())
        dialog.setOption(QColorDialog.DontUseNativeDialog, True)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.resize(420, 320)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        if dialog.exec_() != QColorDialog.Accepted:
            return

        selected = dialog.selectedColor()
        if selected.isValid():
            self.set_curve_color(var_name, selected.getRgb()[:3])

    def _connect_curve_click(self, curve, var_name):
        if hasattr(curve, "setCurveClickable"):
            curve.setCurveClickable(True, width=24)
        if hasattr(curve, "sigClicked"):
            curve.sigClicked.connect(lambda *_args, name=var_name: self.select_curve(name))

    def _handle_curve_key_event(self, event):
        var_name = self.selected_var_name
        if not var_name or var_name not in self.curves or not self.selected_curve_focus_active:
            return False

        key = event.key()
        if key == Qt.Key_Left:
            self.shift_curve_phase(var_name, -10.0)
            return True
        if key == Qt.Key_Right:
            self.shift_curve_phase(var_name, 10.0)
            return True
        if key == Qt.Key_Up:
            self.shift_curve_offset(var_name, 1.0)
            return True
        if key == Qt.Key_Down:
            self.shift_curve_offset(var_name, -1.0)
            return True
        return False

    def _hide_selected_hover_point(self):
        self.selected_hover_point = None
        if hasattr(self, "selected_hover_marker"):
            self.selected_hover_marker.setVisible(False)
        if hasattr(self, "selected_hover_vline"):
            self.selected_hover_vline.setVisible(False)
        if hasattr(self, "selected_hover_hline"):
            self.selected_hover_hline.setVisible(False)
        self.selected_coord_value.setText("")
        self.selected_coord_value.setStyleSheet("")

    def _nearest_selected_point(self, x_value):
        var_name = self.selected_var_name
        curve = self.curves.get(var_name)
        if curve is None or curve.xData is None or curve.yData is None:
            return None

        xs = list(curve.xData)
        ys = list(curve.yData)
        count = min(len(xs), len(ys))
        if count == 0:
            return None

        idx = bisect_left(xs, x_value)
        candidates = []
        if 0 <= idx < count:
            candidates.append(idx)
        if 0 <= idx - 1 < count:
            candidates.append(idx - 1)
        if not candidates:
            return None

        best_idx = min(candidates, key=lambda i: abs(float(xs[i]) - float(x_value)))
        return float(xs[best_idx]), float(ys[best_idx])

    def _point_scene_distance_px(self, x_value, y_value, mouse_scene_pos):
        point_scene = self.view_box.mapViewToScene(QPointF(float(x_value), float(y_value)))
        dx = float(point_scene.x()) - float(mouse_scene_pos.x())
        dy = float(point_scene.y()) - float(mouse_scene_pos.y())
        return math.hypot(dx, dy)

    def _update_selected_coord_label(self, x_value, y_value):
        t_s = (float(x_value) - self.reception_start_time) / 1000.0
        self.selected_coord_value.setText(f"({t_s:.3f} s, {float(y_value):.3f})")
        self.selected_coord_value.setStyleSheet("color: #d00000;")

    def _show_selected_hover_point(self, x_value, y_value):
        self.selected_hover_point = (x_value, y_value)
        self.selected_hover_marker.setData([x_value], [y_value])
        self.selected_hover_marker.setVisible(True)
        self.selected_hover_vline.setValue(x_value)
        self.selected_hover_hline.setValue(y_value)
        self.selected_hover_vline.setVisible(True)
        self.selected_hover_hline.setVisible(True)
        self._update_selected_coord_label(x_value, y_value)

    def _update_selected_hover_point(self, mouse_x=None, mouse_scene_pos=None):
        if not self.selected_curve_focus_active or not self.selected_var_name:
            self._hide_selected_hover_point()
            return

        if mouse_x is None and self.selected_hover_point is not None:
            mouse_x = self.selected_hover_point[0]
        if mouse_x is None:
            return

        point = self._nearest_selected_point(float(mouse_x))
        if point is None:
            self._hide_selected_hover_point()
            return

        x_value, y_value = point
        if mouse_scene_pos is not None:
            distance_px = self._point_scene_distance_px(x_value, y_value, mouse_scene_pos)
            if distance_px > self.hover_hit_px:
                self._hide_selected_hover_point()
                return

        self._show_selected_hover_point(x_value, y_value)

    def _handle_plot_mouse_press(self, event):
        if event.button() != Qt.LeftButton:
            return False
        self._plot_mouse_press_curve_selected = False
        QTimer.singleShot(0, self._deactivate_selected_curve_after_blank_click)
        return False

    def _deactivate_selected_curve_after_blank_click(self):
        if not self._plot_mouse_press_curve_selected:
            self._set_selected_curve_focus_active(False)

    def _handle_plot_mouse_move(self, event):
        if not self.selected_curve_focus_active or not self.selected_var_name:
            return False
        try:
            scene_pos = self.plot_widget.mapToScene(event.pos())
            view_pos = self.view_box.mapSceneToView(scene_pos)
        except Exception:
            return False
        self._update_selected_hover_point(mouse_x=float(view_pos.x()), mouse_scene_pos=scene_pos)
        return False

    def _visible_curve_y_bounds(self):
        y_min = None
        y_max = None
        for curve in self.curves.values():
            if curve is None or not curve.isVisible() or curve.yData is None:
                continue
            for value in curve.yData:
                try:
                    y = float(value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(y):
                    continue
                y_min = y if y_min is None else min(y_min, y)
                y_max = y if y_max is None else max(y_max, y)
        if y_min is None or y_max is None:
            return None
        return y_min, y_max

    def _apply_auto_y_range(self):
        if not self.auto_y_enabled:
            return
        bounds = self._visible_curve_y_bounds()
        if bounds is None:
            return
        y_min, y_max = bounds
        if abs(y_max - y_min) < 1e-12:
            pad = max(abs(y_min) * 0.1, 1.0)
        else:
            pad = abs(y_max - y_min) * 0.05
        self.plot_widget.setYRange(y_min - pad, y_max + pad, padding=0)

    def eventFilter(self, obj, event):
        if obj in (self.plot_widget, self.plot_widget.viewport()):
            if event.type() == QEvent.FocusIn:
                if self.selected_var_name:
                    self._set_selected_curve_focus_active(True)
            elif event.type() == QEvent.FocusOut:
                self._set_selected_curve_focus_active(False)
            elif event.type() == QEvent.Leave:
                self._hide_selected_hover_point()
            elif event.type() == QEvent.MouseButtonPress:
                self._handle_plot_mouse_press(event)
            elif event.type() == QEvent.MouseMove:
                self._handle_plot_mouse_move(event)
            elif event.type() == QEvent.KeyPress:
                if self._handle_curve_key_event(event):
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        focus_widget = self.focusWidget()
        input_widgets = (QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox)
        if not isinstance(focus_widget, input_widgets) and self._handle_curve_key_event(event):
            return
        super().keyPressEvent(event)

    def update_plot(self):
        if self.plot_state == PlotState.IDLE or self.plot_state == PlotState.STOPPED:
            return

        if self.plot_state == PlotState.CLEARING:
            for var in self.signal_variables:
                self.curves[var].setData([], [])
            return

        # Pause freezes the time window; DataModel can still receive data.
        if self.plot_state == PlotState.STOPPING:
            for var in self.signal_variables:
                ts, vs = self._curve_plot_data(var)
                self.curves[var].setData(ts, vs)
            self._apply_auto_y_range()
            return

        if self.plot_state == PlotState.RUNNING:
            for var in self.signal_variables:
                if not self.curves[var].isVisible():
                    continue  # 璺宠繃闅愯棌鏇茬嚎

                ts_plot, vs_plot = self._curve_plot_data(var)
                if not ts_plot:
                    if self.curves[var].xData is not None and len(self.curves[var].xData) > 0:
                        self.curves[var].setData([], [])  # 鏈夋暟鎹?-> 鏃犳暟鎹墠闇€瑕佹竻闄?
                    if var == self.selected_var_name:
                        self._hide_selected_hover_point()
                    continue

                # 浠呭湪鏁版嵁鍙樺寲鏃舵洿鏂?
                if (
                        self.curves[var].xData is None or
                        len(self.curves[var].xData) != len(ts_plot) or
                        (ts_plot and self.curves[var].xData[-1] != ts_plot[-1]) or
                        self.curves[var].yData is None or
                        (vs_plot and self.curves[var].yData[-1] != vs_plot[-1])
                ):
                    self.curves[var].setData(ts_plot, vs_plot)
                    if var == self.selected_var_name:
                        self._update_selected_hover_point()

            self._apply_auto_y_range()

    # plot window鏃堕棿鎴虫洿鏂?
    def update_cursor(self):
        now = time.time() * 1000  # ms
        self.begin_line.setValue(self.reception_start_time)
        self.x_axis.set_start_time(self.reception_start_time)

        if self.plot_state == PlotState.RUNNING:
            self.window_now = now
            self.window_start = self.window_now - self.fixed_window_seconds * 1000
            self.now_line.setValue(self.window_now)  # 鑷姩璺熼殢鏃堕棿鍓嶈繘

        elif self.plot_state == PlotState.CLEARING:
            self.window_now = self.reception_start_time
            self.window_start = self.window_now - self.fixed_window_seconds * 1000
            self.now_line.setValue(self.window_now)

        highlight_tick = [(self.window_now, f"T_now = {int(self.window_now - self.reception_start_time)} ms"),
                          (self.window_now - 1000, f"{int(self.window_now - self.reception_start_time - 1000)} ms")]
        if self.auto_scroll_enabled:
            self.plot_widget.setXRange(self.window_start, self.window_now + self.fixed_window_seconds * 1000 / 10,
                                       padding=0)
            self.x_axis.setTicks([highlight_tick])
        else:
            self.x_axis.setTicks(None)

    def clear_data(self):
        """Clear all buffered data."""
        now = time.time() * 1000  # ms
        # CLEANING:
        self.plot_state = PlotState.CLEARING
        self.data_model.clear()
        self.update_cursor()
        self.update_plot()

        # IDLE:
        self.plot_state = PlotState.IDLE
        self.data_model.clear()
        self.toggle_reception_btn.setText("Start Receive")
        self.toggle_reception_btn.setStyleSheet("background-color: orange")

    def _connect_variable_control(self, ctrl):
        ctrl.selected.connect(self.select_curve)
        ctrl.visibility_changed.connect(self.set_curve_visibility)
        ctrl.color_changed.connect(self.set_curve_color)
        ctrl.transform_reset_requested.connect(self.reset_curve_transform)

    def _register_variable(self, var_name, checked, grid, columns, count_attr, create_control=True):
        if not var_name or var_name in self.curves:
            return False

        color = self.get_default_color(var_name)
        curve = self.plot_widget.plot(pen=pg.mkPen(color=color, width=2), name=var_name)
        curve.setVisible(bool(checked))
        self._connect_curve_click(curve, var_name)
        self.curves[var_name] = curve
        self.colors[var_name] = color
        self.default_colors[var_name] = color

        if create_control:
            ctrl = VariableControlItem(var_name, color, color, checked=bool(checked))
            self._connect_variable_control(ctrl)
            self.var_controls[var_name] = ctrl

            if grid is not None:
                idx = int(getattr(self, count_attr))
                row = idx // max(1, int(columns))
                col = idx % max(1, int(columns))
                grid.addWidget(ctrl, row, col)
                setattr(self, count_attr, idx + 1)

        self.signal_variables.append(var_name)
        return True

    def _register_static_variable(self, var_name, checked, grid, columns, count_attr, show_control=True):
        self._register_variable(
            var_name=var_name,
            checked=checked,
            grid=grid,
            columns=columns,
            count_attr=count_attr,
            create_control=show_control,
        )

    def _get_or_create_signal_export_section(self, section_name):
        section = (section_name or "Other").strip() or "Other"
        info = self.signal_export_sections.get(section)
        if info is not None:
            return info

        box = QGroupBox(section)
        grid = QGridLayout()
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        box.setLayout(grid)
        info = {"box": box, "grid": grid, "items": []}
        self.signal_export_sections[section] = info
        self.signal_export_section_order.append(section)
        self._relayout_signal_export_sections()
        return info

    @staticmethod
    def _detach_layout_items(layout):
        if layout is None:
            return
        while layout.count():
            layout.takeAt(0)

    def _relayout_signal_export_sections(self):
        if self.signal_export_grid is None:
            return
        self._detach_layout_items(self.signal_export_grid)
        for idx, section in enumerate(self.signal_export_section_order):
            info = self.signal_export_sections.get(section)
            if not info:
                continue
            self.signal_export_grid.addWidget(info["box"], 0, idx, alignment=Qt.AlignTop | Qt.AlignLeft)
        if self.signal_export_container is not None:
            self.signal_export_container.adjustSize()

    def _relayout_signal_export_section_items(self, section_name):
        info = self.signal_export_sections.get(section_name)
        if not info:
            return
        grid = info["grid"]
        self._detach_layout_items(grid)
        for idx, var_name in enumerate(info.get("items", [])):
            ctrl = self.var_controls.get(var_name)
            if ctrl is None:
                continue
            grid.addWidget(ctrl, idx, 0, alignment=Qt.AlignLeft)
        if self.signal_export_container is not None:
            self.signal_export_container.adjustSize()

    def register_signal_export_descriptors(self, descriptors):
        added = []
        changed_sections = set()
        for desc in descriptors:
            var_name = (desc.get("var_name") or desc.get("name") or "").strip()
            if not var_name:
                continue
            section = (desc.get("section") or "Other").strip() or "Other"
            checked = False
            if var_name not in self.curves:
                if self._register_variable(
                    var_name=var_name,
                    checked=checked,
                    grid=None,
                    columns=1,
                    count_attr="signal_export_count",
                ):
                    added.append(var_name)
            elif var_name not in self.var_controls:
                color = self.colors.get(var_name, self.get_default_color(var_name))
                ctrl = VariableControlItem(var_name, color, color, checked=self.curves[var_name].isVisible())
                self._connect_variable_control(ctrl)
                self.var_controls[var_name] = ctrl

            if var_name not in self.dynamic_signal_variables:
                self.dynamic_signal_variables.append(var_name)

            last_section = self.dynamic_signal_sections.get(var_name)
            if last_section == section:
                continue
            if last_section:
                last_info = self.signal_export_sections.get(last_section)
                if last_info and var_name in last_info.get("items", []):
                    last_info["items"].remove(var_name)
                    changed_sections.add(last_section)
            self.dynamic_signal_sections[var_name] = section
            ctrl = self.var_controls.get(var_name)
            if ctrl is None:
                continue
            section_info = self._get_or_create_signal_export_section(section)
            if var_name not in section_info["items"]:
                section_info["items"].append(var_name)
            changed_sections.add(section)

        for section in changed_sections:
            self._relayout_signal_export_section_items(section)
        if changed_sections:
            self._relayout_signal_export_sections()

        return added

    def register_signal_export_variables(self, names):
        descriptors = [{"var_name": name, "section": "Other"} for name in names]
        return self.register_signal_export_descriptors(descriptors)

    def set_curve_visibility(self, var_name, visible):
        if var_name in self.curves:
            self.curves[var_name].setVisible(visible)
            if visible:
                self.refresh_curve(var_name)
            else:
                if var_name == self.selected_var_name:
                    self._hide_selected_hover_point()
                self._apply_auto_y_range()

    def set_curve_color(self, var_name, rgb):
        """Set the curve color for a variable."""
        if var_name in self.curves:
            self.colors[var_name] = rgb
            self._update_curve_pen(var_name)

            ctrl = self.var_controls.get(var_name)
            if ctrl is not None:
                ctrl.set_color(rgb)

            if var_name == self.selected_var_name:
                self._update_selected_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_signal_export_sections()
        for section in self.signal_export_section_order:
            self._relayout_signal_export_section_items(section)

    def closeEvent(self, event):
        try:
            self.data_receiver.disconnect_nfv1()
            self.data_receiver.stop()
        except Exception:
            pass
        event.accept()
