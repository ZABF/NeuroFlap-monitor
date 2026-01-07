from PyQt5.QtGui import QPen
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLabel, QSpinBox, QGridLayout, QMessageBox, QLineEdit, QComboBox, QFrame
)
from PyQt5.QtCore import QTimer, Qt
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

STOPPING -> (redraw all points) -> STOPPED                                           
CLEARING -> (clear all points) -> IDLE
'''


class PlotState(Enum):
    IDLE = 0  # 初始未接收
    RUNNING = 1  # 正在接收
    STOPPING = 2  # 正在暂停
    STOPPED = 3  # 接收暂停
    CLEARING = 4  # 正在清除数据


class PlotWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monitor v2.2.0")

        # 所有固定变量列表
        self.variable_groups = {
            "PID": [
                ("Target_posx", True), ("Target_posy", True), ("Target_posz", True),
                ("Target_pitch", True), ("Target_roll", True),
                ("RLS_posx", True), ("RLS_posy", True), ("RLS_posz", True),
                ("RLS_pitch", True), ("RLS_roll", True),
                ("Pitch_offset", True), ("Roll_offset", True),
                ("Pitch_p", True), ("Roll_p", True), ("Left_A", True), ("Right_A", True),
            ],
            "Attitude_ESP": [
                ("pitch", True), ("roll", True), ("yaw", True),
                ("pitch_6", True), ("roll_6", True), ("yaw_6", True),
                ("pitch_Mocap", True), ("roll_Mocap", True), ("yaw_Mocap", True),
                ("alt", True),
            ],
            "Servo": [
                ("pwm1", True), ("pwm2", True), ("ang1", True), ("ang2", True),
            ],
            "ADC": [
                ("adc", True), ("vol", True), ("freq", True),
            ],
            "IMU": [
                ("q0", False), ("q1", False), ("q2", False), ("q3", False),
                ("mx", True), ("my", True), ("mz", True),
                ("acc.x", True), ("acc.y", True), ("acc.z", True),
                ("gyro.x", True), ("gyro.y", True), ("gyro.z", True),
                ("vx", True), ("vy", True), ("vz", True),
            ],
            "Force": [
                ("F_X", True), ("F_Y", True), ("F_Z", True),
                ("T_X", True), ("T_Y", True), ("T_Z", True),
            ],
            "Attitude_Mocap": [
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
            ],
        }
        # 全部变量（决定数据模型/导出顺序）
        self.fixed_variables = [name for group in self.variable_groups.values() for (name, _) in group]

        # 模板层面的“可见/不可见”定义（决定是否出现在 GUI，有没有复选框）
        self.visible_template = {name for group in self.variable_groups.values() for (name, vis) in group if vis}
        self.hidden_variables = set(self.fixed_variables) - self.visible_template

        # 初始显示的变量
        self.default_visible_vars = ["roll", "pitch", "yaw", "pwm1", "pwm2", "F_X", "F_Y", "F_Z"]

        # 绘图窗口
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.view_box = self.plot_widget.getViewBox()
        self.view_box.sigRangeChangedManually.connect(self.manual_scroll)
        self.curves = {}  # 变量名 -> 曲线
        self.colors = {}  # 当前颜色
        self.default_colors = {}  # 默认颜色
        self.fully_plotted = False
        self.auto_scroll_enabled = True
        self.auto_y_enabled = True

        # 时间轴变量
        self.reception_start_time = time.time() * 1000  # ms
        self.window_start = time.time() * 1000  # ms 初始为程序启动时
        self.window_now = time.time() * 1000
        # 数据模型与收发器
        self.sdk_ip = "172.16.23.64"
        self.esp32_ip = "172.16.23.13"
        self.esp32_port = 28090
        self.rigid_id = "Rigid_Body"
        self.rigid_wing1_id = "Rigid_Wing_L"
        self.rigid_wing2_id = "Rigid_Wing_R"
        self.data_model = DataModel(self.fixed_variables)
        # self.data_transporter = None
        self.data_transporter = DataTransporter(self.esp32_ip, self.esp32_port)
        self.data_receiver = DataReceiver(self.data_model, self)
        # 子窗口
        self.waveform_capture_window = None

        # 初始化所有变量的曲线
        for var in self.fixed_variables:
            color = self.get_default_color(var)
            curve = self.plot_widget.plot(pen=pg.mkPen(color=color, width=2), name=var)

            if var in self.hidden_variables:
                # 模板隐藏：GUI 不出现、运行期不绘，但会存数据；暂停/导出时绘全量
                curve.setVisible(False)
            else:
                # 模板可见：是否初始显示由 default_visible_vars 决定
                curve.setVisible(var in self.default_visible_vars)

            self.curves[var] = curve
            self.colors[var] = color
            self.default_colors[var] = color

        # csv filename edit
        self.export_filename_edit = QLineEdit(self)
        self.export_filename_edit.setFixedWidth(130)  # 单位是像素
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

        # ===== 下部接收控制区 =====

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

        # ===== 变量勾选区域 =====
        self.var_controls = {}

        # 整体水平布局（左边 + 中线 + 右边）
        variable_layout = QHBoxLayout()

        # === 左边 ESP32变量===

        # === 右边 其它变量===

        # 串口选择与连接力传感器按钮
        port_label = QLabel("Bota Port:")

        self.serial_combo = QComboBox()
        self.serial_combo.setFixedWidth(130)
        self.refresh_serial_ports()

        self.toggle_bota_btn = QPushButton("Connect Sensor")
        self.toggle_bota_btn.setStyleSheet("background-color: orange")
        self.toggle_bota_btn.setCheckable(True)
        self.toggle_bota_btn.clicked.connect(self.toggle_bota_connection)

        # Bias 设置按钮
        self.bias_button = QPushButton("Bias")
        self.bias_button.setStyleSheet("background-color: lightblue")
        self.bias_button.clicked.connect(self.data_receiver.set_ft_bias)
        # self.bias_button.clicked.connect(self.data_receiver.set_ft_bias)  # 假设你在 data_receiver 中定义了 set_ft_bias 方法

        # 力传感器状态显示
        self.bota_status_label = QLabel("state:" + self.data_receiver.bota_state)
        self.bota_status_label.setFixedHeight(24)
        self.bota_status_label.setAlignment(Qt.AlignCenter)

        # 右边上变量：Force
        PID_grid = QGridLayout()
        mcu_grid = QGridLayout()
        force_grid = QGridLayout()
        mocap_grid = QGridLayout()

        hline_2 = QFrame()
        hline_2.setFrameShape(QFrame.HLine)
        hline_2.setFrameShadow(QFrame.Sunken)
        hline_2.setLineWidth(1)

        hline_3 = QFrame()
        hline_3.setFrameShape(QFrame.HLine)
        hline_3.setFrameShadow(QFrame.Sunken)
        hline_3.setLineWidth(1)
        # 接收mocap行
        mocap_rx_layout = QHBoxLayout()
        mocap_rx_layout.addWidget(QLabel("MoCap SDK IP:"))

        # 添加 IP 输入框，设置默认值
        self.mocap_ip_input = QLineEdit()
        self.mocap_ip_input.setText(self.sdk_ip)
        self.mocap_ip_input.setFixedWidth(130)  # 可选：限制宽度
        mocap_rx_layout.addWidget(self.mocap_ip_input)

        mocap_rx_layout.addWidget(QLabel("Rigid:"))
        self.mocap_rigid_input = QLineEdit()
        self.mocap_rigid_input.setText(self.rigid_id)
        self.mocap_rigid_input.setFixedWidth(130)  # 可选：限制宽度
        mocap_rx_layout.addWidget(self.mocap_rigid_input)

        mocap_rx_layout.addWidget(QLabel("Wing1:"))
        self.mocap_rigid_wing1_input = QLineEdit()
        self.mocap_rigid_wing1_input.setText(self.rigid_wing1_id)
        self.mocap_rigid_wing1_input.setFixedWidth(130)  # 可选：限制宽度
        mocap_rx_layout.addWidget(self.mocap_rigid_wing1_input)

        mocap_rx_layout.addWidget(QLabel("Wing2:"))
        self.mocap_rigid_wing2_input = QLineEdit()
        self.mocap_rigid_wing2_input.setText(self.rigid_wing2_id)
        self.mocap_rigid_wing2_input.setFixedWidth(130)  # 可选：限制宽度
        mocap_rx_layout.addWidget(self.mocap_rigid_wing2_input)

        mocap_rx_layout.addStretch()

        self.R_MoCap_button = QPushButton("Receive from MoCap")
        self.R_MoCap_button.setStyleSheet("background-color: orange")
        self.R_MoCap_button.setCheckable(True)
        self.R_MoCap_button.clicked.connect(self.toggle_mocap)
        mocap_rx_layout.addWidget(self.R_MoCap_button)

        # 回传esp行
        mocap_tx_layout = QHBoxLayout()
        mocap_tx_layout.addWidget(QLabel("ESP32 UDP IP:"))

        # 添加 IP 输入框，设置默认值
        self.esp32_rx_ip_input = QLineEdit()
        self.esp32_rx_ip_input.setText("172.16.23.13")
        self.esp32_rx_ip_input.setFixedWidth(130)  # 可选：限制宽度

        mocap_tx_layout.addWidget(self.esp32_rx_ip_input)

        mocap_tx_layout.addWidget(QLabel("PORT:"))

        self.esp32_rx_port_input = QLineEdit()
        self.esp32_rx_port_input.setText("28090")
        self.esp32_rx_port_input.setFixedWidth(100)  # 可选：限制宽度
        mocap_tx_layout.addWidget(self.esp32_rx_port_input)

        mocap_tx_layout.addStretch()

        self.T_Esp32_button = QPushButton("Transport to ESP32")
        self.T_Esp32_button.setStyleSheet("background-color: orange")
        self.T_Esp32_button.setCheckable(True)
        self.T_Esp32_button.clicked.connect(self.toggle_transport)
        mocap_tx_layout.addWidget(self.T_Esp32_button)

        # 右边下变量 MoCap
        # 填充各分组
        group_layout_map = {
            "PID": PID_grid,
            "Attitude_ESP": mcu_grid,
            "Servo": mcu_grid,
            "ADC": mcu_grid,
            "IMU": mcu_grid,
            "Force": force_grid,
            "Attitude_Mocap": mocap_grid,
        }

        # 每个小区域内部计数排布
        layout_counters = {layout: 0 for layout in [PID_grid, mcu_grid, force_grid, mocap_grid]}
        layout_column_count_map = {
            PID_grid: 5,
            mcu_grid: 6,  # 左侧：6列
            force_grid: 6,  # 右上（力传感器）：6列
            mocap_grid: 7  # 右下（Mocap）：7列
        }

        for group, var_list in self.variable_groups.items():
            layout = group_layout_map[group]
            column_count = layout_column_count_map.get(layout, 6)
            for (var, vis) in var_list:
                if not vis:
                    continue  # 模板隐藏：不给控件

                color = self.get_default_color(var)
                ctrl = VariableControlItem(var, color, color, checked=(var in self.default_visible_vars))
                ctrl.visibility_changed.connect(self.set_curve_visibility)
                ctrl.color_changed.connect(self.set_curve_color)
                self.var_controls[var] = ctrl

                idx = layout_counters[layout]
                row = idx // column_count
                col = idx % column_count
                layout.addWidget(ctrl, row, col)
                layout_counters[layout] += 1

        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        vline.setLineWidth(1)
        vline.setMidLineWidth(0)

        port_layout = QHBoxLayout()
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.serial_combo)
        port_layout.addWidget(self.toggle_bota_btn)
        port_layout.addWidget(self.bota_status_label)
        port_layout.addStretch()
        port_layout.addWidget(self.bias_button)

        # 三级布局
        left_vlayout = QVBoxLayout()

        left_vlayout.addWidget(QLabel("PID:"))
        left_vlayout.addLayout(PID_grid)

        left_vlayout.addWidget(hline_3)
        left_vlayout.addStretch()
        left_vlayout.addWidget(QLabel("MCU:"))
        left_vlayout.addLayout(mcu_grid)
        left_vlayout.addStretch()

        right_vlayout = QVBoxLayout()
        right_vlayout.addLayout(port_layout)
        # right_vlayout.addWidget(self.bota_status_label)
        right_vlayout.addLayout(force_grid)
        right_vlayout.addWidget(hline_2)  # ← 插入水平分隔线
        right_vlayout.addLayout(mocap_rx_layout)
        right_vlayout.addLayout(mocap_tx_layout)
        right_vlayout.addLayout(mocap_grid)

        # 二级布局
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

        hline_1 = QFrame()
        hline_1.setFrameShape(QFrame.HLine)
        hline_1.setFrameShadow(QFrame.Sunken)
        hline_1.setLineWidth(1)

        variable_layout.addLayout(left_vlayout, 1)
        variable_layout.addWidget(vline)
        variable_layout.addLayout(right_vlayout, 1)

        # 一级布局
        main_layout = QVBoxLayout()
        main_layout.addLayout(setting_layout)
        main_layout.addWidget(self.plot_widget, 1)
        main_layout.addLayout(control_layout)
        main_layout.addWidget(hline_1)  # ← 插入水平分隔线
        main_layout.addLayout(variable_layout)
        self.setLayout(main_layout)

        # 画布内画光标显示数字等
        self.now_line = pg.InfiniteLine(angle=90, movable=False,
                                        pen=pg.mkPen('y', width=2, style=Qt.CustomDashLine, dash=[5, 5, 1, 5]))
        self.begin_line = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen('y', width=2, style=Qt.CustomDashLine, dash=[5, 5, 1, 5]))
        self.plot_widget.addItem(self.now_line)
        self.plot_widget.addItem(self.begin_line)

        # self.plot_widget.showAxis('top', show=True)
        # self.x_axis = self.plot_widget.getAxis('top')
        self.x_axis = RelativeTimeAxis(orientation='top')
        self.plot_widget.getPlotItem().setAxisItems({'top': self.x_axis})
        self.x_axis.setStyle(showValues=True)
        self.x_axis.setTextPen(QPen(Qt.yellow))

        # 定时器用于刷新曲线
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(20)

        # 定时器用于刷新光标
        self.axis_timer = QTimer()
        self.axis_timer.timeout.connect(self.update_cursor)
        self.axis_timer.start(5)

        # 定时器用于定时处理数据
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.data_receiver.process_data)
        self.data_timer.start(20)

        # 定时器用于定时在capture window画图
        self.capture_timer = QTimer()
        self.capture_timer.timeout.connect(self.update_capture_plot)
        self.capture_timer.start(50)

        # 通用功能定时器
        self.misc_timer = QTimer()
        self.misc_timer.timeout.connect(self.update_misc_tasks)
        self.misc_timer.start(200)  # 200ms 或根据你实际需求调整

        self.plot_state = PlotState.IDLE
        self.last_plot_state = PlotState.IDLE

    def toggle_mocap(self):
        # HACK: multi rigid
        self.data_receiver.sdk_ip = self.mocap_ip_input.text().strip()  # 获取用户输入 IP
        self.data_receiver.rigid_id = self.mocap_rigid_input.text().strip()  # 获取用户输入 Rigid
        self.data_receiver.wing1_id = self.mocap_rigid_wing1_input.text().strip()  # 获取用户输入 Rigid
        self.data_receiver.wing2_id = self.mocap_rigid_wing2_input.text().strip()  # 获取用户输入 Rigid
        if self.R_MoCap_button.isChecked():
            # Start
            self.R_MoCap_button.setText("Receiving...")
            self.R_MoCap_button.setStyleSheet("background-color: lightgreen")
            # 发起连接并在连接成功后启动接收线程
            self.data_receiver.connect_mocap()
        else:
            # Stop
            self.R_MoCap_button.setText("Receive from MoCap")
            self.R_MoCap_button.setStyleSheet("background-color: orange")
            self.data_receiver.disconnect_mocap()

    def toggle_transport(self):
        # try:
        #     ip = self.esp32_rx_ip_input.text().strip()  # 获取用户输入 IP
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
        #     # 如果已存在旧线程且已停止，创建新线程实例
        #     if self.data_transporter is None or not self.data_transporter.is_alive():
        #         self.data_transporter = DataTransporterThread(ip, port)
        #         self.data_transporter.start()
        #         print("Transport thread built ")
        #     # 开启发送开关（由 DataReceiver 使用）
        #     self.data_receiver.transport_enabled = True
        #     print("Transport enable ")
        # else:
        #     # Stop Transport
        #     self.T_Esp32_button.setText("Transport to ESP32")
        #     self.T_Esp32_button.setStyleSheet("background-color: orange")
        #     # 关闭发送开关，必要时也停线程
        #     self.data_receiver.transport_enabled = False
        #     print("Transport disenable ")
        #
        #     if self.data_transporter:
        #         self.data_transporter.stop()
        #         self.data_transporter.join(timeout=1.0)
        #         self.data_transporter = None  # 必须重置以允许下次重新创建
        try:
            self.data_transporter.ip = self.esp32_rx_ip_input.text().strip()  # 获取用户输入 IP
            self.data_transporter.port = int(self.esp32_rx_port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Port must be an integer")
            return

        if self.T_Esp32_button.isChecked():
            # Start Transport
            self.T_Esp32_button.setText("Transporting...")
            self.T_Esp32_button.setStyleSheet("background-color: lightgreen")

            # 开启发送开关（由 DataReceiver 使用）
            self.data_receiver.transport_enabled = True
            print("Transport enable ")
        else:
            # Stop Transport
            self.T_Esp32_button.setText("Transport to ESP32")
            self.T_Esp32_button.setStyleSheet("background-color: orange")
            # 关闭发送开关，必要时也停线程
            self.data_receiver.transport_enabled = False
            print("Transport disenable ")

    def update_misc_tasks(self):
        self.update_bota_status_label()
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
        """扫描可用串口"""
        self.serial_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.serial_combo.addItem(port.device)

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
        """导出当前 PlotWidget 的曲线为 CSV"""
        # 1. 自动停止数据接收
        if self.plot_state == PlotState.RUNNING:
            self.toggle_reception()

        # 2. 准备保存目录
        export_dir = "./csv_data"
        os.makedirs(export_dir, exist_ok=True)

        # 3. 获取路径（自动命名或用户自定义）
        user_input = self.export_filename_edit.text().strip()
        if user_input:
            path = os.path.join(export_dir, user_input)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(export_dir, f"{timestamp}_waveform.csv")

        # 4. 确保扩展名正确
        base, ext = os.path.splitext(path)
        if ext.lower() != ".csv":
            ext = ".csv"
            base = path  # 用户可能没写扩展名
        final_path = base + ext

        # 5. 避免重名，自动加 _1, _2 等
        counter = 1
        while os.path.exists(final_path):
            final_path = f"{base}_{counter}{ext}"
            counter += 1
            # 6. 执行导出
        try:
            exporter = CSVExporter(self.plot_widget.getPlotItem())
            exporter.export(final_path)
            QMessageBox.information(self, "Export successful", f"CSV file exported to：\n{final_path}")
            # 可选：写回路径到输入框
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

    def set_auto_scroll_enabled(self, state):
        self.auto_scroll_enabled = (state == 2)

    def set_auto_y_enabled(self, state):
        self.auto_y_enabled = (state == 2)
        self.plot_widget.enableAutoRange(axis=1, enable=self.auto_y_enabled)

    def manual_scroll(self):
        if self.auto_y_enabled:
            self.auto_y_enabled = False
            self.auto_y.setChecked(False)
        if self.auto_scroll_enabled:
            self.auto_scroll_enabled = False
            self.auto_x.setChecked(False)

    def get_default_color(self, var_name):
        """根据变量名获取默认颜色"""
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

            # === Attitude_Mocap 主体 ===
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

        return color_map.get(var_name, (200, 200, 200))  # 默认灰色

    def toggle_reception(self):
        now = time.time() * 1000  # ms
        if self.plot_state == PlotState.IDLE:
            print(self.plot_state)
            self.data_receiver.first_ft_received_flag = False
            self.data_receiver.first_udp_received_flag = False
            self.data_model.clear()  # 防止残留数据
            self.data_receiver.start()
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
            # self.data_receiver.start()
            self.toggle_reception_btn.setText("Pause")
            self.toggle_reception_btn.setStyleSheet("background-color: lightblue")
            self.plot_state = PlotState.RUNNING
            return


    def auto_scale_all(self):
        self.auto_x.setChecked(True)
        self.auto_y.setChecked(True)

    def update_plot(self):
        if self.plot_state == PlotState.IDLE or self.plot_state == PlotState.STOPPED:
            return

        if self.plot_state == PlotState.CLEARING:
            for var in self.fixed_variables:
                self.curves[var].setData([], [])
            return

        # 暂停时立刻绘制所有数据（便于csv收集所有数据）
        if self.plot_state == PlotState.STOPPING:
            for var in self.fixed_variables:
                ts, vs = self.data_model.get_series(var, None)
                self.curves[var].setData(ts, vs)
            return

        # 高性能防卡顿
        if self.plot_state == PlotState.RUNNING:
            window_start = self.window_start
            window_end = self.window_now

            for var in self.fixed_variables:
                if not self.curves[var].isVisible():
                    continue  # 跳过隐藏曲线

                if self.auto_scroll_enabled:
                    ts, vs = self.data_model.get_series_fast(var, self.fixed_window_seconds * 1000)
                    if not ts:
                        continue  # 无数据则跳过
                    # 只保留窗口内数据
                    idx_range = [i for i, t in enumerate(ts) if window_start <= t <= window_end]
                    if not idx_range:
                        if self.curves[var].xData is not None and len(self.curves[var].xData) > 0:
                            self.curves[var].setData([], [])  # 有数据 -> 无数据才需要清除
                        continue

                    # 切片数据
                    i_min = idx_range[0]
                    i_max = idx_range[-1] + 1
                    ts_window = ts[i_min:i_max]
                    vs_window = vs[i_min:i_max]
                else:
                    ts, vs = self.data_model.get_series(var, None)
                    if not ts:
                        continue  # 无数据则跳过
                    # 手动模式：显示全部数据
                    ts_window = ts
                    vs_window = vs

                # 仅在数据变化时更新
                if (
                        self.curves[var].xData is None or
                        len(self.curves[var].xData) != len(ts_window) or
                        (ts_window and self.curves[var].xData[-1] != ts_window[-1])
                ):
                    self.curves[var].setData(ts_window, vs_window)

    # plot window时间戳更新
    def update_cursor(self):
        now = time.time() * 1000  # ms
        self.begin_line.setValue(self.reception_start_time)
        self.x_axis.set_start_time(self.reception_start_time)

        if self.plot_state == PlotState.RUNNING:
            self.window_now = now
            self.window_start = self.window_now - self.fixed_window_seconds * 1000
            self.now_line.setValue(self.window_now)  # 自动跟随时间前进

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
        """清空数据"""
        now = time.time() * 1000  # ms
        # CLEANING:
        self.plot_state = PlotState.CLEARING
        self.data_model.clear()
        self.update_cursor()
        self.update_plot()

        # IDLE:
        self.plot_state = PlotState.IDLE
        self.data_receiver.stop()
        self.data_model.clear()
        self.toggle_reception_btn.setText("Start Receive")
        self.toggle_reception_btn.setStyleSheet("background-color: orange")

    def set_curve_visibility(self, var_name, visible):
        if var_name in self.hidden_variables:
            return  # 模板隐藏的变量，忽略任何可见性修改
        if var_name in self.curves:
            self.curves[var_name].setVisible(visible)

    def set_curve_color(self, var_name, rgb):
        """设置变量曲线颜色"""
        if var_name in self.curves:
            self.colors[var_name] = rgb
            self.curves[var_name].setPen(pg.mkPen(color=rgb, width=2))
