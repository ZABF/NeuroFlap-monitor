import socket
import threading
import time
from collections import deque, defaultdict

import numpy as np

from data_parser import DataParser
from bota_lite import BotaSerialSensor
import MoCap.LuMo.LuMoSDKClient as LuMoSDKClient

class DataReceiver_old:

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

    # ------------------- 核心处理 -------------------
    def process_data(self):
        to_process = []
        while self.pending_queue:
            try:
                item = self.pending_queue.popleft()
                to_process.append(item)
            except IndexError:
                break

        for data_source, data, unix_ts in to_process:
            # --Start Process--
            # elapsed = perf_time - self.reception_start_time
            # if elapsed < 0:
            #     continue
            if data_source == "udp":
                source_ts, att, imu, servo = self.parser.parse_packet(data)

                if source_ts is None:
                    continue

                # 解包出这一帧数据的数据：att， 时间戳 source_ts，和接收到上位机的时间戳unix_ts. 开始数据对其并存储数据
                if att is not None:
                    # 这一步根据source ts和unix ts来更新数据源”upd:att“的最小时间戳。
                    # 返回值包括：
                    #   session_id:(通过前后时间戳判断是否仍在同一会话)
                    #   recon_ts: source_ts + 最新的min_offset,作为该数据源数据对其的时间戳
                    #   new_min: 标记是否更新了最小时间戳(后续用来进行时间戳修正)
                    #   min_offset: 目前为止的min_offset
                    session_id, recon_ts, new_min, min_offset= self.update_min_offset("udp:att", unix_ts, source_ts)
                    if new_min:
                        # 如果找到了新的min_offset,就对该数据源时间戳进行修，
                        # 传入参数包括:
                        # 数据源名称”upd:att“
                        # 当前会话session_id,只修改当前会话的时间戳，不影响之前的会话
                        # 更新的min_offset,用于修正时间戳即udp:att的recon_ts都改为source_ts+(最新的)min_offset
                        self.data_model.reapply_offset_for_session(source = "udp:att", session_id = session_id, min_offset = min_offset)

                    # 存储数据源udp:att的时间戳，包括
                    # reconstructive_timestamp: 即每次source_ts+min_offset
                    # source_timestamp: 即数据来源的自身没有加offset前的时间戳
                    # min_offset: 可能冗余了
                    # session_id：时间戳对应的会话id
                    self.data_model.add_timestamp(source = "udp:att",reconstructive_timestamp = recon_ts, source_timestamp = source_ts, min_offset = min_offset, session_id = session_id)
                    for k, v in att.items():
                        self.data_model.add_data(key = k, value = v, source = "udp:att")

                if imu is not None:
                    session_id, recon_ts, new_min, min_offset = self.update_min_offset("udp:imu", unix_ts, source_ts)
                    if new_min:
                        self.data_model.add_timestamp("udp:imu",recon_ts, source_ts, min_offset, session_id)
                    for k, v in imu.items():
                        self.data_model.add_data(k, v, "udp:imu")

                if servo is not None:
                    session_id, recon_ts, new_min, min_offset = self.update_min_offset("udp:servo", unix_ts, source_ts)
                    if new_min:
                        self.data_model.add_timestamp("udp:servo", recon_ts, source_ts, min_offset, session_id)
                    for k, v in servo.items():
                        self.data_model.add_data(k, v, "udp:servo")

            elif data_source == "ft":
                source_ts, ft_data = self.parser.parse_ft_frame(data)
                if source_ts is None:
                    continue

                session_id, recon_ts, new_min, min_offset = self.update_min_offset(data_source, unix_ts, source_ts)
                if new_min:
                    self.data_model.add_timestamp(data_source, recon_ts, source_ts, min_offset, session_id)

                if ft_data is not None:
                    for k, v in ft_data.items():
                        self.bias_buffers[k].append(v)  # 缓存数据
                        corrected_value = v - self.ft_bias[k]
                        self.data_model.add_data(k, corrected_value,data_source)

            elif data_source == "mocap":
                source_ts, rigid_data_dict,marker_list = self.parser.parse_mocap_frame(data, self.rigid_id, self.wing1_id,self.wing2_id)
                if source_ts is None:
                    continue

                session_id, recon_ts, new_min,min_offset = self.update_min_offset(data_source, unix_ts, source_ts)

                if self.rigid_id in rigid_data_dict:
                    mocap_data = rigid_data_dict[self.rigid_id]
                    for k, v in mocap_data.items():
                        if new_min:
                            self.data_model.reapply_offset_for_session(session_id, self.source[data_source]["min_offset"])
                        self.data_model.add_data(k, recon_ts,source_ts, v, session_id)


                if self.wing1_id in rigid_data_dict:
                    mocap_data = rigid_data_dict[self.wing1_id]
                    for k, v in mocap_data.items():
                        self.data_model.add_data(k, recon_ts,source_ts, v, session_id)

                if self.wing2_id in rigid_data_dict:
                    mocap_data = rigid_data_dict[self.wing2_id]
                    for k, v in mocap_data.items():
                        self.data_model.add_data(k, recon_ts,source_ts, v, session_id)

                for marker in marker_list:
                    self.data_model.add_data(f"Marker_Id", recon_ts, source_ts, marker["Id"],session_id)
                    self.data_model.add_data(f"Marker_Group", recon_ts, source_ts,marker["Name"],session_id)
                    self.data_model.add_data(f"Marker_X", recon_ts, source_ts,marker["X"],session_id)
                    self.data_model.add_data(f"Marker_Y", recon_ts, source_ts,marker["Y"],session_id)
                    self.data_model.add_data(f"Marker_Z", recon_ts, source_ts,marker["Z"],session_id)
            else:
                continue

    def set_ft_bias(self):
        for k, buf in self.bias_buffers.items():
            if buf:
                self.ft_bias[k] = np.mean(list(buf))
        print("Bias set:", dict(self.ft_bias))


    def update_min_offset(self,data_source,unix_ts,source_ts):
        source = self.source[data_source]
        new_min_found = False

        if source["last_ts"] is not None:
            if abs(source_ts-source["last_ts"]) > self.JUMP_THRESHOLD_MS:
                source["session_id"] += 1
                source["min_offset"] = None
                source["first_flag"] = False
        source["last_ts"] = source_ts

        temp_offset = unix_ts - source_ts
        if not source["first_flag"]:
            source["first_flag"] = True
            source["min_offset"] = temp_offset
            new_min_found = True
        else:
            if temp_offset < source["min_offset"]:
                source["min_offset"] = temp_offset
                new_min_found = True

        reconstructed_ts = source_ts + source["min_offset"]

        return source["session_id"], reconstructed_ts, new_min_found, source["min_offset"]

 #  原时间戳代码：
 # # 找到udp最小延迟
 #                    temp_udp_offset = timestamp_unix - timestamp_udp
 #                    if self.timestamp_min_udp_offset is None:
 #                        self.timestamp_min_udp_offset = temp_udp_offset
 #                    else:
 #                        if self.last_timestamp_udp:
 #                            # NOTE:  200ms这个值要大于最大网络卡顿/延迟时间（即允许卡顿200ms程序仍然认为是连续的接收，即前后数据有连续的时间戳），
 #                            #        200ms这个值要小于意外重启间隔（即时间戳之差大于这个值，则认为是两次不同的接收，要重新计算收发双方时间戳偏移量）
 #                            # HACK:  这个语句同时用于避免16bit回绕。->有可能 16bit 超限导致时间戳之差小于 200ms，此时认为重新开始接收，重新计算偏移量
 #                            if abs(timestamp_udp - self.last_timestamp_udp) > 200:  # 200ms
 #                                self.first_udp_received_flag = False
 #                        self.last_timestamp_udp = timestamp_udp
 #
 #                        if not self.first_udp_received_flag:
 #                            self.first_udp_received_flag = True
 #                            self.timestamp_min_udp_offset = temp_udp_offset
 #                        else:
 #                            # OPTIMIZE: 局部/平滑最小值？防止异常offset
 #                            self.timestamp_min_udp_offset = min(temp_udp_offset, self.timestamp_min_udp_offset)
 #                            self.data_model.reapply_offset_for_session(session_id, new_offset=self.timestamp_min_udp_offset)
 #                            # 绘图层里检测 model.needs_full_redraw == True 时，做一次全量 curve.setData(...)
 #
 #                    reconstructive_timestamp_udp = timestamp_udp + self.timestamp_min_udp_offset
 #                    # if att:
 #                    #     print(f'a unix: {timestamp_unix}; udp: {timestamp_udp}; x-p: {temp_offset}; reT:{reconstructive_timestamp_udp}; od:{(self.timestamp_min_udp_offset - temp_offset)}')
 #                    # if imu:
 #                    #     print(f'i unix: {timestamp_unix}; udp: {timestamp_udp}; x-p: {temp_offset}; reT:{reconstructive_timestamp_udp}; od:{(self.timestamp_min_udp_offset - temp_offset)}')
 #                    # if servo:
 #                    #     print(f's unix: {timestamp_unix}; udp: {timestamp_udp}; x-p: {temp_offset}; reT:{reconstructive_timestamp_udp}; od:{(self.timestamp_min_udp_offset - temp_offset)}')
