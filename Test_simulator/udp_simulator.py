from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
import socket, time, struct, math
from threading import Thread, Event
from ctypes import c_int16

UDP_IP, UDP_PORT = "127.0.0.1", 28080
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def to_int16(val):
    from ctypes import c_int16
    return c_int16(int(val)).value

def to_uint16(val):
    from ctypes import c_uint16
    return c_uint16(int(val)).value

def attitude(t, frame_num):
    angle_rol = 180 * math.sin(2 * 3.1416 * 3.75 * t)
    angle_pit = 180 * math.cos(t)
    angle_yaw = 180 * math.sin(0.5 * t)
    roll_6 = 180 * math.sin(t)
    pitch_6 = 180 * math.cos(t)
    yaw_6 = 180 * math.sin(0.5 * t)
    roll_Mocap = 180 * math.sin(t)
    pitch_Mocap = 180 * math.cos(t)
    yaw_Mocap = 180 * math.sin(0.5 * t)
    return ANO_Send_Attitude(angle_rol, angle_pit, angle_yaw, roll_6, pitch_6, yaw_6, roll_Mocap, pitch_Mocap, yaw_Mocap, frame_num)


def imu(t, frame_num):
    a_x = math.sin(t) * 1.5
    a_y = math.cos(t) * 2.0
    a_z = 0.98
    g_x, g_y, g_z = 0.1, 0.2, 0.3
    m_x, m_y, m_z = 1.0, 0.5, 0.0
    q0, q1, q2, q3 = 1.0, 0.0, 0.0, 0.0
    mx, my, mz = 0.01, 0.02, 0.03

    return ANO_Send_Sensor(
        a_x, a_y, a_z,
        g_x, g_y, g_z,
        m_x, m_y, m_z,
        q0, q1, q2, q3,
        mx, my, mz,
        frame_num
    )


def servo(t, frame_num):
    leftpwm = 1550 + 500 * math.sin(2 * 3.1416 * 3.75 * t)
    leftdeg = 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    rightpwm = 1450 + 500 * math.sin(2 * 3.1416 * 3.75 * t)
    rightdeg = 20 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    adc = 2048 + 10 * math.sin(t)
    freq = 0.5
    alt = 1.23
    vol = 7.4

    T_posx= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    T_posy= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    T_posz= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    C_posx= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    C_posy= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    C_posz= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    T_pitch= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    T_roll= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    C_pitch= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    C_roll= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    pitch_offset= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    roll_offset= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    pitch_p= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    roll_p= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    A_left= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    A_right= 28 + 24 * math.cos(2 * 3.1416 * 3.75 * t)
    return ANO_Send_Servo_Data(
        leftpwm, leftdeg, rightpwm, rightdeg, adc, freq, alt, vol, T_posx,T_posy, T_posz,
        C_posx,C_posy,  C_posz,  T_pitch, T_roll,  C_pitch, C_roll,
        pitch_offset, roll_offset,pitch_p, roll_p,A_left,A_right, frame_num
    )


import struct


