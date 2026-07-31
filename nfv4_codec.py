import struct

from nfv3_parser import NFv3Parser


class NFv4Codec:
    """NFv4 session, clock-sync, and diagnostic wire codec.

    DATA and SCHEMA payloads intentionally retain the NFv3 layout. Their
    version byte is normalized before delegating to the released NFv3 parser.
    """

    MAGIC = 0x464E
    VERSION = 4

    TYPE_DATA = 0x01
    TYPE_SCHEMA_REQ = 0x10
    TYPE_SCHEMA_RESP = 0x11
    TYPE_SESSION_OPEN = 0x20
    TYPE_SESSION_ACCEPT = 0x21
    TYPE_SESSION_BUSY = 0x22
    TYPE_SESSION_CLOSE = 0x23
    TYPE_SYNC_REQUEST = 0x24
    TYPE_SYNC_RESPONSE = 0x25
    TYPE_DIAG_COMMAND = 0x30
    TYPE_DIAG_PROBE = 0x31
    TYPE_DIAG_REPORT = 0x32

    FEATURE_CLOCK_SYNC = 1 << 0
    FEATURE_DIAGNOSTICS = 1 << 1
    FEATURE_TCP_DIAGNOSTICS = 1 << 2

    DIAG_REPORT_CAPABILITIES = 1
    DIAG_REPORT_FEEDBACK = 2
    DIAG_REPORT_PATH = 3

    DIAG_CONTROL_TEST_BEGIN = 1
    DIAG_CONTROL_UDP_UPLOAD_START = 2
    DIAG_CONTROL_TCP_CONNECT = 3
    DIAG_CONTROL_TCP_DOWNLOAD_START = 4
    DIAG_CONTROL_TCP_UPLOAD_START = 5
    DIAG_CONTROL_TEST_END = 6
    DIAG_CONTROL_CANCEL = 7

    DIAG_FEEDBACK_FINAL = 1 << 0
    DIAG_FEEDBACK_STAGE_COMPLETE = 1 << 1
    DIAG_PROBE_STAGE_START = 1 << 0
    DIAG_PROBE_STAGE_END = 1 << 1
    DIAG_PROBE_TEST_END = 1 << 2
    DIAG_PROBE_MONITOR_TO_FIRMWARE = 1 << 3

    DIAG_CAPABILITY_FEEDBACK = 1 << 0
    DIAG_CAPABILITY_PATH_LATENCY = 1 << 1
    DIAG_CAPABILITY_UDP_REVERSE = 1 << 2
    DIAG_CAPABILITY_TCP = 1 << 3
    DIAG_CAPABILITY_FOUR_TIMESTAMPS = 1 << 4
    DIAG_CAPABILITY_ALL = (
        DIAG_CAPABILITY_FEEDBACK
        | DIAG_CAPABILITY_PATH_LATENCY
        | DIAG_CAPABILITY_UDP_REVERSE
        | DIAG_CAPABILITY_TCP
        | DIAG_CAPABILITY_FOUR_TIMESTAMPS
    )

    SESSION_OPEN_FMT = "<HBBIIHH"
    SESSION_ACCEPT_FMT = "<HBBIIIHHI"
    SESSION_BUSY_FMT = "<HBBIHH"
    SESSION_CLOSE_FMT = "<HBBI"
    SYNC_REQUEST_FMT = "<HBBIIIBBH"
    SYNC_RESPONSE_FMT = "<HBBIIQQIBBH"
    DIAG_COMMAND_FMT = "<HBBIIBBBBHHIHH"
    DIAG_PROBE_HEADER_FMT = "<HBBIIBBHIQHH"
    DIAG_CAPABILITIES_REPORT_FMT = "<HBBIBBHIHHI"
    DIAG_FEEDBACK_REPORT_FMT = "<HBBIBBHIB3xIIIIIII"
    DIAG_PATH_REPORT_FMT = "<HBBIBBHIB3xQQiI15I"

    SESSION_OPEN_SIZE = struct.calcsize(SESSION_OPEN_FMT)
    SESSION_ACCEPT_SIZE = struct.calcsize(SESSION_ACCEPT_FMT)
    SESSION_BUSY_SIZE = struct.calcsize(SESSION_BUSY_FMT)
    SESSION_CLOSE_SIZE = struct.calcsize(SESSION_CLOSE_FMT)
    SYNC_REQUEST_SIZE = struct.calcsize(SYNC_REQUEST_FMT)
    SYNC_RESPONSE_SIZE = struct.calcsize(SYNC_RESPONSE_FMT)
    DIAG_COMMAND_SIZE = struct.calcsize(DIAG_COMMAND_FMT)
    DIAG_PROBE_HEADER_SIZE = struct.calcsize(DIAG_PROBE_HEADER_FMT)
    DIAG_CAPABILITIES_REPORT_SIZE = struct.calcsize(
        DIAG_CAPABILITIES_REPORT_FMT
    )
    DIAG_FEEDBACK_REPORT_SIZE = struct.calcsize(DIAG_FEEDBACK_REPORT_FMT)
    DIAG_PATH_REPORT_SIZE = struct.calcsize(DIAG_PATH_REPORT_FMT)

    def __init__(self, data_parser=None):
        self.data_parser = data_parser or NFv3Parser()

    @classmethod
    def peek_header(cls, data):
        if len(data) < 4:
            return None
        magic, version, packet_type = struct.unpack_from("<HBB", data, 0)
        if magic != cls.MAGIC or version != cls.VERSION:
            return None
        return packet_type

    def build_session_open(
        self,
        client_nonce,
        requested_features,
        max_udp_payload=1200,
        preferred_tcp_frame=1200,
    ):
        return struct.pack(
            self.SESSION_OPEN_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_SESSION_OPEN,
            int(client_nonce) & 0xFFFFFFFF,
            int(requested_features) & 0xFFFFFFFF,
            int(max_udp_payload) & 0xFFFF,
            int(preferred_tcp_frame) & 0xFFFF,
        )

    def build_session_close(self, session_id):
        return struct.pack(
            self.SESSION_CLOSE_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_SESSION_CLOSE,
            int(session_id) & 0xFFFFFFFF,
        )

    def build_schema_request(self, request_id):
        packet = bytearray(self.data_parser.build_schema_request(request_id))
        packet[2] = self.VERSION
        return bytes(packet)

    def build_sync_request(
        self,
        session_id,
        sequence,
        context=0,
        stage=0,
        flags=0,
    ):
        return struct.pack(
            self.SYNC_REQUEST_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_SYNC_REQUEST,
            int(session_id) & 0xFFFFFFFF,
            int(sequence) & 0xFFFFFFFF,
            int(context) & 0xFFFFFFFF,
            int(stage) & 0xFF,
            int(flags) & 0xFF,
            0,
        )

    def parse_base_packet(self, data):
        packet_type = self.peek_header(data)
        if packet_type is None:
            return None
        if packet_type in (self.TYPE_DATA, self.TYPE_SCHEMA_RESP):
            normalized = bytearray(data)
            normalized[2] = NFv3Parser.VERSION
            packet = self.data_parser.parse_packet(bytes(normalized))
            if packet is not None:
                packet["wire_version"] = self.VERSION
            return packet
        if packet_type == self.TYPE_SESSION_ACCEPT:
            if len(data) != self.SESSION_ACCEPT_SIZE:
                return None
            (
                _magic,
                _version,
                _type,
                client_nonce,
                session_id,
                accepted_features,
                aux_port,
                tcp_port,
                timeout_ms,
            ) = struct.unpack(self.SESSION_ACCEPT_FMT, data)
            return {
                "type": "session_accept",
                "client_nonce": client_nonce,
                "session_id": session_id,
                "accepted_features": accepted_features,
                "aux_port": aux_port,
                "tcp_port": tcp_port,
                "timeout_ms": timeout_ms,
                "wire_version": self.VERSION,
            }
        if packet_type == self.TYPE_SESSION_BUSY:
            if len(data) != self.SESSION_BUSY_SIZE:
                return None
            (
                _magic,
                _version,
                _type,
                owner_ipv4,
                owner_port,
                retry_ms,
            ) = struct.unpack(self.SESSION_BUSY_FMT, data)
            return {
                "type": "session_busy",
                "owner_ipv4": owner_ipv4,
                "owner_ip": self._format_ipv4(owner_ipv4),
                "owner_port": owner_port,
                "retry_ms": retry_ms,
                "wire_version": self.VERSION,
            }
        return None

    def parse_sync_response(self, data):
        if self.peek_header(data) != self.TYPE_SYNC_RESPONSE:
            return None
        if len(data) != self.SYNC_RESPONSE_SIZE:
            return None
        (
            _magic,
            _version,
            _type,
            session_id,
            sequence,
            t2_us,
            t3_us,
            context,
            stage,
            flags,
            _reserved,
        ) = struct.unpack(self.SYNC_RESPONSE_FMT, data)
        return {
            "type": "sync_response",
            "session_id": session_id,
            "sequence": sequence,
            "t2_us": t2_us,
            "t3_us": t3_us,
            "context": context,
            "stage": stage,
            "flags": flags,
        }

    def parse_aux_packet(self, data):
        packet_type = self.peek_header(data)
        if packet_type == self.TYPE_SYNC_RESPONSE:
            return self.parse_sync_response(data)
        if packet_type == self.TYPE_DIAG_COMMAND:
            if len(data) != self.DIAG_COMMAND_SIZE:
                return None
            values = struct.unpack(self.DIAG_COMMAND_FMT, data)
            return {
                "type": "diag_command",
                "session_id": values[3],
                "test_id": values[4],
                "action": values[5],
                "mode": values[6],
                "stage": values[7],
                "flags": values[8],
                "target_pps": values[9],
                "payload_bytes": values[10],
                "duration_ms": values[11],
                "tcp_port": values[12],
                "wire_version": self.VERSION,
            }
        if packet_type == self.TYPE_DIAG_PROBE:
            if len(data) < self.DIAG_PROBE_HEADER_SIZE:
                return None
            values = struct.unpack_from(self.DIAG_PROBE_HEADER_FMT, data, 0)
            if values[7] != len(data):
                return None
            return {
                "type": "diag_probe",
                "session_id": values[3],
                "test_id": values[4],
                "stage": values[5],
                "flags": values[6],
                "packet_size": values[7],
                "probe_seq": values[8],
                "sender_us": values[9],
                "target_pps": values[10],
                "wire_version": self.VERSION,
            }
        return None

    def build_diag_capabilities_report(
        self,
        session_id,
        features,
        max_udp_payload,
        preferred_tcp_frame,
        monitor_nonce,
    ):
        return struct.pack(
            self.DIAG_CAPABILITIES_REPORT_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_REPORT,
            int(session_id) & 0xFFFFFFFF,
            self.DIAG_REPORT_CAPABILITIES,
            0,
            self.DIAG_CAPABILITIES_REPORT_SIZE,
            int(features) & 0xFFFFFFFF,
            int(max_udp_payload) & 0xFFFF,
            int(preferred_tcp_frame) & 0xFFFF,
            int(monitor_nonce) & 0xFFFFFFFF,
        )

    def build_diag_feedback_report(
        self,
        session_id,
        test_id,
        stage,
        flags,
        normal_packets_rx,
        normal_packet_gaps,
        probe_packets_rx,
        probe_packet_gaps,
        last_probe_seq,
        max_probe_gap,
        receiver_errors,
    ):
        return struct.pack(
            self.DIAG_FEEDBACK_REPORT_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_REPORT,
            int(session_id) & 0xFFFFFFFF,
            self.DIAG_REPORT_FEEDBACK,
            int(flags) & 0xFF,
            self.DIAG_FEEDBACK_REPORT_SIZE,
            int(test_id) & 0xFFFFFFFF,
            int(stage) & 0xFF,
            int(normal_packets_rx) & 0xFFFFFFFF,
            int(normal_packet_gaps) & 0xFFFFFFFF,
            int(probe_packets_rx) & 0xFFFFFFFF,
            int(probe_packet_gaps) & 0xFFFFFFFF,
            int(last_probe_seq) & 0xFFFFFFFF,
            int(max_probe_gap) & 0xFFFFFFFF,
            int(receiver_errors) & 0xFFFFFFFF,
        )

    @staticmethod
    def _path_stats_fields(stats):
        return (
            int(stats.get("samples", 0)) & 0xFFFFFFFF,
            int(stats.get("latest", 0)) & 0xFFFFFFFF,
            int(stats.get("min", 0)) & 0xFFFFFFFF,
            int(stats.get("p50", 0)) & 0xFFFFFFFF,
            int(stats.get("p95", 0)) & 0xFFFFFFFF,
        )

    def build_diag_path_report(
        self,
        session_id,
        transform,
        path_stats,
        *,
        test_id=0,
        stage=0xFF,
    ):
        flags = 0
        if transform.usable or transform.locked:
            flags |= 1
        if transform.locked:
            flags |= 2
        return struct.pack(
            self.DIAG_PATH_REPORT_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_REPORT,
            int(session_id) & 0xFFFFFFFF,
            self.DIAG_REPORT_PATH,
            flags,
            self.DIAG_PATH_REPORT_SIZE,
            int(test_id) & 0xFFFFFFFF,
            int(stage) & 0xFF,
            int(transform.source_anchor_us) & 0xFFFFFFFFFFFFFFFF,
            int(transform.target_anchor_us) & 0xFFFFFFFFFFFFFFFF,
            int(transform.drift_ppb),
            int(transform.uncertainty_us) & 0xFFFFFFFF,
            *self._path_stats_fields(path_stats.get("upload", {})),
            *self._path_stats_fields(path_stats.get("download", {})),
            *self._path_stats_fields(path_stats.get("rtt", {})),
        )

    def build_diag_probe(
        self,
        session_id,
        test_id,
        stage,
        flags,
        packet_size,
        sequence,
        sender_us,
        target_pps,
    ):
        packet_size = int(packet_size)
        if packet_size < self.DIAG_PROBE_HEADER_SIZE or packet_size > 0xFFFF:
            raise ValueError("invalid NFv4 diagnostic probe size")
        packet = bytearray(packet_size)
        struct.pack_into(
            self.DIAG_PROBE_HEADER_FMT,
            packet,
            0,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_PROBE,
            int(session_id) & 0xFFFFFFFF,
            int(test_id) & 0xFFFFFFFF,
            int(stage) & 0xFF,
            int(flags) & 0xFF,
            packet_size,
            int(sequence) & 0xFFFFFFFF,
            int(sender_us) & 0xFFFFFFFFFFFFFFFF,
            int(target_pps) & 0xFFFF,
            0,
        )
        return bytes(packet)

    @staticmethod
    def _format_ipv4(value):
        return ".".join(str((int(value) >> shift) & 0xFF) for shift in (24, 16, 8, 0))
