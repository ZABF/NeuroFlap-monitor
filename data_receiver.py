import socket
import threading
import time
from collections import defaultdict, deque

import numpy as np

from bota_lite import BotaSerialSensor
from data_parser import DataParser
from nfv1_parser import NFv1Parser
import MoCap.LuMo.LuMoSDKClient as LuMoSDKClient


class DataReceiver:
    NF_SOURCE_PREFIX = "udp:nf:"
    NF_SCHEMA_RETRY_MS = 1000

    def __init__(
        self,
        data_model,
        main_window,
        udp_ip="0.0.0.0",
        udp_port=28080,
        bota_port="COM10",
        sdk_ip="172.16.23.64",
        rigid_id="Rigid_WingLite_R_MainRod",
        udp_target_ip=None,
        udp_target_port=None,
    ):
        self.data_model = data_model
        self.main_window = main_window
        self.data_transporter = main_window.data_transporter

        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.udp_target_ip = udp_target_ip or getattr(main_window, "esp32_ip", None)
        self.udp_target_port = udp_target_port or udp_port
        self.sock = None
        self.udp_thread = None

        self.bota_port = bota_port
        self.bota_thread = None
        self.bota_sensor = None
        self.bota_state = "Disconnect"
        self.bota_running = False
        self.bias_buffers = defaultdict(lambda: deque(maxlen=100))
        self.ft_bias = defaultdict(lambda: 0.0)

        self.sdk_ip = sdk_ip
        self.rigid_id = rigid_id
        self.wing1_id = None
        self.wing2_id = None

        self.mocap_thread = None
        self.mocap_state = "Disconnect"
        self.mocap_running = False
        self.mocap_writer = None
        self.mocap_csv_file = None
        self.transport_enabled = False

        self.running = False
        self.pending_queue = deque()
        self.parser = DataParser()
        self.nf_parser = NFv1Parser()
        self.first_ft_received_flag = False
        self.first_udp_received_flag = False

        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_signal_no = {}
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_request_id = 0
        self.nf_last_schema_request_ms = 0.0
        self.nf_last_packet_seq = None
        self.nf_packet_gap_count = 0
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0

    def start(self):
        if self.running:
            return
        self.running = True
        self._start_udp()
        self._start_bota()
        self._start_mocap()

    def stop(self):
        self.running = False
        self.bota_running = False
        self.mocap_running = False

        if self.udp_thread and self.udp_thread.is_alive():
            self.udp_thread.join()
            print("UDP thread stopped")
        self.udp_thread = None

        if self.sock:
            self.sock.close()
            self.sock = None
            print("Socket closed")

        if self.bota_thread and self.bota_thread.is_alive():
            self.bota_thread.join()
            print("Bota thread stopped")
        self.bota_thread = None

        if self.mocap_thread and self.mocap_thread.is_alive():
            self.mocap_thread.join()
            print("MoCap thread stopped")
        self.mocap_thread = None

    def _start_udp(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Windows UDP sockets can raise WSAECONNRESET(10054) on recvfrom after
        # sending to an unreachable peer; disable this behavior for retry flow.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except OSError:
                pass
        self.sock.bind((self.udp_ip, self.udp_port))
        self.udp_thread = threading.Thread(target=self.receive_udp_data, daemon=True)
        self.udp_thread.start()
        self.begin_nfv1_schema_sync()
        print(f"UDP listening on {self.udp_ip}:{self.udp_port}")

    def begin_nfv1_schema_sync(self):
        if self.nf_schema_retry_active and not self.nf_schema_order:
            return
        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_signal_no = {}
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_last_packet_seq = None
        self.nf_schema_retry_active = True
        self.nf_next_schema_retry_ms = 0.0
        self._request_nfv1_schema(force=True)

    def _tick_nfv1_schema_retry(self):
        if not self.nf_schema_retry_active:
            return
        if self.nf_schema_order:
            self.nf_schema_retry_active = False
            self.nf_next_schema_retry_ms = 0.0
            return

        now_ms = time.time() * 1000.0
        if now_ms < self.nf_next_schema_retry_ms:
            return

        self._request_nfv1_schema(force=True)
        self.nf_next_schema_retry_ms = now_ms + self.NF_SCHEMA_RETRY_MS

    def _start_bota(self):
        if self.bota_sensor:
            if not self.bota_thread or not self.bota_thread.is_alive():
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

    def connect_mocap(self, sdk_ip=None):
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
                print(
                    f"Connected to {self.sdk_ip}. Listening for MoCap data... "
                    f"Rigid:({self.rigid_id}) Wing1:({self.wing1_id}) Wing2:({self.wing2_id})"
                )
                self.mocap_running = True
                self.mocap_thread = threading.Thread(target=self.receive_mocap_data, daemon=True)
                self.mocap_thread.start()
            except Exception as exc:
                self.mocap_state = "Disconnected"
                print(f"Connect {self.sdk_ip} failed: {exc}")

        threading.Thread(target=_connect_task, daemon=True).start()

    def disconnect_mocap(self):
        self.mocap_running = False
        if self.mocap_thread and self.mocap_thread.is_alive():
            self.mocap_thread.join()
            print("Mocap thread stopped")
        self.mocap_thread = None
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
            except Exception as exc:
                print(f"Failed to open bota: {exc}")
                self.bota_state = "Disconnect"
                self.bota_sensor = None
                self.bota_running = False

        threading.Thread(target=_connect_task, daemon=True).start()

    def disconnect_ft(self):
        self.bota_running = False
        if self.bota_thread and self.bota_thread.is_alive():
            self.bota_thread.join()
            print("Bota thread stopped")
        self.bota_thread = None
        if self.bota_sensor:
            self.bota_sensor.close()
            self.bota_sensor = None
            print("Bota disconnected.")
        self.bota_state = "Disconnect"

    def receive_mocap_data(self):
        while self.running and self.mocap_running:
            try:
                frame = LuMoSDKClient.ReceiveData(1)
                if frame is None:
                    time.sleep(0.001)
                    continue

                self.ingest_data("mocap", frame)

                if self.transport_enabled:
                    for rigid in frame.rigidBodys:
                        if rigid.Name == self.rigid_id:
                            self.data_transporter.udp_send_mocap_message(rigid)
            except Exception as exc:
                print("MoCap receive error:", exc)

    def receive_udp_data(self):
        self.sock.settimeout(0.5)
        while self.running:
            try:
                data, remote_addr = self.sock.recvfrom(2048)
                self.ingest_data("udp", data, {"remote_addr": remote_addr})
            except socket.timeout:
                continue
            except OSError as exc:
                if getattr(exc, "winerror", None) == 10054:
                    continue
                break
            except Exception as exc:
                print("UDP receive error:", exc)

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
            except Exception as exc:
                print("Bota receive error:", exc)
                time.sleep(0.0001)

    def ingest_data(self, data_source, data, meta=None):
        timestamp_unix = time.time() * 1000.0
        self.pending_queue.append((data_source, data, timestamp_unix, meta or {}))

    def _request_nfv1_schema(self, force=False):
        if not self.sock or not self.udp_target_ip or not self.udp_target_port:
            return False

        now_ms = time.time() * 1000.0
        if not force and (now_ms - self.nf_last_schema_request_ms) < self.NF_SCHEMA_RETRY_MS:
            return False

        self.nf_request_id = (self.nf_request_id + 1) & 0xFFFFFFFF
        packet = self.nf_parser.build_schema_request(self.nf_request_id)
        try:
            self.sock.sendto(packet, (self.udp_target_ip, self.udp_target_port))
            self.nf_last_schema_request_ms = now_ms
            return True
        except OSError as exc:
            print(f"NF schema request failed: {exc}")
            return False

    def _handle_nfv1_schema_response(self, packet):
        if (not self.nf_schema_retry_active) and self.nf_schema_order:
            return

        chunk_total = packet["chunk_total"]
        chunk_index = packet["chunk_index"]

        if chunk_total == 0:
            return

        # chunk 0 indicates a fresh schema transfer.
        if chunk_index == 0 or self.nf_schema_chunk_total != chunk_total:
            self.nf_schema_chunks = {}
            self.nf_schema_chunk_total = chunk_total

        self.nf_schema_chunks[chunk_index] = packet["entries"]
        if len(self.nf_schema_chunks) != self.nf_schema_chunk_total:
            return

        entries = []
        for chunk_index in range(self.nf_schema_chunk_total):
            chunk_entries = self.nf_schema_chunks.get(chunk_index)
            if chunk_entries is None:
                return
            entries.extend(chunk_entries)

        schema = {}
        schema_by_signal_no = {}
        self.nf_schema_order = []
        used_names = set()
        ordered_names = []
        for entry in entries:
            gid = entry["gid"]
            base_name = entry["name"] or f"gid_{gid:08X}"
            var_name = base_name
            if var_name in used_names:
                var_name = f"{base_name}[{gid:08X}]"
            used_names.add(var_name)
            schema[gid] = {
                "gid": gid,
                "scalar_type": entry["scalar_type"],
                "name": entry["name"],
                "unit": entry["unit"],
                "var_name": var_name,
            }
            domain = (gid >> 16) & 0xFFFF
            signal_no = gid & 0xFFFF
            if domain == 0 and signal_no < 256:
                schema_by_signal_no[signal_no] = schema[gid]
            self.nf_schema_order.append(schema[gid])
            ordered_names.append(var_name)

        self.nf_schema = schema
        self.nf_schema_by_signal_no = schema_by_signal_no
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.main_window.register_signal_export_variables(ordered_names)
        print(f"NF schema synced: count={len(schema)}")

    def _process_nfv1_data(self, packet, unix_ts):
        if not self.nf_schema_by_signal_no:
            if not self.nf_schema_retry_active:
                self.begin_nfv1_schema_sync()
            return

        if self.nf_last_packet_seq is not None:
            expected_packet_seq = (self.nf_last_packet_seq + 1) & 0xFFFFFFFF
            if packet["packet_seq"] != expected_packet_seq:
                self.nf_packet_gap_count += 1
        self.nf_last_packet_seq = packet["packet_seq"]

        # Offset estimate uses packet send_us; each sample keeps its own t_src_us.
        send_timestamp_ms = packet["send_us"] / 1000.0
        send_us = int(packet["send_us"])
        base_hi = send_us & 0xFFFFFFFF00000000
        for item in packet["items"]:
            signal_no = int(item.get("signal_no", 0))
            desc = self.nf_schema_by_signal_no.get(signal_no)
            if desc is None:
                continue
            value = self.nf_parser.raw_to_value(desc["scalar_type"], item["raw"])
            if value is None:
                continue

            t32 = int(item["t_src_us"]) & 0xFFFFFFFF
            cand = base_hi | t32
            if cand + 0x80000000 < send_us:
                cand += 0x100000000
            elif cand > send_us + 0x80000000:
                cand -= 0x100000000

            src_timestamp_ms = cand / 1000.0
            unix_for_offset = unix_ts + (src_timestamp_ms - send_timestamp_ms)
            src = f"{self.NF_SOURCE_PREFIX}{desc['gid']}"
            self.data_model.add_data(src, unix_for_offset, src_timestamp_ms, {desc["var_name"]: value})

    def _process_udp_packet(self, data, unix_ts, meta):
        remote_addr = meta.get("remote_addr")
        if remote_addr:
            self.udp_target_ip = remote_addr[0]
            self.udp_target_port = remote_addr[1]

        packet = self.nf_parser.parse_packet(data)
        if packet is None:
            return

        if packet["type"] == "schema_resp":
            self._handle_nfv1_schema_response(packet)
            return

        if packet["type"] == "data":
            self._process_nfv1_data(packet, unix_ts)

    def process_data(self):
        self._tick_nfv1_schema_retry()

        to_process = []
        while self.pending_queue:
            try:
                to_process.append(self.pending_queue.popleft())
            except IndexError:
                break

        for data_source, data, unix_ts, meta in to_process:
            if data_source == "udp":
                self._process_udp_packet(data, unix_ts, meta)
                continue

            if data_source == "ft":
                parsed = self.parser.parse_ft_frame(data)
                if not parsed or len(parsed) != 2:
                    continue
                source_ts, ft_data = parsed
                if source_ts is None or not ft_data:
                    continue

                corrected_data = {}
                for key, value in ft_data.items():
                    self.bias_buffers[key].append(value)
                    corrected_data[key] = value - self.ft_bias[key]
                self.data_model.add_data(data_source, unix_ts, source_ts, corrected_data)
                continue

            if data_source == "mocap":
                parsed = self.parser.parse_mocap_frame(data, self.rigid_id, self.wing1_id, self.wing2_id)
                if not parsed or len(parsed) != 2:
                    continue
                source_ts, mocap_data = parsed
                if source_ts is None or mocap_data is None:
                    continue
                self.data_model.add_data(data_source, unix_ts, source_ts, mocap_data)

    def set_ft_bias(self):
        for key, buf in self.bias_buffers.items():
            if buf:
                self.ft_bias[key] = float(np.mean(list(buf)))
        print("Bias set:", dict(self.ft_bias))