def ANO_Send_Attitude(angle_rol, angle_pit, angle_yaw, roll_6, pitch_6, yaw_6, roll_Mocap, pitch_Mocap, yaw_Mocap, frame_num):
    data = bytearray()
    data.append(0xAA)
    data.append(0xAA)
    data.append(0x01)
    data.append(0x00)  # placeholder for length

    _temp = to_int16(angle_rol * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(angle_pit * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(angle_yaw * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(roll_6 * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(pitch_6 * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(yaw_6 * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(roll_Mocap * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(pitch_Mocap * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(yaw_Mocap * 100)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    _temp = to_int16(frame_num)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    data[3] = len(data) - 4
    checksum = sum(data) & 0xFF
    data.append(checksum)

    return bytes(data)


def ANO_Send_Sensor(a_x, a_y, a_z, g_x, g_y, g_z, m_x, m_y, m_z, q0, q1, q2, q3, mx, my, mz, frame_num):
    data = bytearray()
    data.append(0xAA)
    data.append(0xAA)
    data.append(0x02)
    data.append(0x00)  # placeholder

    for val in [a_x, a_y, a_z, g_x, g_y, g_z, m_x, m_y, m_z, q0, q1, q2, q3, mx, my, mz]:
        _temp = to_int16(val * 100)
        data.append((_temp >> 8) & 0xFF)
        data.append(_temp & 0xFF)

    _temp = to_int16(frame_num)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    data[3] = len(data) - 4
    checksum = sum(data) & 0xFF
    data.append(checksum)

    return bytes(data)

def ANO_Send_Servo_Data(leftpwm, leftdeg, rightpwm, rightdeg, adc, freq, alt, vol,
                        T_posx,T_posy, T_posz, C_posx,C_posy,  C_posz,
                        T_pitch, T_roll,  C_pitch, C_roll,
                        pitch_offset, roll_offset,pitch_p, roll_p,A_left,A_right,frame_num):
    data = bytearray()
    data.append(0xAA)
    data.append(0xAA)
    data.append(0xF3)
    data.append(0x00)  # placeholder

    for val in [leftpwm, leftdeg, rightpwm, rightdeg, adc]:
        _temp = to_int16(val)
        data.append((_temp >> 8) & 0xFF)
        data.append(_temp & 0xFF)

    for val in [freq, alt]:
        _temp = to_int16(val * 100)
        data.append((_temp >> 8) & 0xFF)
        data.append(_temp & 0xFF)

    for val in [vol, T_posx, T_posy, T_posz, C_posx, C_posy, C_posz,]:
        _temp = to_int16(val)
        data.append((_temp >> 8) & 0xFF)
        data.append(_temp & 0xFF)

    for val in [T_pitch, T_roll, C_pitch, C_roll,pitch_offset, roll_offset,pitch_p, roll_p,A_left,A_right]:
        _temp = to_int16(val * 100)
        data.append((_temp >> 8) & 0xFF)
        data.append(_temp & 0xFF)

    _temp = to_int16(frame_num)
    data.append((_temp >> 8) & 0xFF)
    data.append(_temp & 0xFF)

    data[3] = len(data) - 4
    checksum = sum(data) & 0xFF
    data.append(checksum)

    return bytes(data)


def send(p): sock.sendto(p, (UDP_IP, UDP_PORT))


class Sender(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UDP模拟器")
        self.setGeometry(200, 200, 400, 160)

        self.status = QLabel("状态：未发送", alignment=Qt.AlignCenter)
        self.status.setStyleSheet("color: red")

        self.btn_start = QPushButton("开始发送")
        self.btn_stop = QPushButton("停止发送")

        # 初始状态
        self.btn_start.setStyleSheet("background-color: lightgreen")
        self.btn_stop.setStyleSheet("background-color: lightgray")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)

        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)

        self.stop_event = Event()
        self.thread = None

        self.t_start_1 = 0
        self.t_start_2 = 0

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = Thread(target=self.loop, daemon=True)
            self.thread.start()
            time.sleep(1)

            self.status.setText(f"状态：发送中 1:${self.t_start_1} 2:,${self.t_start_2}")
            self.status.setStyleSheet("color: green")

            # 状态更新
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_start.setStyleSheet("background-color: lightgray")
            self.btn_stop.setStyleSheet("background-color: lightcoral")

    def stop(self):
        self.stop_event.set()
        self.status.setText("状态：已停止")
        self.status.setStyleSheet("color: red")

        # 状态更新
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_start.setStyleSheet("background-color: lightgreen")
        self.btn_stop.setStyleSheet("background-color: lightgray")

    def loop(self):
        t = 0.0
        frame_num = 0
        interval = 0.01  # 10ms
        next_time = time.perf_counter()
        while not self.stop_event.is_set():
            now = time.perf_counter()
            if now >= next_time:
                if frame_num == 0:
                    self.t_start_1 = time.time_ns()/1000000-1756470000000
                    send(attitude(t, frame_num))
                    send(imu(t, frame_num))
                    send(servo(t, frame_num))
                    self.t_start_2 = time.time_ns()/1000000-1756470000000
                else:
                    send(attitude(t, frame_num))
                    send(imu(t, frame_num))
                    send(servo(t, frame_num))

                frame_num = (frame_num + 1) & 0xFFFF
                t += interval
                next_time += interval
            else:
                # 减少CPU占用，但保持高响应
                time.sleep(0.001)

    def closeEvent(self, event):
        self.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication([])
    win = Sender()
    win.show()
    app.exec_()
