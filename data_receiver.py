import socket
import threading
import time
from collections import defaultdict, deque

import numpy as np

from bota_lite import BotaSerialSensor
from data_parser import DataParser
from nfv3_parser import NFv3Parser
from nfv4_clock_client import NFv4ClockClient
from nfv4_codec import NFv4Codec
from network_clock import (
    ClockEstimatorStrategy,
    ClockTransform,
    SelectableClockEstimator,
)
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
    NF_V4_OPEN_RETRY_MS = 500
    NF_V4_OPEN_ATTEMPTS = 3
    NF_RECONNECT_MIN_MS = 500
    NF_RECONNECT_MAX_MS = 5000
    NF_BUSY_RECONNECT_MS = 3000
    NF_DISCONNECT_BURST_COUNT = 3
    NF_DISCONNECT_BURST_INTERVAL_MS = 120
    NF_DIAG_FEEDBACK_IDLE_MS = 1000
    NF_DIAG_FEEDBACK_ACTIVE_MS = 250
    NF_DIAG_TCP_IO_TIMEOUT_S = 0.5
    NF_CLOCK_MODEL_STALE_S = 5.0
    NF_CLOCK_MODEL_UNLOCK_S = 15.0

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
        clock_strategy=ClockEstimatorStrategy.V4_V3,
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
        self._udp_send_lock = threading.Lock()

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
        self.nf_v4_codec = NFv4Codec(self.nf_parser)
        self.nf_clock_estimator = SelectableClockEstimator(clock_strategy)
        self.nf_v4_clock = NFv4ClockClient(
            estimator=self.nf_clock_estimator,
            codec=self.nf_v4_codec,
        )
        self._clock_wall_anchor_us = time.time_ns() // 1000
        self._clock_monotonic_anchor_us = time.monotonic_ns() // 1000
        self._clock_last_published_revision = -1
        self._clock_next_publish_us = 0
        self._clock_strategy_switch_pending = False
        self._clock_strategy_holdover = False
        self.first_ft_received_flag = False
        self.first_udp_received_flag = False
        self.data_ingestion_enabled = True

        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_key = {}
        self.nf_schema_generation = None
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_schema_chunk_entry_total = 0
        self.nf_request_id = 0
        self.nf_last_schema_request_ms = 0.0
        self.nf_schema_req_sent_count = 0
        self.nf_last_schema_sync_ok_ms = 0.0
        self.nf_last_packet_seq = None
        self.nf_packet_gap_count = 0
        self._nf_snapshot_contention_lock = threading.Lock()
        self.nf_snapshot_contention_total = 0
        self.nf_snapshot_contention_by_task = {}
        self.nf_diag_normal_packets_rx = 0
        self.nf_diag_normal_packet_gaps = 0
        self.nf_diag_normal_last_seq = None
        self.nf_diag_probe_test_id = 0
        self.nf_diag_probe_stage = 0
        self.nf_diag_probe_packets_rx = 0
        self.nf_diag_probe_packet_gaps = 0
        self.nf_diag_probe_last_seq = None
        self.nf_diag_probe_max_gap = 0
        self.nf_diag_receiver_errors = 0
        self.nf_v4_aux_datagrams_rx = 0
        self.nf_v4_aux_invalid_packets = 0
        self.nf_v4_aux_wrong_peer = 0
        self.nf_v4_aux_wrong_session = 0
        self.nf_diag_probe_active = False
        self.nf_diag_next_feedback_ms = 0.0
        self.nf_diag_next_capabilities_ms = 0.0
        self.nf_diag_monitor_nonce = time.monotonic_ns() & 0xFFFFFFFF
        self._nf_diag_lock = threading.Lock()
        self._nf_diag_worker_lock = threading.RLock()
        self._nf_diag_socket = None
        self._nf_diag_socket_lock = threading.Lock()
        self._nf_diag_service_thread = None
        self._nf_diag_udp_thread = None
        self._nf_diag_udp_stop = None
        self._nf_diag_tcp_thread = None
        self._nf_diag_tcp_upload_thread = None
        self._nf_diag_tcp_stop = None
        self._nf_diag_tcp_upload_stop = None
        self._nf_diag_tcp_socket = None
        self._nf_diag_tcp_send_lock = threading.Lock()
        self._nf_diag_active_test_id = 0
        self._nf_v4_diag_context = 0
        self._nf_v4_diag_stage = 0xFF
        self._nf_v4_capabilities_sent = False
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.nf_want_connected = False
        self.nf_connected = False
        self.nf_connecting = False
        self.nf_protocol = 0
        self.nf_client_nonce = time.monotonic_ns() & 0xFFFFFFFF
        self.nf_session_id = 0
        self.nf_accepted_features = 0
        self.nf_aux_port = 0
        self.nf_tcp_port = 0
        self.nf_v4_open_attempts = 0
        self.nf_v4_fallback = False
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

    def set_data_ingestion_enabled(self, enabled):
        self.data_ingestion_enabled = bool(enabled)

    def set_clock_estimator_strategy(self, strategy):
        strategy = ClockEstimatorStrategy.parse(strategy)
        if not self.nf_clock_estimator.switch_strategy(strategy):
            return False
        self.nf_v4_clock.restart_estimation_sampling()
        self._clock_last_published_revision = -1
        self._clock_next_publish_us = 0
        self._clock_strategy_switch_pending = bool(self.nf_connected)
        self._clock_strategy_holdover = bool(
            self.data_model.clock_transforms.get(self.NF_CLOCK_SOURCE)
        )
        return True

    def start(self):
        if self.running:
            return
        self.running = True
        self._start_udp()
        self._start_nfv3_diag_service_()
        self._start_bota()
        self._start_mocap()

    def stop(self):
        self.running = False
        self.nf_v4_clock.stop_session()
        self.nf_clock_estimator.close()
        self.bota_running = False
        self.mocap_running = False
        self._stop_nfv3_diag_workers_()
        self._stop_nfv3_diag_service_()

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

        self._clear_nfv3_schema_()
        self._reset_snapshot_contention_()
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
        self.nf_protocol = 0
        self.nf_session_id = 0
        self.nf_accepted_features = 0
        self.nf_aux_port = 0
        self.nf_tcp_port = 0
        self.nf_v4_clock.stop_session()
        self._start_connect_attempt_(now_ms)

    def disconnect_nfv3(self):
        closing_protocol = self.nf_protocol
        if self.nf_protocol == self.nf_v4_codec.VERSION and self.nf_session_id:
            self._send_v4_session_close_()
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
        self.nf_protocol = 0
        self.nf_session_id = 0
        self.nf_v4_clock.stop_session()
        self._stop_nfv3_diag_workers_()
        self.nf_disconnect_burst_left = (
            self.NF_DISCONNECT_BURST_COUNT
            if closing_protocol == self.nf_parser.VERSION
            else 0
        )
        self.nf_next_disconnect_burst_ms = 0.0
        if self.nf_disconnect_burst_left > 0:
            self._send_disconnect_request()
            self.nf_disconnect_burst_left -= 1
            self.nf_next_disconnect_burst_ms = time.time() * 1000.0 + self.NF_DISCONNECT_BURST_INTERVAL_MS

    def _start_connect_attempt_(self, now_ms):
        self.nf_connecting = True
        self.nf_connected = False
        self.nf_connect_start_ms = now_ms
        self.nf_next_connect_req_ms = now_ms + self.NF_V4_OPEN_RETRY_MS
        self.nf_last_connect_req_ms = 0.0
        self.nf_waiting_pong = False
        self.nf_busy_owner_ip = ""
        self.nf_busy_owner_port = 0
        self.nf_protocol = 0
        self.nf_session_id = 0
        self.nf_v4_open_attempts = 0
        self.nf_v4_fallback = False
        self.nf_v4_clock.stop_session()
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
            "protocol_version": int(self.nf_protocol or 0),
            "session_id": int(self.nf_session_id or 0),
            "clock_state": self.nf_clock_estimator.snapshot(
                stale_after_s=self.NF_CLOCK_MODEL_STALE_S
            ).state.value,
            "busy_owner_ip": self.nf_busy_owner_ip,
            "busy_owner_port": int(self.nf_busy_owner_port or 0),
            "last_error": self.nf_last_error,
            "clock": self.get_nfv3_clock_status(),
            "snapshot_contention": self._snapshot_contention_status_(),
        }

    def _reset_snapshot_contention_(self):
        with self._nf_snapshot_contention_lock:
            self.nf_snapshot_contention_total = 0
            self.nf_snapshot_contention_by_task = {}

    def _record_snapshot_contention_(self, task_frames):
        now = time.monotonic()
        with self._nf_snapshot_contention_lock:
            for frame in task_frames:
                task_id = int(frame.get("task_id", 0))
                count = max(0, int(frame.get("snapshot_contention_count", 0)))
                task_schema = self.nf_parser.schema_tasks.get(task_id, {})
                task_name = str(task_schema.get("name", f"Task{task_id}"))
                if count <= 0:
                    entry = self.nf_snapshot_contention_by_task.get(task_id)
                    if entry is not None:
                        entry["consecutive_reports"] = 0
                        entry["likely_phase_lock"] = False
                    continue
                entry = self.nf_snapshot_contention_by_task.setdefault(
                    task_id,
                    {
                        "total": 0,
                        "task_name": task_name,
                        "recent": deque(),
                        "last_monotonic": 0.0,
                        "consecutive_reports": 0,
                        "likely_phase_lock": False,
                    },
                )
                recent = entry["recent"]
                while recent and now - recent[0][0] > 2.0:
                    recent.popleft()
                self.nf_snapshot_contention_total += count
                entry["total"] += count
                entry["last_monotonic"] = now
                entry["consecutive_reports"] += 1
                entry["likely_phase_lock"] = bool(
                    count >= self.nf_parser.TASK_CONTENTION_MASK
                    or entry["consecutive_reports"] >= 3
                )
                recent.append((now, count))

    def _snapshot_contention_status_(self):
        now = time.monotonic()
        tasks = []
        with self._nf_snapshot_contention_lock:
            total = int(self.nf_snapshot_contention_total)
            for task_id, entry in self.nf_snapshot_contention_by_task.items():
                recent = entry["recent"]
                while recent and now - recent[0][0] > 2.0:
                    recent.popleft()
                last_monotonic = float(entry["last_monotonic"])
                tasks.append(
                    {
                        "task_id": int(task_id),
                        "task_name": str(entry["task_name"]),
                        "total": int(entry["total"]),
                        "recent_2s": int(sum(item[1] for item in recent)),
                        "last_seconds_ago": (
                            max(0.0, now - last_monotonic)
                            if last_monotonic > 0.0
                            else None
                        ),
                        "likely_phase_lock": bool(entry["likely_phase_lock"]),
                    }
                )
        tasks.sort(key=lambda item: (-item["total"], item["task_id"]))
        return {"total": total, "tasks": tasks}

    def get_nfv3_clock_status(self):
        snapshot = self.nf_clock_estimator.snapshot(
            stale_after_s=self.NF_CLOCK_MODEL_STALE_S
        )
        client = self.nf_v4_clock.diagnostics()
        with self._nf_diag_socket_lock:
            diag_socket = self._nf_diag_socket
            socket_ready = diag_socket is not None
            try:
                local_endpoint = diag_socket.getsockname() if diag_socket else ("", 0)
            except OSError:
                local_endpoint = ("", 0)
        target = self._diag_target_()
        transport = {
            **client,
            "service_thread_alive": bool(
                self._nf_diag_service_thread
                and self._nf_diag_service_thread.is_alive()
            ),
            "socket_ready": socket_ready,
            "local_ip": str(local_endpoint[0] or ""),
            "local_port": int(local_endpoint[1] or 0),
            "target_ip": str(target[0]) if target else "",
            "target_port": int(target[1]) if target else 0,
        }
        with self._nf_diag_lock:
            transport.update(
                {
                    "aux_datagrams_rx": self.nf_v4_aux_datagrams_rx,
                    "aux_invalid_packets": self.nf_v4_aux_invalid_packets,
                    "aux_wrong_peer": self.nf_v4_aux_wrong_peer,
                    "aux_wrong_session": self.nf_v4_aux_wrong_session,
                }
            )
        blocker = self._clock_alignment_blocker_(snapshot, transport)
        return {
            "strategy": snapshot.strategy.value,
            "strategy_display": snapshot.strategy.display_name,
            "model_name": snapshot.model_name,
            "strategy_switch_pending": self._clock_strategy_switch_pending,
            "strategy_holdover": self._clock_strategy_holdover,
            "state": snapshot.state.value,
            "offset_state": snapshot.offset_state.value,
            "drift_state": snapshot.drift_state.value,
            "usable": snapshot.usable,
            "uncertainty_us": snapshot.uncertainty_us,
            "drift_ppb": snapshot.drift_ppb,
            "candidate_drift_ppb": snapshot.candidate_drift_ppb,
            "physical_candidate_drift_ppb": (
                snapshot.physical_candidate_drift_ppb
            ),
            "statistical_candidate_drift_ppb": (
                snapshot.statistical_candidate_drift_ppb
            ),
            "statistical_drift_uncertainty_ppb": (
                snapshot.statistical_drift_uncertainty_ppb
            ),
            "drift_lower_ppb": snapshot.drift_lower_ppb,
            "drift_upper_ppb": snapshot.drift_upper_ppb,
            "drift_uncertainty_ppb": snapshot.drift_uncertainty_ppb,
            "sample_count": snapshot.sample_count,
            "candidate_count": snapshot.candidate_count,
            "representative_count": snapshot.representative_count,
            "lock_required_representatives": (
                self.nf_clock_estimator.MIN_LOCK_REPRESENTATIVES
            ),
            "sample_span_us": snapshot.sample_span_us,
            "representative_span_us": snapshot.representative_span_us,
            "rejected_count": snapshot.rejected_count,
            "minimum_rtt_us": snapshot.minimum_rtt_us,
            "latest_rtt_us": snapshot.latest_rtt_us,
            "rtt_p50_us": snapshot.rtt_p50_us,
            "rtt_p95_us": snapshot.rtt_p95_us,
            "delay_floor_us": snapshot.delay_floor_us,
            "strict_intersection": snapshot.strict_intersection,
            "consensus_accepted": snapshot.consensus_accepted,
            "compatible_count": snapshot.compatible_count,
            "consensus_required_count": snapshot.consensus_required_count,
            "drift_fit_valid": snapshot.drift_fit_valid,
            "drift_fit_pending": snapshot.drift_fit_pending,
            "drift_fit_runtime_ms": snapshot.drift_fit_runtime_ms,
            "drift_fit_error": snapshot.drift_fit_error,
            "healthy_fit_streak": snapshot.healthy_fit_streak,
            "lock_confirm_updates": snapshot.lock_confirm_updates,
            "model_age_s": snapshot.model_age_s,
            "holdover_age_s": snapshot.holdover_age_s,
            "epoch": snapshot.epoch,
            "reset_count": snapshot.reset_count,
            "last_reset_reason": snapshot.last_reset_reason,
            "blocker": blocker,
            "transport": transport,
            "revision": snapshot.revision,
        }

    def _clock_alignment_blocker_(self, snapshot, transport):
        if self.nf_protocol != self.nf_v4_codec.VERSION or not transport["active"]:
            return "NFv4 clock session is not active"
        if not transport["service_thread_alive"]:
            return "clock UDP service thread is not running"
        if not transport["socket_ready"]:
            return "clock UDP socket is unavailable"
        if transport["requests_due"] == 0:
            return "waiting for the first synchronization request"
        if transport["requests_sent"] == 0:
            return transport["last_failure"] or "synchronization requests cannot be sent"
        if transport["responses_matched"] == 0:
            if transport["responses_seen"] > 0:
                return transport["last_failure"] or "clock responses do not match the session"
            if transport["aux_wrong_session"] > 0:
                return "auxiliary UDP responses use a different session"
            if transport["aux_wrong_peer"] > 0:
                return "auxiliary UDP responses arrived from a different peer"
            if transport["aux_invalid_packets"] > 0:
                return "auxiliary UDP responses are not valid NFv4 packets"
            if transport["aux_datagrams_rx"] > 0:
                return "auxiliary UDP packets arrived without a sync response"
            return (
                "no clock response from "
                f"{transport['target_ip']}:{transport['target_port']}"
            )
        if snapshot.sample_count == 0:
            if transport["samples_rejected"] > 0:
                return "clock responses arrived, but every baseline sample was rejected"
            return "clock responses arrived without a baseline synchronization sample"
        if snapshot.state.value == "Stale":
            return "no reliable baseline clock sample for 5 seconds"
        if snapshot.state.value == "Degraded":
            return "candidate model rejected; holding the last good transform"
        if not snapshot.consensus_accepted:
            return (
                "compatible interval consensus is insufficient "
                f"({snapshot.compatible_count}/{snapshot.consensus_required_count})"
            )
        if snapshot.offset_state.value == "Acquiring":
            return "collecting a compatible offset interval"
        if snapshot.representative_count < self.nf_clock_estimator.MIN_LOCK_REPRESENTATIVES:
            return (
                "collecting representative samples "
                f"({snapshot.representative_count}/"
                f"{self.nf_clock_estimator.MIN_LOCK_REPRESENTATIVES})"
            )
        if snapshot.representative_span_us < self.nf_clock_estimator.MIN_LOCK_SPAN_US:
            return (
                "collecting long-term clock-drift evidence "
                f"({snapshot.representative_span_us / 1.0e6:.1f}/"
                f"{self.nf_clock_estimator.MIN_LOCK_SPAN_US / 1.0e6:.1f} s)"
            )
        if not snapshot.drift_fit_valid:
            return "clock-drift interval is not valid"
        if snapshot.healthy_fit_streak < self.nf_clock_estimator.LOCK_CONFIRM_UPDATES:
            return (
                "confirming the clock model "
                f"({snapshot.healthy_fit_streak}/"
                f"{self.nf_clock_estimator.LOCK_CONFIRM_UPDATES})"
            )
        return ""

    def get_nfv3_clock_metadata(self):
        snapshot = self.nf_clock_estimator.snapshot(
            stale_after_s=self.NF_CLOCK_MODEL_STALE_S
        )
        wall_offset_us = self._clock_wall_anchor_us - self._clock_monotonic_anchor_us
        if snapshot.updated_monotonic > 0.0:
            age_us = max(
                0,
                int((time.monotonic() - snapshot.updated_monotonic) * 1_000_000.0),
            )
            updated_unix_us = time.time_ns() // 1000 - age_us
        else:
            updated_unix_us = ""
        return snapshot.to_metadata(
            target_epoch_offset_us=wall_offset_us,
            updated_unix_us=updated_unix_us,
        )

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
        self._clear_nfv3_schema_()
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

    def _clear_nfv3_schema_(self):
        self.nf_schema = {}
        self.nf_schema_order = []
        self.nf_schema_by_key = {}
        self.nf_schema_generation = None
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_schema_chunk_entry_total = 0
        self.nf_parser.clear_schema()

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

    def _send_udp_packet(self, packet, target=None):
        target_ip = target[0] if target else self.udp_target_ip
        target_port = target[1] if target else self.udp_target_port
        if not self.sock or not target_ip or not target_port:
            return False
        try:
            with self._udp_send_lock:
                self.sock.sendto(packet, (target_ip, int(target_port)))
            return True
        except OSError as exc:
            self.nf_last_error = f"udp send failed: {exc}"
            return False

    def _diag_target_(self):
        if not self.udp_target_ip or not self.udp_target_port:
            return None
        port = int(self.nf_aux_port or self.udp_target_port)
        if port <= 0 or port >= 65535:
            return None
        if self.nf_aux_port:
            return self.udp_target_ip, port
        return self.udp_target_ip, port + 1

    def _send_diag_udp_packet_(self, packet, target=None):
        destination = target or self._diag_target_()
        if not destination:
            return False
        with self._nf_diag_socket_lock:
            diag_socket = self._nf_diag_socket
        if diag_socket is None:
            return False
        try:
            with self._nf_diag_socket_lock:
                if self._nf_diag_socket is not diag_socket:
                    return False
                diag_socket.sendto(
                    packet, (destination[0], int(destination[1]))
                )
            return True
        except OSError as exc:
            self.nf_last_error = f"diagnostic udp send failed: {exc}"
            return False

    def _send_v4_sync_packet_(self, packet):
        destination = self._diag_target_()
        if not destination:
            return 0
        with self._nf_diag_socket_lock:
            diag_socket = self._nf_diag_socket
            if diag_socket is None:
                return 0
            try:
                t1_us = time.monotonic_ns() // 1000
                diag_socket.sendto(packet, (destination[0], int(destination[1])))
                return t1_us
            except OSError as exc:
                self.nf_last_error = f"clock sync send failed: {exc}"
                return 0

    def _start_nfv3_diag_service_(self):
        if self._nf_diag_service_thread and self._nf_diag_service_thread.is_alive():
            return
        diag_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        diag_socket.bind((self.udp_ip, 0))
        diag_socket.settimeout(0.05)
        with self._nf_diag_socket_lock:
            self._nf_diag_socket = diag_socket
        self._nf_diag_service_thread = threading.Thread(
            target=self._run_nfv3_diag_service_,
            daemon=True,
            name="NFv3 diagnostic service",
        )
        self._nf_diag_service_thread.start()

    def _stop_nfv3_diag_service_(self):
        with self._nf_diag_socket_lock:
            diag_socket = self._nf_diag_socket
            self._nf_diag_socket = None
        if diag_socket:
            try:
                diag_socket.close()
            except OSError:
                pass
        thread = self._nf_diag_service_thread
        self._nf_diag_service_thread = None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _run_nfv3_diag_service_(self):
        while self.running:
            with self._nf_diag_socket_lock:
                diag_socket = self._nf_diag_socket
            if diag_socket is None:
                return
            try:
                data, remote_addr = diag_socket.recvfrom(2048)
                self._handle_nfv3_diag_datagram_(data, remote_addr)
            except socket.timeout:
                pass
            except OSError:
                return
            if (
                self.nf_connected
                and self.nf_protocol == self.nf_v4_codec.VERSION
            ):
                with self._nf_diag_lock:
                    context = self._nf_v4_diag_context
                    stage = self._nf_v4_diag_stage
                self.nf_v4_clock.tick(
                    self._send_v4_sync_packet_,
                    context=0,
                )
                if context != 0:
                    self.nf_v4_clock.tick(
                        self._send_v4_sync_packet_,
                        context=context,
                        stage=stage,
                    )
                self._publish_nfv4_clock_transform_()
                self._tick_nfv4_diag_feedback_()
            else:
                self._tick_nfv3_diag_feedback_()
                self._tick_nfv3_clock_model_()

    def _send_connect_request(self):
        if not self.nf_v4_fallback:
            requested_features = self.nf_v4_codec.FEATURE_CLOCK_SYNC
            packet = self.nf_v4_codec.build_session_open(
                self.nf_client_nonce,
                requested_features
                | self.nf_v4_codec.FEATURE_DIAGNOSTICS
                | self.nf_v4_codec.FEATURE_TCP_DIAGNOSTICS,
            )
            self.nf_v4_open_attempts += 1
        else:
            packet = self.nf_parser.build_connect_request()
        if self._send_udp_packet(packet):
            self.nf_last_connect_req_ms = time.time() * 1000.0
            return True
        return False

    def _send_v4_session_close_(self):
        if not self.nf_session_id:
            return False
        return self._send_udp_packet(
            self.nf_v4_codec.build_session_close(self.nf_session_id)
        )

    def _send_link_ping(self):
        packet = self.nf_parser.build_link_ping()
        return self._send_udp_packet(packet)

    def _send_disconnect_request(self):
        packet = self.nf_parser.build_disconnect_request()
        return self._send_udp_packet(packet)

    @staticmethod
    def _advance_sequence_counter(sequence, last_sequence):
        sequence = int(sequence) & 0xFFFFFFFF
        if last_sequence is None:
            return sequence, 0
        forward = (sequence - int(last_sequence)) & 0xFFFFFFFF
        if forward == 0 or forward >= 0x80000000:
            return last_sequence, 0
        return sequence, forward - 1

    def _reset_nfv3_diagnostics_(self, *, reset_clock=True):
        if reset_clock:
            self.nf_clock_estimator.restart_estimation(
                "NFv3 diagnostics restarted"
            )
        with self._nf_diag_lock:
            self.nf_diag_normal_packets_rx = 0
            self.nf_diag_normal_packet_gaps = 0
            self.nf_diag_normal_last_seq = None
            self.nf_diag_probe_test_id = 0
            self.nf_diag_probe_stage = 0
            self.nf_diag_probe_packets_rx = 0
            self.nf_diag_probe_packet_gaps = 0
            self.nf_diag_probe_last_seq = None
            self.nf_diag_probe_max_gap = 0
            self.nf_diag_receiver_errors = 0
            self.nf_v4_aux_datagrams_rx = 0
            self.nf_v4_aux_invalid_packets = 0
            self.nf_v4_aux_wrong_peer = 0
            self.nf_v4_aux_wrong_session = 0
            self.nf_diag_probe_active = False
            self.nf_diag_next_feedback_ms = 0.0
            self.nf_diag_next_capabilities_ms = 0.0
            self._nf_v4_diag_context = 0
            self._nf_v4_diag_stage = 0xFF
            self._nf_v4_capabilities_sent = False

    def _nfv4_diagnostics_enabled_(self):
        return (
            self.nf_connected
            and self.nf_protocol == self.nf_v4_codec.VERSION
            and (
                self.nf_accepted_features
                & self.nf_v4_codec.FEATURE_DIAGNOSTICS
            )
        )

    def _send_nfv4_diag_capabilities_(self, target=None):
        if not self._nfv4_diagnostics_enabled_():
            return False
        packet = self.nf_v4_codec.build_diag_capabilities_report(
            self.nf_session_id,
            self.nf_v4_codec.DIAG_CAPABILITY_ALL,
            1200,
            self.nf_parser.DIAG_TCP_FRAME_SIZE,
            self.nf_diag_monitor_nonce,
        )
        sent = self._send_diag_udp_packet_(packet, target)
        if sent:
            self._nf_v4_capabilities_sent = True
        return sent

    def _send_nfv4_diag_feedback_(
        self,
        stage_complete=False,
        final=False,
        target=None,
    ):
        if not self._nfv4_diagnostics_enabled_():
            return False
        flags = 0
        if stage_complete:
            flags |= self.nf_v4_codec.DIAG_FEEDBACK_STAGE_COMPLETE
        if final:
            flags |= self.nf_v4_codec.DIAG_FEEDBACK_FINAL
        with self._nf_diag_lock:
            packet = self.nf_v4_codec.build_diag_feedback_report(
                self.nf_session_id,
                self.nf_diag_probe_test_id,
                self.nf_diag_probe_stage,
                flags,
                self.nf_diag_normal_packets_rx,
                self.nf_diag_normal_packet_gaps,
                self.nf_diag_probe_packets_rx,
                self.nf_diag_probe_packet_gaps,
                self.nf_diag_probe_last_seq or 0,
                self.nf_diag_probe_max_gap,
                self.nf_diag_receiver_errors,
            )
        return self._send_diag_udp_packet_(packet, target)

    def _tick_nfv4_diag_feedback_(self):
        if not self._nfv4_diagnostics_enabled_():
            return
        if not self._nf_v4_capabilities_sent:
            self._send_nfv4_diag_capabilities_()
        now_ms = time.monotonic() * 1000.0
        with self._nf_diag_lock:
            active = self.nf_diag_probe_active
        if now_ms < self.nf_diag_next_feedback_ms:
            return
        self._send_nfv4_diag_feedback_()
        interval_ms = (
            self.NF_DIAG_FEEDBACK_ACTIVE_MS
            if active
            else self.NF_DIAG_FEEDBACK_IDLE_MS
        )
        self.nf_diag_next_feedback_ms = now_ms + interval_ms

    def _tick_nfv3_clock_model_(self):
        transform = self.nf_clock_estimator.transform
        if not transform.locked or transform.updated_monotonic <= 0.0:
            return
        age_s = time.monotonic() - transform.updated_monotonic
        if age_s < self.NF_CLOCK_MODEL_UNLOCK_S:
            return
        self.nf_clock_estimator.restart_estimation(
            "clock model became stale"
        )

    def _observe_nfv3_data_packet_(self, packet):
        if not self.nf_connected:
            return
        with self._nf_diag_lock:
            self.nf_diag_normal_packets_rx += 1
            self.nf_diag_normal_last_seq, missing = self._advance_sequence_counter(
                packet["packet_seq"], self.nf_diag_normal_last_seq
            )
            self.nf_diag_normal_packet_gaps += missing
            # Preserve the legacy public counters while using exact missing-packet counts.
            self.nf_last_packet_seq = self.nf_diag_normal_last_seq
            self.nf_packet_gap_count = self.nf_diag_normal_packet_gaps

    def _send_nfv3_diag_capabilities_(self, target=None):
        if not self.nf_connected:
            return False
        packet = self.nf_parser.build_diag_capabilities(
            self.nf_parser.DIAG_CAPABILITY_ALL,
            1200,
            self.nf_parser.DIAG_TCP_FRAME_SIZE,
            self.nf_diag_monitor_nonce,
        )
        return self._send_diag_udp_packet_(packet, target)

    def _send_nfv3_diag_feedback_(
        self,
        stage_complete=False,
        final=False,
        target=None,
    ):
        if not self.nf_connected:
            return False
        flags = 0
        if stage_complete:
            flags |= self.nf_parser.DIAG_FEEDBACK_STAGE_COMPLETE
        if final:
            flags |= self.nf_parser.DIAG_FEEDBACK_FINAL
        with self._nf_diag_lock:
            packet = self.nf_parser.build_diag_feedback(
                self.nf_diag_probe_test_id,
                self.nf_diag_probe_stage,
                flags,
                self.nf_diag_normal_packets_rx,
                self.nf_diag_normal_packet_gaps,
                self.nf_diag_probe_packets_rx,
                self.nf_diag_probe_packet_gaps,
                self.nf_diag_probe_last_seq or 0,
                self.nf_diag_probe_max_gap,
                self.nf_diag_receiver_errors,
            )
        return self._send_diag_udp_packet_(packet, target)

    def _tick_nfv3_diag_feedback_(self):
        if not self.nf_connected:
            return
        now_ms = time.monotonic() * 1000.0
        if now_ms >= self.nf_diag_next_capabilities_ms:
            self._send_nfv3_diag_capabilities_()
            self.nf_diag_next_capabilities_ms = now_ms + 5000.0
        if now_ms >= self.nf_diag_next_feedback_ms:
            self._send_nfv3_diag_feedback_()
            with self._nf_diag_lock:
                active = self.nf_diag_probe_active
            interval_ms = (
                self.NF_DIAG_FEEDBACK_ACTIVE_MS
                if active
                else self.NF_DIAG_FEEDBACK_IDLE_MS
            )
            self.nf_diag_next_feedback_ms = now_ms + interval_ms

    def _process_nfv3_diag_probe_(self, packet, target=None):
        if not self.nf_connected:
            return
        test_id = int(packet["test_id"]) & 0xFFFFFFFF
        stage = int(packet["stage"]) & 0xFF
        flags = int(packet["flags"])
        with self._nf_diag_lock:
            if (
                test_id != self.nf_diag_probe_test_id
                or stage != self.nf_diag_probe_stage
            ):
                self.nf_diag_probe_test_id = test_id
                self.nf_diag_probe_stage = stage
                self.nf_diag_probe_packets_rx = 0
                self.nf_diag_probe_packet_gaps = 0
                self.nf_diag_probe_last_seq = None
                self.nf_diag_probe_max_gap = 0

            self.nf_diag_probe_active = True
            self.nf_diag_probe_packets_rx += 1
            self.nf_diag_probe_last_seq, missing = self._advance_sequence_counter(
                packet["probe_seq"], self.nf_diag_probe_last_seq
            )
            self.nf_diag_probe_packet_gaps += missing
            self.nf_diag_probe_max_gap = max(self.nf_diag_probe_max_gap, missing)

        if flags & self.nf_parser.DIAG_PROBE_STAGE_END:
            final = bool(flags & self.nf_parser.DIAG_PROBE_TEST_END)
            self._send_nfv3_diag_feedback_(
                stage_complete=True,
                final=final,
                target=target,
            )
            self.nf_diag_next_feedback_ms = (
                time.monotonic() * 1000.0 + self.NF_DIAG_FEEDBACK_ACTIVE_MS
            )
            with self._nf_diag_lock:
                self.nf_diag_probe_active = False

    def _is_nfv3_diag_peer_(self, remote_addr):
        if not self.nf_connected or not remote_addr:
            return False
        if self.udp_target_ip and remote_addr[0] != self.udp_target_ip:
            return False
        target = self._diag_target_()
        if target and int(remote_addr[1]) != int(target[1]):
            return False
        return True

    def _handle_nfv3_diag_datagram_(self, data, remote_addr):
        received_us = time.monotonic_ns() // 1000
        if self.nf_v4_codec.peek_header(data) is not None:
            return self._handle_nfv4_aux_datagram_(
                data, remote_addr, received_us
            )
        packet_type = self.nf_parser.peek_packet_type(data)
        diagnostic_types = {
            self.nf_parser.TYPE_DIAG_FEEDBACK,
            self.nf_parser.TYPE_DIAG_PROBE,
            self.nf_parser.TYPE_DIAG_CAPABILITIES,
            self.nf_parser.TYPE_DIAG_ECHO_REQUEST,
            self.nf_parser.TYPE_DIAG_ECHO_RESPONSE,
            self.nf_parser.TYPE_DIAG_CONTROL,
            self.nf_parser.TYPE_DIAG_CLOCK_SAMPLE,
        }
        if packet_type not in diagnostic_types:
            return False
        if not self._is_nfv3_diag_peer_(remote_addr):
            return True

        packet = self.nf_parser.parse_packet(data)
        if packet is None:
            with self._nf_diag_lock:
                self.nf_diag_receiver_errors += 1
            return True

        if packet["type"] == "diag_echo_request":
            response_started_us = time.monotonic_ns() // 1000
            response = self.nf_parser.build_diag_echo_response(
                packet["test_id"],
                packet["sequence"],
                packet["t1_us"],
                received_us,
                response_started_us,
                packet["flags"],
            )
            self._send_diag_udp_packet_(response, remote_addr)
        elif packet["type"] == "diag_probe":
            self._process_nfv3_diag_probe_(packet, remote_addr)
        elif packet["type"] == "diag_control":
            self._process_nfv3_diag_control_(packet, remote_addr)
        elif packet["type"] == "diag_clock_sample":
            self._process_nfv3_clock_sample_(packet, remote_addr)
        return True

    def _handle_nfv4_aux_datagram_(self, data, remote_addr, received_us):
        with self._nf_diag_lock:
            self.nf_v4_aux_datagrams_rx += 1
        if (
            not self.nf_connected
            or self.nf_protocol != self.nf_v4_codec.VERSION
            or not remote_addr
            or (
                self.udp_target_ip
                and str(remote_addr[0]) != str(self.udp_target_ip)
            )
        ):
            with self._nf_diag_lock:
                self.nf_v4_aux_wrong_peer += 1
            return False
        packet = self.nf_v4_codec.parse_aux_packet(data)
        if packet is None:
            with self._nf_diag_lock:
                self.nf_v4_aux_invalid_packets += 1
            return False
        if int(packet.get("session_id", 0)) != self.nf_session_id:
            with self._nf_diag_lock:
                self.nf_v4_aux_wrong_session += 1
            return False
        if packet["type"] == "sync_response":
            matched = self.nf_v4_clock.handle_response(data, received_us)
            if matched:
                self._sync_nfv4_clock_epoch_()
                self.nf_last_pong_ms = time.time() * 1000.0
                measurement = self.nf_v4_clock.take_measurement()
                if measurement and int(measurement["context"]) != 0:
                    self._send_nfv4_loaded_path_report_(
                        measurement,
                        remote_addr,
                    )
                else:
                    self._publish_nfv4_clock_transform_(force=False)
            return True
        if not self._nfv4_diagnostics_enabled_():
            return True
        if packet["type"] == "diag_probe":
            self._process_nfv4_diag_probe_(packet, remote_addr)
            return True
        if packet["type"] == "diag_command":
            self._process_nfv4_diag_control_(packet, remote_addr)
            return True
        return True

    def _sync_nfv4_clock_epoch_(self):
        clock_bucket = self.data_model.ensure_source(self.NF_CLOCK_SOURCE)
        if clock_bucket.current_session == self.nf_clock_estimator.epoch:
            return
        self.data_model.begin_clock_epoch(
            self.NF_CLOCK_SOURCE,
            self.nf_clock_estimator.epoch,
        )

    def _publish_nfv4_clock_transform_(self, force=False):
        now_us = time.monotonic_ns() // 1000
        transform = self.nf_clock_estimator.transform
        if not (transform.usable or transform.locked):
            return
        if (
            not force
            and transform.revision == self._clock_last_published_revision
        ):
            return
        if not force and now_us < self._clock_next_publish_us:
            return
        wall_offset_us = (
            self._clock_wall_anchor_us - self._clock_monotonic_anchor_us
        )
        wall_transform = ClockTransform(
            source_anchor_us=transform.source_anchor_us,
            target_anchor_us=transform.target_anchor_us + wall_offset_us,
            drift_ppb=transform.drift_ppb,
            uncertainty_us=transform.uncertainty_us,
            usable=transform.usable,
            locked=transform.locked,
            epoch=transform.epoch,
            revision=transform.revision,
            updated_monotonic=transform.updated_monotonic,
        )
        self.data_model.set_clock_transform(
            self.NF_CLOCK_SOURCE, wall_transform
        )
        self._clock_strategy_switch_pending = False
        self._clock_strategy_holdover = False
        if self._nfv4_diagnostics_enabled_():
            packet = self.nf_v4_codec.build_diag_path_report(
                self.nf_session_id,
                transform,
                self.nf_clock_estimator.path_stats(),
            )
            self._send_diag_udp_packet_(packet)
        self._clock_last_published_revision = transform.revision
        self._clock_next_publish_us = now_us + 1_000_000

    @staticmethod
    def _single_path_stats_(value):
        value = max(0, int(value))
        return {
            "samples": 1,
            "latest": value,
            "min": value,
            "p50": value,
            "p95": value,
        }

    def _send_nfv4_loaded_path_report_(self, measurement, target=None):
        if not self._nfv4_diagnostics_enabled_():
            return False
        transform = self.nf_clock_estimator.transform
        if not (transform.usable or transform.locked):
            return False
        if not measurement.get("one_way_valid"):
            return False
        stats = {
            "upload": self._single_path_stats_(
                measurement.get("upload_us", 0)
            ),
            "download": self._single_path_stats_(
                measurement.get("download_us", 0)
            ),
            "rtt": self._single_path_stats_(
                measurement.get("rtt_us", 0)
            ),
        }
        packet = self.nf_v4_codec.build_diag_path_report(
            self.nf_session_id,
            transform,
            stats,
            test_id=measurement.get("context", 0),
            stage=measurement.get("stage", 0xFF),
        )
        return self._send_diag_udp_packet_(packet, target)

    def _process_nfv4_diag_probe_(self, packet, target=None):
        test_id = int(packet["test_id"]) & 0xFFFFFFFF
        stage = int(packet["stage"]) & 0xFF
        flags = int(packet["flags"])
        with self._nf_diag_lock:
            if (
                test_id != self.nf_diag_probe_test_id
                or stage != self.nf_diag_probe_stage
            ):
                self.nf_diag_probe_test_id = test_id
                self.nf_diag_probe_stage = stage
                self.nf_diag_probe_packets_rx = 0
                self.nf_diag_probe_packet_gaps = 0
                self.nf_diag_probe_last_seq = None
                self.nf_diag_probe_max_gap = 0
            self._nf_v4_diag_context = test_id
            self._nf_v4_diag_stage = stage
            self.nf_diag_probe_active = True
            self.nf_diag_probe_packets_rx += 1
            self.nf_diag_probe_last_seq, missing = self._advance_sequence_counter(
                packet["probe_seq"], self.nf_diag_probe_last_seq
            )
            self.nf_diag_probe_packet_gaps += missing
            self.nf_diag_probe_max_gap = max(
                self.nf_diag_probe_max_gap, missing
            )

        if flags & self.nf_v4_codec.DIAG_PROBE_STAGE_END:
            final = bool(flags & self.nf_v4_codec.DIAG_PROBE_TEST_END)
            self._send_nfv4_diag_feedback_(
                stage_complete=True,
                final=final,
                target=target,
            )
            with self._nf_diag_lock:
                self.nf_diag_probe_active = False

    def _process_nfv4_diag_control_(self, packet, remote_addr):
        action = int(packet["action"])
        test_id = int(packet["test_id"]) & 0xFFFFFFFF
        with self._nf_diag_lock:
            self._nf_v4_diag_context = test_id
            self._nf_v4_diag_stage = int(packet["stage"]) & 0xFF

        if action == self.nf_v4_codec.DIAG_CONTROL_TEST_BEGIN:
            if test_id != self._nf_diag_active_test_id:
                self._stop_nfv3_diag_workers_()
            else:
                self._stop_nfv3_udp_worker_()
            self._nf_diag_active_test_id = test_id
            return
        if action == self.nf_v4_codec.DIAG_CONTROL_UDP_UPLOAD_START:
            self._nf_diag_active_test_id = test_id
            self._start_nfv3_udp_upload_(packet, remote_addr)
            return
        if action == self.nf_v4_codec.DIAG_CONTROL_TCP_CONNECT:
            self._nf_diag_active_test_id = test_id
            self._start_nfv3_tcp_session_(packet, remote_addr)
            return
        if action == self.nf_v4_codec.DIAG_CONTROL_TCP_UPLOAD_START:
            self._start_nfv3_tcp_upload_(packet)
            return
        if action in (
            self.nf_v4_codec.DIAG_CONTROL_TEST_END,
            self.nf_v4_codec.DIAG_CONTROL_CANCEL,
        ):
            self._stop_nfv3_diag_workers_()
            self._nf_diag_active_test_id = 0
            with self._nf_diag_lock:
                self._nf_v4_diag_context = 0
                self._nf_v4_diag_stage = 0xFF

    def _process_nfv3_clock_sample_(self, packet, remote_addr):
        # Loaded samples are useful for pressure-test latency reporting, but
        # must not move the baseline clock model.
        if int(packet.get("test_id", 0)) != 0:
            return
        if not self.nf_clock_estimator.add(
            packet["t1_us"],
            packet["t2_us"],
            packet["t3_us"],
            packet["t4_us"],
        ):
            return
        transform = self.nf_clock_estimator.transform
        wall_offset_us = self._clock_wall_anchor_us - self._clock_monotonic_anchor_us
        wall_transform = ClockTransform(
            source_anchor_us=transform.source_anchor_us,
            target_anchor_us=transform.target_anchor_us + wall_offset_us,
            drift_ppb=transform.drift_ppb,
            uncertainty_us=transform.uncertainty_us,
            usable=transform.usable,
            locked=transform.locked,
            epoch=transform.epoch,
            revision=transform.revision,
            updated_monotonic=transform.updated_monotonic,
        )
        if wall_transform.usable or wall_transform.locked:
            self.data_model.set_clock_transform(
                self.NF_CLOCK_SOURCE, wall_transform
            )
        else:
            self.data_model.set_clock_transform(self.NF_CLOCK_SOURCE, None)
        model_packet = self.nf_parser.build_diag_clock_model(
            transform, self.nf_clock_estimator.path_stats()
        )
        self._send_diag_udp_packet_(model_packet, remote_addr)

    def _process_nfv3_diag_control_(self, packet, remote_addr):
        action = int(packet["action"])
        test_id = int(packet["test_id"]) & 0xFFFFFFFF
        if action == self.nf_parser.DIAG_CONTROL_TEST_BEGIN:
            if test_id != self._nf_diag_active_test_id:
                self._stop_nfv3_diag_workers_()
            else:
                self._stop_nfv3_udp_worker_()
            self._nf_diag_active_test_id = test_id
            return
        if action == self.nf_parser.DIAG_CONTROL_UDP_UPLOAD_START:
            self._nf_diag_active_test_id = test_id
            self._start_nfv3_udp_upload_(packet, remote_addr)
            return
        if action == self.nf_parser.DIAG_CONTROL_TCP_CONNECT:
            self._nf_diag_active_test_id = test_id
            self._start_nfv3_tcp_session_(packet, remote_addr)
            return
        if action == self.nf_parser.DIAG_CONTROL_TCP_UPLOAD_START:
            self._start_nfv3_tcp_upload_(packet)
            return
        if action in (
            self.nf_parser.DIAG_CONTROL_TEST_END,
            self.nf_parser.DIAG_CONTROL_CANCEL,
        ):
            self._stop_nfv3_diag_workers_()
            self._nf_diag_active_test_id = 0

    def _start_nfv3_udp_upload_(self, control, remote_addr):
        self._stop_nfv3_udp_worker_()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_nfv3_udp_upload_,
            args=(dict(control), tuple(remote_addr), stop_event),
            daemon=True,
            name="NFv3 UDP diagnostic upload",
        )
        with self._nf_diag_worker_lock:
            self._nf_diag_udp_stop = stop_event
            self._nf_diag_udp_thread = thread
        thread.start()

    def _run_nfv3_udp_upload_(self, control, remote_addr, stop_event):
        target_pps = max(1, int(control["target_pps"]))
        duration_ms = max(1, int(control["duration_ms"]))
        wire_version = int(control.get("wire_version", self.nf_parser.VERSION))
        header_size = (
            self.nf_v4_codec.DIAG_PROBE_HEADER_SIZE
            if wire_version == self.nf_v4_codec.VERSION
            else self.nf_parser.DIAG_PROBE_HEADER_SIZE
        )
        packet_size = min(
            1200,
            max(header_size, int(control["payload_bytes"])),
        )
        total_packets = max(1, target_pps * duration_ms // 1000)
        interval_ns = 1_000_000_000 // target_pps
        started_ns = time.monotonic_ns()

        for sequence in range(total_packets):
            if stop_event.is_set() or not self.running:
                break
            deadline_ns = started_ns + sequence * interval_ns
            remaining_ns = deadline_ns - time.monotonic_ns()
            if remaining_ns > 0:
                stop_event.wait(remaining_ns / 1_000_000_000.0)
            if stop_event.is_set() or not self.running:
                break
            flags = self.nf_v4_codec.DIAG_PROBE_MONITOR_TO_FIRMWARE
            if sequence == 0:
                flags |= self.nf_v4_codec.DIAG_PROBE_STAGE_START
            if sequence + 1 == total_packets:
                flags |= self.nf_v4_codec.DIAG_PROBE_STAGE_END
            if wire_version == self.nf_v4_codec.VERSION:
                packet = self.nf_v4_codec.build_diag_probe(
                    self.nf_session_id,
                    control["test_id"],
                    control["stage"],
                    flags,
                    packet_size,
                    sequence,
                    time.monotonic_ns() // 1000,
                    target_pps,
                )
            else:
                packet = self.nf_parser.build_diag_probe(
                    control["test_id"],
                    control["stage"],
                    flags,
                    packet_size,
                    sequence,
                    time.monotonic_ns() // 1000,
                    target_pps,
                )
            if not self._send_diag_udp_packet_(packet, remote_addr):
                with self._nf_diag_lock:
                    self.nf_diag_receiver_errors += 1

        with self._nf_diag_worker_lock:
            if self._nf_diag_udp_stop is stop_event:
                self._nf_diag_udp_stop = None
                self._nf_diag_udp_thread = None

    def _stop_nfv3_udp_worker_(self):
        with self._nf_diag_worker_lock:
            stop_event = self._nf_diag_udp_stop
            self._nf_diag_udp_stop = None
            self._nf_diag_udp_thread = None
        if stop_event:
            stop_event.set()

    def _start_nfv3_tcp_session_(self, control, remote_addr):
        self._stop_nfv3_tcp_worker_()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_nfv3_tcp_session_,
            args=(dict(control), remote_addr[0], stop_event),
            daemon=True,
            name="NFv3 TCP diagnostic session",
        )
        with self._nf_diag_worker_lock:
            self._nf_diag_tcp_stop = stop_event
            self._nf_diag_tcp_thread = thread
        thread.start()

    def _run_nfv3_tcp_session_(self, control, host, stop_event):
        tcp_socket = None
        try:
            tcp_socket = socket.create_connection(
                (host, int(control["tcp_port"])),
                timeout=3.0,
            )
            tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # A short timeout is useful for the receive loop, but 50 ms also
            # made the pressure-test sender abort during ordinary ESP32
            # scheduling stalls. Keep cancellation responsive without turning
            # a transient full TCP window into an artificial throughput limit.
            tcp_socket.settimeout(self.NF_DIAG_TCP_IO_TIMEOUT_S)
            with self._nf_diag_worker_lock:
                if stop_event.is_set():
                    return
                self._nf_diag_tcp_socket = tcp_socket

            rx_buffer = bytearray()
            while self.running and not stop_event.is_set():
                try:
                    chunk = tcp_socket.recv(4096)
                    if not chunk:
                        break
                    rx_buffer.extend(chunk)
                except socket.timeout:
                    continue
                except OSError:
                    break

                consumed = 0
                while (
                    len(rx_buffer) - consumed
                    >= self.nf_parser.DIAG_TCP_FRAME_SIZE
                ):
                    received_us = time.monotonic_ns() // 1000
                    frame_end = consumed + self.nf_parser.DIAG_TCP_FRAME_SIZE
                    frame_bytes = bytes(rx_buffer[consumed:frame_end])
                    consumed = frame_end
                    frame = self.nf_parser.parse_diag_tcp_frame(frame_bytes)
                    if frame is None:
                        with self._nf_diag_lock:
                            self.nf_diag_receiver_errors += 1
                        continue
                    if (
                        frame["test_id"] == int(control["test_id"])
                        and frame["kind"] == self.nf_parser.DIAG_TCP_PING
                    ):
                        response_started_us = time.monotonic_ns() // 1000
                        pong = self.nf_parser.build_diag_tcp_frame(
                            frame["test_id"],
                            self.nf_parser.DIAG_TCP_PONG,
                            frame["stage"],
                            frame["sequence"],
                            frame["t1_us"],
                            received_us,
                            response_started_us,
                        )
                        self._send_nfv3_tcp_bytes_(tcp_socket, pong)
                if consumed:
                    del rx_buffer[:consumed]
        except OSError as exc:
            if not stop_event.is_set():
                self.nf_last_error = f"diagnostic TCP connect failed: {exc}"
                with self._nf_diag_lock:
                    self.nf_diag_receiver_errors += 1
        finally:
            with self._nf_diag_worker_lock:
                if self._nf_diag_tcp_socket is tcp_socket:
                    self._nf_diag_tcp_socket = None
                if self._nf_diag_tcp_stop is stop_event:
                    self._nf_diag_tcp_stop = None
                    self._nf_diag_tcp_thread = None
            if tcp_socket:
                try:
                    tcp_socket.close()
                except OSError:
                    pass

    def _send_nfv3_tcp_bytes_(self, tcp_socket, data):
        try:
            with self._nf_diag_tcp_send_lock:
                tcp_socket.sendall(data)
            return True
        except (OSError, socket.timeout):
            return False

    def _start_nfv3_tcp_upload_(self, control):
        self._stop_nfv3_tcp_upload_worker_()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_nfv3_tcp_upload_,
            args=(dict(control), stop_event),
            daemon=True,
            name="NFv3 TCP diagnostic upload",
        )
        with self._nf_diag_worker_lock:
            self._nf_diag_tcp_upload_stop = stop_event
            self._nf_diag_tcp_upload_thread = thread
        thread.start()

    def _run_nfv3_tcp_upload_(self, control, stop_event):
        deadline = time.monotonic() + max(1, int(control["duration_ms"])) / 1000.0
        sequence = 0
        while self.running and not stop_event.is_set() and time.monotonic() < deadline:
            with self._nf_diag_worker_lock:
                tcp_socket = self._nf_diag_tcp_socket
            if tcp_socket is None:
                stop_event.wait(0.01)
                continue
            frame = self.nf_parser.build_diag_tcp_frame(
                control["test_id"],
                self.nf_parser.DIAG_TCP_UPLOAD_DATA,
                control["stage"],
                sequence,
                time.monotonic_ns() // 1000,
            )
            if not self._send_nfv3_tcp_bytes_(tcp_socket, frame):
                break
            sequence = (sequence + 1) & 0xFFFFFFFF

        with self._nf_diag_worker_lock:
            if self._nf_diag_tcp_upload_stop is stop_event:
                self._nf_diag_tcp_upload_stop = None
                self._nf_diag_tcp_upload_thread = None

    def _stop_nfv3_tcp_upload_worker_(self):
        with self._nf_diag_worker_lock:
            stop_event = self._nf_diag_tcp_upload_stop
            self._nf_diag_tcp_upload_stop = None
            self._nf_diag_tcp_upload_thread = None
        if stop_event:
            stop_event.set()

    def _stop_nfv3_tcp_worker_(self):
        self._stop_nfv3_tcp_upload_worker_()
        with self._nf_diag_worker_lock:
            stop_event = self._nf_diag_tcp_stop
            tcp_socket = self._nf_diag_tcp_socket
            self._nf_diag_tcp_stop = None
            self._nf_diag_tcp_thread = None
            self._nf_diag_tcp_socket = None
        if stop_event:
            stop_event.set()
        if tcp_socket:
            try:
                tcp_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                tcp_socket.close()
            except OSError:
                pass

    def _stop_nfv3_diag_workers_(self):
        self._stop_nfv3_udp_worker_()
        self._stop_nfv3_tcp_worker_()

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
                if (
                    not self.nf_v4_fallback
                    and self.nf_v4_open_attempts >= self.NF_V4_OPEN_ATTEMPTS
                ):
                    self.nf_v4_fallback = True
                self._send_connect_request()
                self.nf_next_connect_req_ms = now_ms + (
                    self.NF_CONNECT_RETRY_MS
                    if self.nf_v4_fallback
                    else self.NF_V4_OPEN_RETRY_MS
                )
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

        if self.nf_protocol == self.nf_v4_codec.VERSION:
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
        packet = (
            self.nf_v4_codec.build_schema_request(self.nf_request_id)
            if self.nf_protocol == self.nf_v4_codec.VERSION
            else self.nf_parser.build_schema_request(self.nf_request_id)
        )
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
        chunk_total = int(packet["chunk_total"])
        chunk_index = int(packet["chunk_index"])
        total_entries = int(packet.get("total_entries", 0))

        if chunk_total == 0 or total_entries == 0:
            return

        fresh_transfer = (
            self.nf_schema_chunk_generation != schema_generation
            or self.nf_schema_chunk_total != chunk_total
            or self.nf_schema_chunk_entry_total != total_entries
        )
        if fresh_transfer:
            self.nf_schema_chunks = {}
            self.nf_schema_chunk_total = chunk_total
            self.nf_schema_chunk_generation = schema_generation
            self.nf_schema_chunk_entry_total = total_entries

        self.nf_schema_chunks[chunk_index] = packet["entries"]
        if len(self.nf_schema_chunks) != self.nf_schema_chunk_total:
            return

        entries = []
        for chunk_index in range(self.nf_schema_chunk_total):
            chunk_entries = self.nf_schema_chunks.get(chunk_index)
            if chunk_entries is None:
                return
            entries.extend(chunk_entries)

        if len(entries) != self.nf_schema_chunk_entry_total:
            self.nf_schema_chunks = {}
            return
        if not self.nf_parser.install_schema(schema_generation, entries):
            self.nf_schema_chunks = {}
            return

        schema = {}
        schema_by_key = {}
        self.nf_schema_order = []
        used_names = set()
        ordered_descriptors = []
        task_order_by_id = {}
        dataflow_group_order = {}

        def add_descriptor(key, desc, base_name, suffix):
            var_name = base_name
            if var_name in used_names:
                var_name = f"{base_name}[{suffix}]"
            used_names.add(var_name)
            desc["var_name"] = var_name
            schema[key] = desc
            schema_by_key[key] = desc
            self.nf_schema_order.append(desc)
            ordered_descriptors.append(dict(desc))

        for entry in entries:
            if int(entry.get("entry_kind", 0)) != self.nf_parser.SCHEMA_KIND_TASK:
                continue
            task_id = int(entry["task_id"])
            owner = entry.get("name") or f"Task{task_id}"
            task_order = len(task_order_by_id)
            task_order_by_id[task_id] = task_order
            add_descriptor(
                ("task_latency", task_id),
                {
                    "descriptor_kind": "task_latency",
                    "category": "task",
                    "task_id": task_id,
                    "task_order": task_order,
                    "owner": owner,
                    "name": "latency_us",
                    "display_name": "latency_us",
                    "unit": "us",
                    "section": f"Task/{task_id}",
                    "source": f"{self.NF_SOURCE_PREFIX}task:{task_id}:latency",
                    "hidden_control": True,
                },
                f"{owner}.latency_us",
                task_id,
            )

        for entry in entries:
            entry_kind = int(entry.get("entry_kind", 0))
            if entry_kind == self.nf_parser.SCHEMA_KIND_TASK:
                continue

            if entry_kind == self.nf_parser.SCHEMA_KIND_TASK_PORT:
                task_id = int(entry["task_id"])
                direction = int(entry["direction"])
                slot = int(entry["slot"])
                task = self.nf_parser.schema_tasks.get(task_id, {})
                owner = task.get("name") or f"Task{task_id}"
                endpoint_name = entry.get("name") or f"port_{slot}"
                if direction == self.nf_parser.PORT_INPUT:
                    direction_name = "input"
                else:
                    direction_name = "output"
                key = ("task", task_id, direction, slot)
                base_name = f"{owner}.{direction_name}.{endpoint_name}"
                source = f"{self.NF_SOURCE_PREFIX}task:{task_id}:{direction}:{slot}"
                desc = {
                    "entry_kind": entry_kind,
                    "descriptor_kind": "task_port",
                    "category": "task",
                    "task_id": task_id,
                    "task_order": task_order_by_id.get(task_id, task_id),
                    "direction": direction,
                    "slot": slot,
                    "scalar_type": int(entry["scalar_type"]),
                    "timestamp_group": int(entry["timestamp_group"]),
                    "owner": owner,
                    "name": endpoint_name,
                    "display_name": endpoint_name,
                    "unit": entry.get("unit", ""),
                    "section": f"Task/{task_id}",
                    "source": source,
                }
            elif entry_kind == self.nf_parser.SCHEMA_KIND_DATA_NODE:
                node_no = int(entry["node_no"])
                group = entry.get("group") or "Dataflow"
                if group not in dataflow_group_order:
                    dataflow_group_order[group] = len(dataflow_group_order)
                endpoint_name = entry.get("name") or f"node_{node_no}"
                key = ("node", node_no)
                base_name = f"Dataflow.{endpoint_name}"
                source = f"{self.NF_SOURCE_PREFIX}node:{node_no}"
                desc = {
                    "entry_kind": entry_kind,
                    "descriptor_kind": "data_node",
                    "category": "dataflow",
                    "group": group,
                    "group_order": dataflow_group_order[group],
                    "node_no": node_no,
                    "node_id": int(entry["node_id"]),
                    "scalar_type": int(entry["scalar_type"]),
                    "owner": "Dataflow",
                    "name": endpoint_name,
                    "display_name": endpoint_name,
                    "unit": entry.get("unit", ""),
                    "section": f"Dataflow/{group}",
                    "source": source,
                }
            else:
                continue

            suffix = desc.get("node_no", desc.get("slot", 0))
            add_descriptor(key, desc, base_name, suffix)

        self.nf_schema = schema
        self.nf_schema_by_key = schema_by_key
        self.nf_schema_generation = schema_generation
        self.nf_schema_chunks = {}
        self.nf_schema_chunk_total = 0
        self.nf_schema_chunk_generation = None
        self.nf_schema_chunk_entry_total = 0
        self.nf_schema_retry_active = False
        self.nf_next_schema_retry_ms = 0.0
        self.nf_last_schema_sync_ok_ms = time.time() * 1000.0
        if hasattr(self.main_window, "activate_live_dataflow_export_descriptors"):
            activated = self.main_window.activate_live_dataflow_export_descriptors(
                ordered_descriptors,
                self.udp_target_ip,
                self.udp_target_port,
            )
            if activated:
                self.set_data_ingestion_enabled(True)
        elif hasattr(self.main_window, "register_dataflow_export_descriptors"):
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
        if (
            not packet.get("schema_available", False)
            or self.nf_schema_generation != packet_generation
        ):
            if not self.nf_schema_retry_active:
                self.nf_schema_retry_active = True
                self.nf_next_schema_retry_ms = 0.0
                self.nf_schema_chunks = {}
                self.nf_schema_chunk_total = 0
                self.nf_schema_chunk_generation = None
                self.nf_schema_chunk_entry_total = 0
                self._request_nfv3_schema(force=True)
            return

        self._record_snapshot_contention_(packet.get("task_frames", ()))

        if not self.data_ingestion_enabled:
            return

        packet_time_us = int(packet["packet_time_us"])
        packet_timestamp_ms = packet_time_us / 1000.0

        def publish(key, raw, capture_age_us):
            desc = self.nf_schema_by_key.get(key)
            if desc is None:
                return
            capture_age_us = int(capture_age_us) & 0xFFFFFFFF
            if capture_age_us == self.nf_parser.INVALID_AGE_US:
                return
            value = self.nf_parser.raw_to_value(desc["scalar_type"], raw)
            if value is None:
                return
            src_us = packet_time_us - capture_age_us if packet_time_us >= capture_age_us else 0
            self.data_model.add_data(
                desc["source"],
                unix_ts,
                src_us / 1000.0,
                {desc["var_name"]: value},
                offset_src=self.NF_CLOCK_SOURCE,
                offset_timestamp=packet_timestamp_ms,
            )

        def publish_latency(task_id, input_age_us, output_age_us):
            desc = self.nf_schema_by_key.get(("task_latency", task_id))
            if desc is None:
                return
            input_age_us = int(input_age_us) & 0xFFFFFFFF
            output_age_us = int(output_age_us) & 0xFFFFFFFF
            if (
                input_age_us == self.nf_parser.INVALID_AGE_US
                or output_age_us == self.nf_parser.INVALID_AGE_US
                or input_age_us < output_age_us
                or packet_time_us < input_age_us
            ):
                return
            latency_us = input_age_us - output_age_us
            input_time_us = packet_time_us - input_age_us
            self.data_model.add_data(
                desc["source"],
                unix_ts,
                input_time_us / 1000.0,
                {desc["var_name"]: float(latency_us)},
                offset_src=self.NF_CLOCK_SOURCE,
                offset_timestamp=packet_timestamp_ms,
            )
            if hasattr(self.main_window, "update_task_latency"):
                self.main_window.update_task_latency(task_id, latency_us)

        for frame in packet["task_frames"]:
            task_id = int(frame["task_id"])
            flags = int(frame["flags"])
            publish_latency(task_id, frame["input_age_us"], frame["output_age_us"])
            if flags & self.nf_parser.TASK_FLAG_INPUTS_VALID:
                for item in frame["inputs"]:
                    publish(
                        ("task", task_id, self.nf_parser.PORT_INPUT, int(item["slot"])),
                        item["raw"],
                        item["capture_age_us"],
                    )
            if flags & self.nf_parser.TASK_FLAG_OUTPUTS_VALID:
                for item in frame["outputs"]:
                    publish(
                        ("task", task_id, self.nf_parser.PORT_OUTPUT, int(item["slot"])),
                        item["raw"],
                        item["capture_age_us"],
                    )

        for frame in packet["node_frames"]:
            if int(frame.get("status", 0)) != 1:
                continue
            publish(("node", int(frame["node_no"])), frame["raw"], frame["publish_age_us"])

    def _process_udp_packet(self, data, unix_ts, meta):
        remote_addr = meta.get("remote_addr")
        if remote_addr:
            self.udp_target_ip = remote_addr[0]
            self.udp_target_port = remote_addr[1]

        wire_version = data[2] if len(data) >= 3 else 0
        if wire_version == self.nf_v4_codec.VERSION:
            packet = self.nf_v4_codec.parse_base_packet(data)
        else:
            packet = self.nf_parser.parse_packet(data)
        if packet is None:
            return

        now_ms = time.time() * 1000.0

        if packet["type"] == "session_accept":
            if (
                int(packet.get("client_nonce", 0))
                != int(self.nf_client_nonce)
            ):
                return
            accepted_features = int(packet.get("accepted_features", 0))
            if not (
                accepted_features
                & self.nf_v4_codec.FEATURE_CLOCK_SYNC
            ):
                self.nf_last_error = "NFv4 clock sync feature unavailable"
                return
            self.nf_protocol = self.nf_v4_codec.VERSION
            self.nf_session_id = int(packet["session_id"])
            self.nf_accepted_features = accepted_features
            self.nf_aux_port = int(packet["aux_port"])
            self.nf_tcp_port = int(packet["tcp_port"])
            self.nf_connecting = False
            self.nf_connected = True
            self.nf_waiting_pong = False
            self.nf_last_pong_ms = now_ms
            self.nf_busy_owner_ip = ""
            self.nf_busy_owner_port = 0
            self.nf_last_error = ""
            self.nf_next_reconnect_ms = 0.0
            self.nf_reconnect_backoff_ms = float(
                self.NF_RECONNECT_MIN_MS
            )
            self.nf_disconnect_burst_left = 0
            self._reset_nfv3_diagnostics_(reset_clock=False)
            self.nf_v4_clock.start_session(self.nf_session_id)
            self.data_model.begin_clock_epoch(
                self.NF_CLOCK_SOURCE,
                self.nf_clock_estimator.epoch,
            )
            if (
                self.nf_accepted_features
                & self.nf_v4_codec.FEATURE_DIAGNOSTICS
            ):
                self._send_nfv4_diag_capabilities_()
            self.begin_nfv3_schema_sync()
            return

        if packet["type"] == "session_busy":
            self.nf_connecting = False
            self.nf_connected = False
            self.nf_waiting_pong = False
            self.nf_busy_owner_ip = packet.get("owner_ip", "")
            self.nf_busy_owner_port = int(packet.get("owner_port", 0))
            self.nf_last_error = (
                f"busy by {self.nf_busy_owner_ip}:"
                f"{self.nf_busy_owner_port}"
            )
            self._schedule_reconnect_(now_ms, busy=True)
            return

        if packet["type"] == "connect_ack":
            self.nf_protocol = self.nf_parser.VERSION
            self.nf_session_id = 0
            self.nf_aux_port = int(self.udp_target_port or 0) + 1
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
            self._reset_nfv3_diagnostics_()
            self._send_nfv3_diag_capabilities_(remote_addr)
            self.nf_diag_next_capabilities_ms = time.monotonic() * 1000.0 + 5000.0
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
            if wire_version != self.nf_protocol:
                return
            self._observe_nfv3_data_packet_(packet)
            self._process_nfv3_data(packet, unix_ts)
            return

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

            if not self.data_ingestion_enabled:
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
