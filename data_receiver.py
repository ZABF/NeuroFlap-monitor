import socket
import threading
import time
from collections import deque, defaultdict

import numpy as np

from data_parser import DataParser
from bota_lite import BotaSerialSensor
import MoCap.LuMo.LuMoSDKClient as LuMoSDKClient

class DataReceiver:

    JUMP_THRESHOLD_MS = 200 # ms # 判定“不是同一段接收/回绕”的门限

    def __init__(self, data_model, main_window, udp_ip="0.0.0.0", udp_port=28080, bota_port="COM10",
                 sdk_ip="172.16.23.64", rigid_id="Rigid_WingLite_R_MainRod"):
        self.data_model = data_model
        self.main_window = main_window
        self.data_transporter = main_window.data_transporter

        # UDP
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.sock = None
        self.udp_thread = None

        # Bota
        self.bota_port = bota_port
        self.bota_thread = None
        self.bota_sensor = None
        self.bota_state = "Disconnect"
        self.bota_running = False
        self.bias_buffers = defaultdict(lambda: deque(maxlen=100))  # 滑动窗口
        self.ft_bias = defaultdict(lambda: 0.0)

        # MoCap
        self.sdk_ip = sdk_ip
        # HACK: Multi Rigid
        self.rigid_id = rigid_id
        self.wing1_id = None
        self.wing2_id = None

        self.mocap_thread = None
        self.mocap_state = "Disconnect"
        self.mocap_running = False
        self.mocap_writer = None
        self.mocap_csv_file = None
        self.transport_enabled = None

        # 状态
        self.running = False

        # 统一来源状态表：
        self.source = {
            # "udp": {"session_id": 0, "min_offset":None, "first_flag":False,"last_ts":None},
            "udp:imu": {"session_id": 0, "min_offset": None, "first_flag": False, "last_ts": None},
            "udp:att": {"session_id": 0, "min_offset": None, "first_flag": False, "last_ts": None},
            "udp:servo": {"session_id": 0, "min_offset": None, "first_flag": False, "last_ts": None},
            "ft": {"session_id": 0, "min_offset": None, "first_flag": False, "last_ts": None},
            "mocap": {"session_id": 0, "min_offset": None, "first_flag": False, "last_ts": None},
        }

        # 全局
        self.pending_queue = deque()
        self.parser = DataParser()

    def start(self):
        if self.running:
            return
        self.running = True
        self._start_udp()
        self._start_bota()
        self._start_mocap()

    def stop(self):
        self.running = False
        if self.udp_thread:
            self.udp_thread.join()
            print("UDP thread stopped")
        if self.sock:
            self.sock.close()
            print("Socket closed")
        if self.bota_thread:
            self.bota_thread.join()
            print("Bota thread stopped")
        if self.mocap_thread:
            self.mocap_thread.join()
            print("MoCap thread stopped")

    # ------------------- 各源启动 -------------------
    def _start_udp(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.udp_ip, self.udp_port))
        self.udp_thread = threading.Thread(target=self.receive_udp_data, daemon=True)
        self.udp_thread.start()
        print(f"UDP listening on {self.udp_ip}:{self.udp_port}")

    def _start_bota(self):
        if self.bota_sensor:  # 已经 connect_bota 成功
            if not self.bota_thread or not self.bota_thread.isAlive():
                self.bota_thread = threading.Thread(target=self.receive_ft_data, daemon=True)
                self.bota_thread.start()
            print("Bota receiving started.")
        else:
            print("Bota not connected.")

    def _start_mocap(self):
        if self.mocap_state != "Connected":
            print("MoCap not connected.")
            return
        if not self.mocap_thread or not self.mocap_thread.is_alive():
            self.mocap_running = True
            self.mocap_thread = threading.Thread(target=self.receive_mocap_data, daemon=True)
            self.mocap_thread.start()
            print("MoCap receiving started.")
        else:
            print("MoCap thread already running.")

    # ------------------- 连接管理 -------------------
    def connect_mocap(self, sdk_ip = None):
        if sdk_ip:
            self.sdk_ip = sdk_ip
        if self.mocap_state in ("Connecting", "Connected"):
            print("MoCap already connecting or connected.")
            return

        def _connect_task():
            try:
                self.mocap_state = "Connecting..."
                LuMoSDKClient.Init()
                LuMoSDKClient.Connnect(self.sdk_ip)
                self.mocap_state = "Connected"
                print(f"Connected to {self.sdk_ip}. Listening for MoCap data... Rigid:({self.rigid_id} Wing1:({self.wing1_id} Wing2:({self.wing2_id})")
                self.mocap_running = True
                self.mocap_thread = threading.Thread(target=self.receive_mocap_data, daemon=True)
                self.mocap_thread.start()
            except Exception as e:
                self.mocap_state = "Disconnected"
                print(f"Connect {self.sdk_ip} failed: {e}")
        threading.Thread(target=_connect_task, daemon=True).start()

    def disconnect_mocap(self):
        self.mocap_running = False
        if self.mocap_thread:
            self.mocap_thread.join()
            print("Mocap thread stopped")
        LuMoSDKClient.Close()
        print("Mocap socket closed")
        self.mocap_state = "Disconnect"

    def connect_ft(self, port=None):
        if port:
            self.bota_port = port
        if self.bota_thread and self.bota_thread.is_alive():
            print("Bota thread already running.")
            return

        def _connect_task():
            try:
                self.bota_state = "Connecting..."
                self.bota_sensor = BotaSerialSensor(self.bota_port)
                if self.bota_sensor.setup():
                    self.bota_state = "Connected"
                    print(f"Found bota on {self.bota_port}")
                    self.bota_running = True
                    self.bota_thread = threading.Thread(target=self.receive_ft_data, daemon=True)
                    self.bota_thread.start()
                else:
                    print("Failed to setup bota")
                    self.bota_state = "Disconnect"
                    self.bota_sensor.close()
                    self.bota_sensor = None
                    self.bota_running = False
            except Exception as e:
                print(f"Failed to open bota: {e}")
                self.bota_state = "Disconnect"
                self.bota_sensor = None
                self.bota_running = False
        threading.Thread(target=_connect_task, daemon=True).start()

    def disconnect_ft(self):
        self.bota_running = False
        if self.bota_thread:
            self.bota_thread.join()
            print("Bota thread stopped")
        if self.bota_sensor:
            self.bota_sensor.close()
            self.bota_sensor = None
            print("Bota disconnected.")
        self.bota_state = "Disconnect"

    # ------------------- 接收线程 -------------------
    def receive_mocap_data(self):
        while self.running and self.mocap_running:
            try:
                frame = LuMoSDKClient.ReceiveData(1)    # 非阻塞
                if frame is None:
                    time.sleep(0.001)
                    continue

                self.ingest_data("mocap", frame)

                if self.transport_enabled:
                    print("data_receiver_old.py: Transport enabled.")
                    for rigid in frame.rigidBodys:
                        if rigid.Name == self.rigid_id:
                            print("data_receiver_old.py: Rigid ID found and transmitted.")
                            self.data_transporter.udp_send_mocap_message(rigid)

            except Exception as e:
                print("MoCap receive error:", e)

    def receive_udp_data(self):
        self.sock.settimeout(0.5)
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
                self.ingest_data("udp", data)
            except socket.timeout:
                continue  # 超时，说明没有数据，继续下一轮循环
            except Exception as e:
                print("UDP receive error:", e)

    def receive_ft_data(self):
        while self.running and self.bota_running:
            try:
                frame_header = self.bota_sensor._ser.read(1)
                if frame_header != self.bota_sensor.FRAME_HEADER:
                    print("Lost sync")
                    continue

                data = self.bota_sensor._ser.read(36)
                if len(data) == 36:
                    self.ingest_data("ft", data)

            except Exception as e:
                print("Bota receive error:", e)
                time.sleep(0.0001)

    # ------------------- 队列 & 统一入口 -------------------
    def ingest_data(self, data_source, data):
        """
        :param data_source:
        :param data:
        :param timestamp_unix: unix timestamp (ms)
        """
        timestamp_unix = time.time() * 1000
        self.pending_queue.append((data_source, data, timestamp_unix))

    # ------------------- 解包存储 -------------------
    def process_data(self):
        to_process = []
        while self.pending_queue:
            try:
                item = self.pending_queue.popleft()
                to_process.append(item)
            except IndexError:
                break

        for data_source, data, unix_ts in to_process:
            if data_source == "udp":
                source_ts, att, imu, servo = self.parser.parse_packet(data)
                if source_ts is None:
                    continue
                if att is not None:
                    self.data_model.add_data("udp:att",unix_ts, source_ts,att)
                if imu is not None:
                    self.data_model.add_data("udp:imu",unix_ts, source_ts,imu)
                if servo is not None:
                    self.data_model.add_data("udp:servo",unix_ts, source_ts,servo)

            elif data_source == "ft":
                source_ts, ft_data = self.parser.parse_ft_frame(data)
                if source_ts is None:
                    continue
                if ft_data:
                    corrected_data = {}
                    for k, v in ft_data.items():
                        self.bias_buffers[k].append(v)
                        corrected_data[k] = v - self.ft_bias[k]
                    self.data_model.add_data(data_source, unix_ts, source_ts, corrected_data)

            elif data_source == "mocap":
                source_ts, mocap_data = self.parser.parse_mocap_frame(data, self.rigid_id, self.wing1_id,self.wing2_id)
                if source_ts is not None:
                    continue
                if mocap_data is not None:
                    self.data_model.add_data(data_source,unix_ts, source_ts,mocap_data)
            else:
                continue

    def set_ft_bias(self):
        for k, buf in self.bias_buffers.items():
            if buf:
                self.ft_bias[k] = float(np.mean(list(buf)))
        print("Bias set:", dict(self.ft_bias))

