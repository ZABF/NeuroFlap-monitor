import socket
import threading
import time
from collections import defaultdict, deque

import numpy as np

from bota_lite import BotaSerialSensor
from data_parser import DataParser
from nfv3_parser import NFv3Parser
import MoCap.LuMo.LuMoSDKClient as LuMoSDKClient


class DataReceiver:
    NF_SOURCE_PREFIX = "udp:nf:"
    NF_CLOCK_SOURCE = "udp:nf:clock"
    NF_SCHEMA_RETRY_MS = 1000
    NF_CONNECT_RETRY_MS = 200
    NF_CONNECT_TIMEOUT_MS = 5000
    NF_LINK_PING_MS = 2000
    NF_LINK_PING_RETRY_MS = 1000
    NF_LINK_TIMEOUT_MS = 6000
    NF_RECONNECT_MIN_MS = 500
    NF_RECONNECT_MAX_MS = 5000
    NF_BUSY_RECONNECT_MS = 3000
    NF_DISCONNECT_BURST_COUNT = 3
    NF_DISCONNECT_BURST_INTERVAL_MS = 120

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
        self.nf_parser = NFv3Parser()
        self.first_ft_received_flag = False
        self.first_udp_received_flag = False

        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_endpoint_no = {}
        self.nf_schema_generation = None
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_request_id = 0
        self.nf_last_schema_request_ms = 0.0
        self.nf_schema_req_sent_count = 0
        self.nf_last_schema_sync_ok_ms = 0.0
        self.nf_last_packet_seq = None
        self.nf_packet_gap_count = 0
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.nf_want_connected = False
        self.nf_connected = False
        self.nf_connecting = False
        self.nf_connect_start_ms = 0.0
        self.nf_next_connect_req_ms = 0.0
        self.nf_last_connect_req_ms = 0.0
        self.nf_next_reconnect_ms = 0.0
        self.nf_reconnect_backoff_ms = float(self.NF_RECONNECT_MIN_MS)
        self.nf_disconnect_burst_left = 0
        self.nf_next_disconnect_burst_ms = 0.0
        self.nf_last_pong_ms = 0.0
        self.nf_next_ping_due_ms = 0.0
        self.nf_next_ping_retry_ms = 0.0
        self.nf_waiting_pong = False
        self.nf_busy_owner_ip = ""
        self.nf_busy_owner_port = 0
        self.nf_last_error = ""
        self.nf_local_ip = "0.0.0.0"

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
        try:
            self.nf_local_ip = str(self.sock.getsockname()[0] or "0.0.0.0")
        except OSError:
            self.nf_local_ip = "0.0.0.0"
        self.udp_thread = threading.Thread(target=self.receive_udp_data, daemon=True)
        self.udp_thread.start()
        print(f"UDP listening on {self.udp_ip}:{self.udp_port}")

    def _resolve_local_ip(self):
        if not self.udp_target_ip or not self.udp_target_port:
            return self.nf_local_ip
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((self.udp_target_ip, self.udp_target_port))
                self.nf_local_ip = str(probe.getsockname()[0] or self.nf_local_ip)
        except OSError:
            pass
        return self.nf_local_ip

    def connect_nfv3(self, target_ip=None, target_port=None):
        if target_ip:
            self.udp_target_ip = target_ip
        if target_port:
            self.udp_target_port = int(target_port)
        if not self.running:
            self.start()

        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_endpoint_no = {}
        self.nf_schema_generation = None
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0

        now_ms = time.time() * 1000.0
        self.nf_want_connected = True
        self.nf_reconnect_backoff_ms = float(self.NF_RECONNECT_MIN_MS)
        self.nf_next_reconnect_ms = 0.0
        self.nf_disconnect_burst_left = 0
        self.nf_next_disconnect_burst_ms = 0.0
        self.nf_last_pong_ms = 0.0
        self.nf_next_ping_due_ms = 0.0
        self.nf_next_ping_retry_ms = 0.0
        self.nf_waiting_pong = False
        self.nf_busy_owner_ip = ""
        self.nf_busy_owner_port = 0
        self.nf_last_error = ""
        self._start_connect_attempt_(now_ms)

    def disconnect_nfv3(self):
        self.nf_want_connected = False
        self.nf_connecting = False
        self.nf_connected = False
        self.nf_next_reconnect_ms = 0.0
        self.nf_reconnect_backoff_ms = float(self.NF_RECONNECT_MIN_MS)
        self.nf_waiting_pong = False
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.nf_busy_owner_ip = ""
        self.nf_busy_owner_port = 0
        self.nf_disconnect_burst_left = self.NF_DISCONNECT_BURST_COUNT
        self.nf_next_disconnect_burst_ms = 0.0
        if self.nf_disconnect_burst_left > 0:
            self._send_disconnect_request()
            self.nf_disconnect_burst_left -= 1
            self.nf_next_disconnect_burst_ms = time.time() * 1000.0 + self.NF_DISCONNECT_BURST_INTERVAL_MS

    def _start_connect_attempt_(self, now_ms):
        self.nf_connecting = True
        self.nf_connected = False
        self.nf_connect_start_ms = now_ms
        self.nf_next_connect_req_ms = now_ms + self.NF_CONNECT_RETRY_MS
        self.nf_last_connect_req_ms = 0.0
        self.nf_waiting_pong = False
        self.nf_busy_owner_ip = ""
        self.nf_busy_owner_port = 0
        self._resolve_local_ip()
        self._send_connect_request()

    def _schedule_reconnect_(self, now_ms, reason="", busy=False):
        if not self.nf_want_connected:
            return
        if reason:
            self.nf_last_error = reason
        delay_ms = self.NF_BUSY_RECONNECT_MS if busy else int(self.nf_reconnect_backoff_ms)
        self.nf_next_reconnect_ms = now_ms + delay_ms
        if not busy:
            self.nf_reconnect_backoff_ms = min(
                float(self.NF_RECONNECT_MAX_MS),
                max(float(self.NF_RECONNECT_MIN_MS), self.nf_reconnect_backoff_ms * 2.0),
            )

    def get_nfv3_status(self):
        state = "disconnected"
        if self.nf_connected:
            state = "connected"
        elif self.nf_connecting:
            state = "connecting"
        elif self.nf_busy_owner_ip:
            state = "busy"
        return {
            "state": state,
            "want_connected": bool(self.nf_want_connected),
            "connected": bool(self.nf_connected),
            "connecting": bool(self.nf_connecting),
            "target_ip": self.udp_target_ip or "",
            "target_port": int(self.udp_target_port or 0),
            "local_ip": self.nf_local_ip,
            "busy_owner_ip": self.nf_busy_owner_ip,
            "busy_owner_port": int(self.nf_busy_owner_port or 0),
            "last_error": self.nf_last_error,
        }

    def begin_nfv3_schema_sync(self):
        if not self.nf_connected:
            return
        if self.nf_schema_retry_active and not self.nf_schema_order:
            print(
                "NF schema sync begin skipped: "
                f"schema_req_sent_count={self.nf_schema_req_sent_count} "
                f"last_sync_ok_ts={int(self.nf_last_schema_sync_ok_ms)} "
                f"retry_active={int(self.nf_schema_retry_active)}"
            )
            return
        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_endpoint_no = {}
        self.nf_schema_generation = None
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_last_packet_seq = None
        self.nf_schema_retry_active = True
        self.nf_next_schema_retry_ms = 0.0
        print(
            "NF schema sync begin: "
            f"schema_req_sent_count={self.nf_schema_req_sent_count} "
            f"last_sync_ok_ts={int(self.nf_last_schema_sync_ok_ms)} "
            f"retry_active={int(self.nf_schema_retry_active)}"
        )
        self._request_nfv3_schema(force=True)

    def _tick_nfv3_schema_retry(self):
        if not self.nf_schema_retry_active:
            return

        now_ms = time.time() * 1000.0
        if now_ms < self.nf_next_schema_retry_ms:
            return

        print(
            "NF schema retry tick: "
            f"schema_req_sent_count={self.nf_schema_req_sent_count} "
            f"last_sync_ok_ts={int(self.nf_last_schema_sync_ok_ms)} "
            f"retry_active={int(self.nf_schema_retry_active)}"
        )
        self._request_nfv3_schema(force=True)
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

    def _send_udp_packet(self, packet):
        if not self.sock or not self.udp_target_ip or not self.udp_target_port:
            return False
        try:
            self.sock.sendto(packet, (self.udp_target_ip, self.udp_target_port))
            return True
        except OSError as exc:
            self.nf_last_error = f"udp send failed: {exc}"
            return False

    def _send_connect_request(self):
        packet = self.nf_parser.build_connect_request()
        if self._send_udp_packet(packet):
            self.nf_last_connect_req_ms = time.time() * 1000.0
            return True
        return False

    def _send_link_ping(self):
        packet = self.nf_parser.build_link_ping()
        return self._send_udp_packet(packet)

    def _send_disconnect_request(self):
        packet = self.nf_parser.build_disconnect_request()
        return self._send_udp_packet(packet)

    def _tick_nfv3_connection(self):
        now_ms = time.time() * 1000.0

        if self.nf_disconnect_burst_left > 0 and now_ms >= self.nf_next_disconnect_burst_ms:
            self._send_disconnect_request()
            self.nf_disconnect_burst_left -= 1
            self.nf_next_disconnect_burst_ms = now_ms + self.NF_DISCONNECT_BURST_INTERVAL_MS

        if self.nf_connecting:
            if (now_ms - self.nf_connect_start_ms) >= self.NF_CONNECT_TIMEOUT_MS:
                self.nf_connecting = False
                self.nf_connected = False
                self.nf_waiting_pong = False
                self._schedule_reconnect_(now_ms, reason="connect timeout", busy=False)
                return
            if now_ms >= self.nf_next_connect_req_ms:
                self._send_connect_request()
                self.nf_next_connect_req_ms = now_ms + self.NF_CONNECT_RETRY_MS
            return

        if not self.nf_connected:
            if self.nf_want_connected and now_ms >= self.nf_next_reconnect_ms:
                self._start_connect_attempt_(now_ms)
            return

        if self.nf_last_pong_ms > 0 and (now_ms - self.nf_last_pong_ms) >= self.NF_LINK_TIMEOUT_MS:
            self.nf_connected = False
            self.nf_waiting_pong = False
            self.nf_schema_retry_active = False
            self.nf_next_schema_retry_ms = 0.0
            self._schedule_reconnect_(now_ms, reason="link timeout", busy=False)
            return

        if self.nf_waiting_pong:
            if now_ms >= self.nf_next_ping_retry_ms:
                self._send_link_ping()
                self.nf_next_ping_retry_ms = now_ms + self.NF_LINK_PING_RETRY_MS
            return

        if now_ms >= self.nf_next_ping_due_ms:
            self._send_link_ping()
            self.nf_waiting_pong = True
            self.nf_next_ping_retry_ms = now_ms + self.NF_LINK_PING_RETRY_MS

    def _request_nfv3_schema(self, force=False):
        if not self.nf_connected:
            return False

        now_ms = time.time() * 1000.0
        if not force and (now_ms - self.nf_last_schema_request_ms) < self.NF_SCHEMA_RETRY_MS:
            return False

        self.nf_request_id = (self.nf_request_id + 1) & 0xFFFFFFFF
        packet = self.nf_parser.build_schema_request(self.nf_request_id)
        try:
            if not self._send_udp_packet(packet):
                return False
            self.nf_last_schema_request_ms = now_ms
            self.nf_schema_req_sent_count += 1
            print(
                "NF schema req sent: "
                f"schema_req_sent_count={self.nf_schema_req_sent_count} "
                f"last_sync_ok_ts={int(self.nf_last_schema_sync_ok_ms)} "
                f"retry_active={int(self.nf_schema_retry_active)}"
            )
            return True
        except OSError as exc:
            print(f"NF schema request failed: {exc}")
            return False

    def _handle_nfv3_schema_response(self, packet):
        schema_generation = int(packet.get("schema_generation", 0)) & 0xFFFFFFFF
        chunk_total = packet["chunk_total"]
        chunk_index = packet["chunk_index"]

        if chunk_total == 0:
            return

        fresh_transfer = (
            chunk_index == 0
            or self.nf_schema_chunk_generation != schema_generation
            or self.nf_schema_chunk_total != chunk_total
        )
        if fresh_transfer:
            self.nf_schema_chunks = {}
            self.nf_schema_chunk_total = chunk_total
            self.nf_schema_chunk_generation = schema_generation

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
        schema_by_endpoint_no = {}
        self.nf_schema_order = []
        used_names = set()
        ordered_descriptors = []
        for entry in entries:
            endpoint_no = int(entry["endpoint_no"])
            endpoint_kind = int(entry.get("endpoint_kind", 0))
            owner = entry.get("owner") or "Dataflow"
            endpoint_name = entry.get("name") or f"endpoint_{endpoint_no}"
            if endpoint_kind == 1:
                base_name = f"{owner}.input.{endpoint_name}"
                section = f"{owner}/Input"
            elif endpoint_kind == 2:
                base_name = f"{owner}.output.{endpoint_name}"
                section = f"{owner}/Output"
            else:
                base_name = f"Dataflow.{endpoint_name}"
                section = "Dataflow"
            var_name = base_name
            if var_name in used_names:
                var_name = f"{base_name}[{endpoint_no}]"
            used_names.add(var_name)
            desc = {
                "endpoint_no": endpoint_no,
                "endpoint_kind": endpoint_kind,
                "scalar_type": entry["scalar_type"],
                "task_id": entry.get("task_id", 0),
                "owner": owner,
                "name": endpoint_name,
                "unit": entry["unit"],
                "section": section,
                "var_name": var_name,
            }
            schema[endpoint_no] = desc
            schema_by_endpoint_no[endpoint_no] = desc
            self.nf_schema_order.append(desc)
            ordered_descriptors.append(dict(desc))

        self.nf_schema = schema
        self.nf_schema_by_endpoint_no = schema_by_endpoint_no
        self.nf_schema_generation = schema_generation
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.nf_last_schema_sync_ok_ms = time.time() * 1000.0
        if hasattr(self.main_window, "register_dataflow_export_descriptors"):
            self.main_window.register_dataflow_export_descriptors(ordered_descriptors)
        else:
            self.main_window.register_dataflow_export_variables(
                [item["var_name"] for item in ordered_descriptors]
            )
        print(
            "NF schema synced: "
            f"generation={schema_generation} "
            f"count={len(schema)} "
            f"schema_req_sent_count={self.nf_schema_req_sent_count} "
            f"last_sync_ok_ts={int(self.nf_last_schema_sync_ok_ms)}"
        )

    def _process_nfv3_data(self, packet, unix_ts):
        if not self.nf_connected:
            return
        packet_generation = int(packet.get("schema_generation", 0)) & 0xFFFFFFFF
        if not self.nf_schema_by_endpoint_no or self.nf_schema_generation != packet_generation:
            if not self.nf_schema_retry_active:
                self.nf_schema_retry_active = True
                self.nf_next_schema_retry_ms = 0.0
                self.nf_schema_chunks = {}
                self.nf_schema_chunk_total = 0
                self.nf_schema_chunk_generation = None
                self._request_nfv3_schema(force=True)
            return

        if self.nf_last_packet_seq is not None:
            expected_packet_seq = (self.nf_last_packet_seq + 1) & 0xFFFFFFFF
            if packet["packet_seq"] != expected_packet_seq:
                self.nf_packet_gap_count += 1
        self.nf_last_packet_seq = packet["packet_seq"]

        # Offset estimate uses one shared NF clock source. Each variable still keeps
        # its own timestamp queue, but all NF variables share the packet send_us offset.
        build_us = int(packet["build_us"])
        send_timestamp_ms = packet["send_us"] / 1000.0
        for item in packet["items"]:
            endpoint_no = int(item.get("endpoint_no", 0))
            desc = self.nf_schema_by_endpoint_no.get(endpoint_no)
            if desc is None:
                continue
            if int(item.get("status", 0)) != 1:
                continue
            value = self.nf_parser.raw_to_value(desc["scalar_type"], item["raw"])
            if value is None:
                continue

            capture_age_us = int(item.get("capture_age_us", 0)) & 0xFFFFFFFF
            src_us = build_us - capture_age_us if build_us >= capture_age_us else 0
            src_timestamp_ms = src_us / 1000.0
            src = f"{self.NF_SOURCE_PREFIX}{endpoint_no}"
            self.data_model.add_data(
                src,
                unix_ts,
                src_timestamp_ms,
                {desc["var_name"]: value},
                offset_src=self.NF_CLOCK_SOURCE,
                offset_timestamp=send_timestamp_ms,
            )

    def _process_udp_packet(self, data, unix_ts, meta):
        remote_addr = meta.get("remote_addr")
        if remote_addr:
            self.udp_target_ip = remote_addr[0]
            self.udp_target_port = remote_addr[1]

        packet = self.nf_parser.parse_packet(data)
        if packet is None:
            return

        now_ms = time.time() * 1000.0

        if packet["type"] == "connect_ack":
            self.nf_connecting = False
            self.nf_connected = True
            self.nf_waiting_pong = False
            self.nf_last_pong_ms = now_ms
            self.nf_next_ping_due_ms = now_ms + self.NF_LINK_PING_MS
            self.nf_next_ping_retry_ms = 0.0
            self.nf_busy_owner_ip = ""
            self.nf_busy_owner_port = 0
            self.nf_last_error = ""
            self.nf_next_reconnect_ms = 0.0
            self.nf_reconnect_backoff_ms = float(self.NF_RECONNECT_MIN_MS)
            self.nf_disconnect_burst_left = 0
            self.begin_nfv3_schema_sync()
            return

        if packet["type"] == "busy_ack":
            self.nf_connecting = False
            self.nf_connected = False
            self.nf_waiting_pong = False
            self.nf_busy_owner_ip = packet.get("owner_ip", "")
            self.nf_busy_owner_port = int(packet.get("owner_port", 0))
            self.nf_last_error = f"busy by {self.nf_busy_owner_ip}:{self.nf_busy_owner_port}"
            self._schedule_reconnect_(now_ms, busy=True)
            return

        if packet["type"] == "link_pong":
            if self.nf_connected:
                self.nf_last_pong_ms = now_ms
                self.nf_waiting_pong = False
                self.nf_next_ping_due_ms = now_ms + self.NF_LINK_PING_MS
            return

        if packet["type"] == "schema_resp":
            if not self.nf_connected:
                return
            self._handle_nfv3_schema_response(packet)
            return

        if packet["type"] == "data":
            self._process_nfv3_data(packet, unix_ts)

    def process_data(self):
        self._tick_nfv3_connection()
        if self.nf_connected:
            self._tick_nfv3_schema_retry()

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
