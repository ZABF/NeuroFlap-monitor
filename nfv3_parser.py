import struct


class NFv3Parser:
    MAGIC = 0x464E
    VERSION = 3

    TYPE_DATA = 0x01
    TYPE_SCHEMA_REQ = 0x10
    TYPE_SCHEMA_RESP = 0x11
    TYPE_CONNECT_REQ = 0x20
    TYPE_CONNECT_ACK = 0x21
    TYPE_BUSY_ACK = 0x22
    TYPE_LINK_PING = 0x23
    TYPE_LINK_PONG = 0x24
    TYPE_DISCONNECT_REQ = 0x25
    TYPE_DIAG_FEEDBACK = 0x30
    TYPE_DIAG_PROBE = 0x31
    TYPE_DIAG_CAPABILITIES = 0x32
    TYPE_DIAG_ECHO_REQUEST = 0x33
    TYPE_DIAG_ECHO_RESPONSE = 0x34
    TYPE_DIAG_CONTROL = 0x35
    TYPE_DIAG_CLOCK_SAMPLE = 0x36
    TYPE_DIAG_CLOCK_MODEL = 0x37

    DIAG_FEEDBACK_FINAL = 1 << 0
    DIAG_FEEDBACK_STAGE_COMPLETE = 1 << 1
    DIAG_PROBE_STAGE_START = 1 << 0
    DIAG_PROBE_STAGE_END = 1 << 1
    DIAG_PROBE_TEST_END = 1 << 2
    DIAG_PROBE_MONITOR_TO_FIRMWARE = 1 << 3

    DIAG_CAPABILITY_FEEDBACK = 1 << 0
    DIAG_CAPABILITY_ECHO = 1 << 1
    DIAG_CAPABILITY_UDP_REVERSE = 1 << 2
    DIAG_CAPABILITY_TCP = 1 << 3
    DIAG_CAPABILITY_FOUR_TIMESTAMPS = 1 << 4
    DIAG_CAPABILITY_ALL = (
        DIAG_CAPABILITY_FEEDBACK
        | DIAG_CAPABILITY_ECHO
        | DIAG_CAPABILITY_UDP_REVERSE
        | DIAG_CAPABILITY_TCP
        | DIAG_CAPABILITY_FOUR_TIMESTAMPS
    )

    DIAG_CONTROL_TEST_BEGIN = 1
    DIAG_CONTROL_UDP_UPLOAD_START = 2
    DIAG_CONTROL_TCP_CONNECT = 3
    DIAG_CONTROL_TCP_DOWNLOAD_START = 4
    DIAG_CONTROL_TCP_UPLOAD_START = 5
    DIAG_CONTROL_TEST_END = 6
    DIAG_CONTROL_CANCEL = 7

    DIAG_MODE_NONE = 0
    DIAG_MODE_LATENCY = 1
    DIAG_MODE_UDP_CAPACITY = 2
    DIAG_MODE_TCP_CAPACITY = 3
    DIAG_MODE_FULL = 4

    DIAG_TCP_MAGIC = 0x5444464E
    DIAG_TCP_PING = 1
    DIAG_TCP_PONG = 2
    DIAG_TCP_DOWNLOAD_DATA = 3
    DIAG_TCP_UPLOAD_DATA = 4

    SCHEMA_KIND_TASK = 1
    SCHEMA_KIND_TASK_PORT = 2
    SCHEMA_KIND_DATA_NODE = 3
    PORT_INPUT = 0
    PORT_OUTPUT = 1

    TASK_FLAG_BUSINESS_ENABLED = 1 << 0
    TASK_FLAG_INPUTS_VALID = 1 << 1
    TASK_FLAG_OUTPUTS_VALID = 1 << 2
    TASK_FLAG_STATE_MASK = 0x07
    TASK_CONTENTION_SHIFT = 3
    TASK_CONTENTION_MASK = 0x1F
    DEFAULT_TIMESTAMP_GROUP = 0xFF
    INVALID_AGE_US = 0xFFFFFFFF

    # DATA header: generation, packet sequence, packet build time, frame counts.
    DATA_HEADER_FMT = "<HBBIIQHH"
    TASK_FRAME_HEADER_FMT = "<HBII"
    NODE_FRAME_FMT = "<HBII"
    SCHEMA_REQ_FMT = "<HBBI"
    # Includes total entry count so chunk aggregation can be validated.
    SCHEMA_RESP_HEADER_FMT = "<HBBIHHHH"
    SCHEMA_ENTRY_HEADER_FMT = "<BH"
    CTRL_HEADER_FMT = "<HBB"
    BUSY_ACK_FMT = "<4sH"
    DIAG_FEEDBACK_FMT = "<HBBIBBHIIIIIII"
    DIAG_PROBE_HEADER_FMT = "<HBBIBBHIQHH"
    DIAG_CAPABILITIES_FMT = "<HBBIHHI"
    DIAG_ECHO_FMT = "<HBBIIQQQB3x"
    DIAG_CONTROL_FMT = "<HBBIBBBBHHIHH"
    DIAG_CLOCK_SAMPLE_FMT = "<HBBIIQQQQB3x"
    DIAG_CLOCK_MODEL_FMT = "<HBBIQQiIB3x15I"
    DIAG_TCP_HEADER_FMT = "<IIBBHIQQQ"

    DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FMT)
    TASK_FRAME_HEADER_SIZE = struct.calcsize(TASK_FRAME_HEADER_FMT)
    NODE_FRAME_SIZE = struct.calcsize(NODE_FRAME_FMT)
    SCHEMA_REQ_SIZE = struct.calcsize(SCHEMA_REQ_FMT)
    SCHEMA_RESP_HEADER_SIZE = struct.calcsize(SCHEMA_RESP_HEADER_FMT)
    SCHEMA_ENTRY_HEADER_SIZE = struct.calcsize(SCHEMA_ENTRY_HEADER_FMT)
    CTRL_HEADER_SIZE = struct.calcsize(CTRL_HEADER_FMT)
    BUSY_ACK_SIZE = struct.calcsize(BUSY_ACK_FMT)
    DIAG_FEEDBACK_SIZE = struct.calcsize(DIAG_FEEDBACK_FMT)
    DIAG_PROBE_HEADER_SIZE = struct.calcsize(DIAG_PROBE_HEADER_FMT)
    DIAG_CAPABILITIES_SIZE = struct.calcsize(DIAG_CAPABILITIES_FMT)
    DIAG_ECHO_SIZE = struct.calcsize(DIAG_ECHO_FMT)
    DIAG_CONTROL_SIZE = struct.calcsize(DIAG_CONTROL_FMT)
    DIAG_CLOCK_SAMPLE_SIZE = struct.calcsize(DIAG_CLOCK_SAMPLE_FMT)
    DIAG_CLOCK_MODEL_SIZE = struct.calcsize(DIAG_CLOCK_MODEL_FMT)
    DIAG_TCP_HEADER_SIZE = struct.calcsize(DIAG_TCP_HEADER_FMT)
    DIAG_TCP_FRAME_SIZE = 1200

    TYPE_UNKNOWN = 0
    TYPE_BOOL = 1
    TYPE_U8 = 2
    TYPE_U16 = 3
    TYPE_U32 = 4
    TYPE_I32 = 5
    TYPE_F32 = 6

    def __init__(self):
        self.clear_schema()

    def clear_schema(self):
        self.schema_generation = None
        self.schema_tasks = {}
        self.schema_nodes = {}

    def install_schema(self, schema_generation: int, entries) -> bool:
        tasks = {}
        ports = []
        nodes = {}
        for entry in entries:
            kind = int(entry.get("entry_kind", 0))
            if kind == self.SCHEMA_KIND_TASK:
                task_id = int(entry["task_id"])
                if task_id in tasks:
                    return False
                tasks[task_id] = {
                    **entry,
                    "inputs": [],
                    "outputs": [],
                }
            elif kind == self.SCHEMA_KIND_TASK_PORT:
                ports.append(dict(entry))
            elif kind == self.SCHEMA_KIND_DATA_NODE:
                node_no = int(entry["node_no"])
                if node_no in nodes:
                    return False
                nodes[node_no] = dict(entry)
            else:
                return False

        for port in ports:
            task = tasks.get(int(port["task_id"]))
            if task is None:
                return False
            direction = int(port["direction"])
            if direction == self.PORT_INPUT:
                task["inputs"].append(port)
            elif direction == self.PORT_OUTPUT:
                task["outputs"].append(port)
            else:
                return False

        for task in tasks.values():
            task["inputs"].sort(key=lambda item: int(item["slot"]))
            task["outputs"].sort(key=lambda item: int(item["slot"]))
            if len(task["inputs"]) != int(task["input_count"]):
                return False
            if len(task["outputs"]) != int(task["output_count"]):
                return False
            if [int(item["slot"]) for item in task["inputs"]] != list(range(len(task["inputs"]))):
                return False
            if [int(item["slot"]) for item in task["outputs"]] != list(range(len(task["outputs"]))):
                return False
            for port in task["inputs"]:
                group = int(port["timestamp_group"])
                if group != self.DEFAULT_TIMESTAMP_GROUP and group >= int(task["input_timestamp_group_count"]):
                    return False
            for port in task["outputs"]:
                group = int(port["timestamp_group"])
                if group != self.DEFAULT_TIMESTAMP_GROUP and group >= int(task["output_timestamp_group_count"]):
                    return False

        self.schema_generation = int(schema_generation) & 0xFFFFFFFF
        self.schema_tasks = tasks
        self.schema_nodes = nodes
        return True

    def build_schema_request(self, request_id: int) -> bytes:
        return struct.pack(
            self.SCHEMA_REQ_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_SCHEMA_REQ,
            request_id & 0xFFFFFFFF,
        )

    def build_connect_request(self) -> bytes:
        return struct.pack(self.CTRL_HEADER_FMT, self.MAGIC, self.VERSION, self.TYPE_CONNECT_REQ)

    def build_link_ping(self) -> bytes:
        return struct.pack(self.CTRL_HEADER_FMT, self.MAGIC, self.VERSION, self.TYPE_LINK_PING)

    def build_disconnect_request(self) -> bytes:
        return struct.pack(self.CTRL_HEADER_FMT, self.MAGIC, self.VERSION, self.TYPE_DISCONNECT_REQ)

    def build_diag_feedback(
        self,
        test_id: int,
        stage: int,
        flags: int,
        normal_packets_rx: int,
        normal_packet_gaps: int,
        probe_packets_rx: int,
        probe_packet_gaps: int,
        last_probe_seq: int,
        max_probe_gap: int,
        receiver_errors: int,
    ) -> bytes:
        return struct.pack(
            self.DIAG_FEEDBACK_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_FEEDBACK,
            test_id & 0xFFFFFFFF,
            stage & 0xFF,
            flags & 0xFF,
            0,
            normal_packets_rx & 0xFFFFFFFF,
            normal_packet_gaps & 0xFFFFFFFF,
            probe_packets_rx & 0xFFFFFFFF,
            probe_packet_gaps & 0xFFFFFFFF,
            last_probe_seq & 0xFFFFFFFF,
            max_probe_gap & 0xFFFFFFFF,
            receiver_errors & 0xFFFFFFFF,
        )

    def build_diag_capabilities(
        self,
        features: int,
        max_udp_payload: int,
        preferred_tcp_frame: int,
        monitor_nonce: int,
    ) -> bytes:
        return struct.pack(
            self.DIAG_CAPABILITIES_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_CAPABILITIES,
            features & 0xFFFFFFFF,
            max_udp_payload & 0xFFFF,
            preferred_tcp_frame & 0xFFFF,
            monitor_nonce & 0xFFFFFFFF,
        )

    def build_diag_echo_response(
        self,
        test_id: int,
        sequence: int,
        t1_us: int,
        t2_us: int,
        t3_us: int,
        flags: int = 0,
    ) -> bytes:
        return struct.pack(
            self.DIAG_ECHO_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_ECHO_RESPONSE,
            test_id & 0xFFFFFFFF,
            sequence & 0xFFFFFFFF,
            t1_us & 0xFFFFFFFFFFFFFFFF,
            t2_us & 0xFFFFFFFFFFFFFFFF,
            t3_us & 0xFFFFFFFFFFFFFFFF,
            flags & 0xFF,
        )

    def build_diag_clock_model(self, transform, path_stats) -> bytes:
        def values(name):
            stats = path_stats.get(name, {})
            return (
                int(stats.get("samples", 0)),
                int(stats.get("latest", 0)),
                int(stats.get("min", 0)),
                int(stats.get("p50", 0)),
                int(stats.get("p95", 0)),
            )

        return struct.pack(
            self.DIAG_CLOCK_MODEL_FMT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_CLOCK_MODEL,
            int(transform.revision) & 0xFFFFFFFF,
            int(transform.source_anchor_us) & 0xFFFFFFFFFFFFFFFF,
            int(transform.target_anchor_us) & 0xFFFFFFFFFFFFFFFF,
            int(transform.drift_ppb),
            min(0xFFFFFFFF, max(0, int(transform.uncertainty_us))),
            1 if transform.locked else 0,
            *values("upload"),
            *values("download"),
            *values("rtt"),
        )

    def build_diag_probe(
        self,
        test_id: int,
        stage: int,
        flags: int,
        packet_size: int,
        probe_seq: int,
        send_us: int,
        target_pps: int,
    ) -> bytes:
        if packet_size < self.DIAG_PROBE_HEADER_SIZE or packet_size > 0xFFFF:
            raise ValueError("invalid diagnostic probe size")
        packet = bytearray(packet_size)
        struct.pack_into(
            self.DIAG_PROBE_HEADER_FMT,
            packet,
            0,
            self.MAGIC,
            self.VERSION,
            self.TYPE_DIAG_PROBE,
            test_id & 0xFFFFFFFF,
            stage & 0xFF,
            flags & 0xFF,
            packet_size,
            probe_seq & 0xFFFFFFFF,
            send_us & 0xFFFFFFFFFFFFFFFF,
            target_pps & 0xFFFF,
            0,
        )
        return bytes(packet)

    def build_diag_tcp_frame(
        self,
        test_id: int,
        kind: int,
        stage: int,
        sequence: int,
        t1_us: int,
        t2_us: int = 0,
        t3_us: int = 0,
    ) -> bytes:
        frame = bytearray(self.DIAG_TCP_FRAME_SIZE)
        struct.pack_into(
            self.DIAG_TCP_HEADER_FMT,
            frame,
            0,
            self.DIAG_TCP_MAGIC,
            test_id & 0xFFFFFFFF,
            kind & 0xFF,
            stage & 0xFF,
            self.DIAG_TCP_FRAME_SIZE - self.DIAG_TCP_HEADER_SIZE,
            sequence & 0xFFFFFFFF,
            t1_us & 0xFFFFFFFFFFFFFFFF,
            t2_us & 0xFFFFFFFFFFFFFFFF,
            t3_us & 0xFFFFFFFFFFFFFFFF,
        )
        return bytes(frame)

    @classmethod
    def peek_packet_type(cls, data: bytes):
        if not data or len(data) < cls.CTRL_HEADER_SIZE:
            return None
        magic, version, packet_type = struct.unpack_from(cls.CTRL_HEADER_FMT, data, 0)
        if magic != cls.MAGIC or version != cls.VERSION:
            return None
        return int(packet_type)

    def parse_packet(self, data: bytes):
        packet_type = self.peek_packet_type(data)
        if packet_type is None:
            return None
        if packet_type == self.TYPE_DATA:
            return self._parse_data_packet(data)
        if packet_type == self.TYPE_SCHEMA_RESP:
            return self._parse_schema_response(data)
        if packet_type == self.TYPE_CONNECT_ACK:
            return self._parse_control(data, "connect_ack")
        if packet_type == self.TYPE_BUSY_ACK:
            return self._parse_busy_ack(data)
        if packet_type == self.TYPE_LINK_PONG:
            return self._parse_control(data, "link_pong")
        if packet_type == self.TYPE_DIAG_PROBE:
            return self._parse_diag_probe(data)
        if packet_type == self.TYPE_DIAG_CAPABILITIES:
            return self._parse_diag_capabilities(data)
        if packet_type == self.TYPE_DIAG_ECHO_REQUEST:
            return self._parse_diag_echo(data, "diag_echo_request")
        if packet_type == self.TYPE_DIAG_ECHO_RESPONSE:
            return self._parse_diag_echo(data, "diag_echo_response")
        if packet_type == self.TYPE_DIAG_CONTROL:
            return self._parse_diag_control(data)
        if packet_type == self.TYPE_DIAG_FEEDBACK:
            return self._parse_diag_feedback(data)
        if packet_type == self.TYPE_DIAG_CLOCK_SAMPLE:
            return self._parse_diag_clock_sample(data)
        return None

    def _parse_diag_clock_sample(self, data: bytes):
        if len(data) != self.DIAG_CLOCK_SAMPLE_SIZE:
            return None
        values = struct.unpack(self.DIAG_CLOCK_SAMPLE_FMT, data)
        return {
            "type": "diag_clock_sample",
            "test_id": int(values[3]),
            "sequence": int(values[4]),
            "t1_us": int(values[5]),
            "t2_us": int(values[6]),
            "t3_us": int(values[7]),
            "t4_us": int(values[8]),
            "flags": int(values[9]),
        }

    def _parse_diag_feedback(self, data: bytes):
        if len(data) != self.DIAG_FEEDBACK_SIZE:
            return None
        values = struct.unpack(self.DIAG_FEEDBACK_FMT, data)
        return {
            "type": "diag_feedback",
            "test_id": int(values[3]),
            "stage": int(values[4]),
            "flags": int(values[5]),
            "normal_packets_rx": int(values[7]),
            "normal_packet_gaps": int(values[8]),
            "probe_packets_rx": int(values[9]),
            "probe_packet_gaps": int(values[10]),
            "last_probe_seq": int(values[11]),
            "max_probe_gap": int(values[12]),
            "receiver_errors": int(values[13]),
        }

    def _parse_diag_probe(self, data: bytes):
        if len(data) < self.DIAG_PROBE_HEADER_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            test_id,
            stage,
            flags,
            packet_size,
            probe_seq,
            send_us,
            target_pps,
            _reserved,
        ) = struct.unpack_from(self.DIAG_PROBE_HEADER_FMT, data, 0)
        if packet_size != len(data):
            return None
        return {
            "type": "diag_probe",
            "test_id": test_id,
            "stage": stage,
            "flags": flags,
            "packet_size": packet_size,
            "probe_seq": probe_seq,
            "send_us": send_us,
            "target_pps": target_pps,
        }

    def _parse_diag_capabilities(self, data: bytes):
        if len(data) != self.DIAG_CAPABILITIES_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            features,
            max_udp_payload,
            preferred_tcp_frame,
            monitor_nonce,
        ) = struct.unpack(self.DIAG_CAPABILITIES_FMT, data)
        return {
            "type": "diag_capabilities",
            "features": int(features),
            "max_udp_payload": int(max_udp_payload),
            "preferred_tcp_frame": int(preferred_tcp_frame),
            "monitor_nonce": int(monitor_nonce),
        }

    def _parse_diag_echo(self, data: bytes, name: str):
        if len(data) != self.DIAG_ECHO_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            test_id,
            sequence,
            t1_us,
            t2_us,
            t3_us,
            flags,
        ) = struct.unpack(self.DIAG_ECHO_FMT, data)
        return {
            "type": name,
            "test_id": int(test_id),
            "sequence": int(sequence),
            "t1_us": int(t1_us),
            "t2_us": int(t2_us),
            "t3_us": int(t3_us),
            "flags": int(flags),
        }

    def _parse_diag_control(self, data: bytes):
        if len(data) != self.DIAG_CONTROL_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            test_id,
            action,
            mode,
            stage,
            flags,
            target_pps,
            payload_bytes,
            duration_ms,
            tcp_port,
            _reserved,
        ) = struct.unpack(self.DIAG_CONTROL_FMT, data)
        return {
            "type": "diag_control",
            "test_id": int(test_id),
            "action": int(action),
            "mode": int(mode),
            "stage": int(stage),
            "flags": int(flags),
            "target_pps": int(target_pps),
            "payload_bytes": int(payload_bytes),
            "duration_ms": int(duration_ms),
            "tcp_port": int(tcp_port),
        }

    def parse_diag_tcp_frame(self, data: bytes):
        if len(data) != self.DIAG_TCP_FRAME_SIZE:
            return None
        (
            magic,
            test_id,
            kind,
            stage,
            payload_size,
            sequence,
            t1_us,
            t2_us,
            t3_us,
        ) = struct.unpack_from(self.DIAG_TCP_HEADER_FMT, data, 0)
        if (
            magic != self.DIAG_TCP_MAGIC
            or payload_size != self.DIAG_TCP_FRAME_SIZE - self.DIAG_TCP_HEADER_SIZE
        ):
            return None
        return {
            "test_id": int(test_id),
            "kind": int(kind),
            "stage": int(stage),
            "sequence": int(sequence),
            "t1_us": int(t1_us),
            "t2_us": int(t2_us),
            "t3_us": int(t3_us),
        }

    def raw_to_value(self, scalar_type: int, raw: int):
        if scalar_type == self.TYPE_BOOL:
            return 1.0 if raw != 0 else 0.0
        if scalar_type == self.TYPE_U8:
            return float(raw & 0xFF)
        if scalar_type == self.TYPE_U16:
            return float(raw & 0xFFFF)
        if scalar_type == self.TYPE_U32:
            return float(raw & 0xFFFFFFFF)
        if scalar_type == self.TYPE_I32:
            return float(struct.unpack("<i", struct.pack("<I", raw & 0xFFFFFFFF))[0])
        if scalar_type == self.TYPE_F32:
            return float(struct.unpack("<f", struct.pack("<I", raw & 0xFFFFFFFF))[0])
        return None

    def _parse_data_packet(self, data: bytes):
        if len(data) < self.DATA_HEADER_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            schema_generation,
            packet_seq,
            packet_time_us,
            task_frame_count,
            node_frame_count,
        ) = struct.unpack_from(self.DATA_HEADER_FMT, data, 0)
        packet = {
            "type": "data",
            "schema_generation": schema_generation,
            "packet_seq": packet_seq,
            "packet_time_us": packet_time_us,
            "task_frame_count": task_frame_count,
            "node_frame_count": node_frame_count,
            "task_frames": [],
            "node_frames": [],
            "schema_available": self.schema_generation == schema_generation,
        }
        if not packet["schema_available"]:
            return packet

        offset = self.DATA_HEADER_SIZE
        for _ in range(task_frame_count):
            if offset + self.TASK_FRAME_HEADER_SIZE > len(data):
                return None
            task_id, flags, input_age_us, output_age_us = struct.unpack_from(
                self.TASK_FRAME_HEADER_FMT, data, offset
            )
            offset += self.TASK_FRAME_HEADER_SIZE
            task = self.schema_tasks.get(int(task_id))
            if task is None:
                return None

            value_count = int(task["input_count"]) + int(task["output_count"])
            group_count = int(task["input_timestamp_group_count"]) + int(task["output_timestamp_group_count"])
            needed = 4 * (value_count + group_count)
            if offset + needed > len(data):
                return None

            raw_values = list(struct.unpack_from(f"<{value_count}I", data, offset)) if value_count else []
            offset += 4 * value_count
            group_ages = list(struct.unpack_from(f"<{group_count}I", data, offset)) if group_count else []
            offset += 4 * group_count
            input_group_count = int(task["input_timestamp_group_count"])
            input_group_ages = group_ages[:input_group_count]
            output_group_ages = group_ages[input_group_count:]

            inputs = []
            for index, port in enumerate(task["inputs"]):
                group = int(port["timestamp_group"])
                capture_age = input_age_us if group == self.DEFAULT_TIMESTAMP_GROUP else input_group_ages[group]
                inputs.append({**port, "raw": raw_values[index], "capture_age_us": capture_age})
            outputs = []
            raw_offset = int(task["input_count"])
            for index, port in enumerate(task["outputs"]):
                group = int(port["timestamp_group"])
                capture_age = output_age_us if group == self.DEFAULT_TIMESTAMP_GROUP else output_group_ages[group]
                outputs.append({**port, "raw": raw_values[raw_offset + index], "capture_age_us": capture_age})

            packet["task_frames"].append(
                {
                    "task_id": int(task_id),
                    "flags": int(flags),
                    "snapshot_contention_count": (
                        int(flags) >> self.TASK_CONTENTION_SHIFT
                    ) & self.TASK_CONTENTION_MASK,
                    "input_age_us": int(input_age_us),
                    "output_age_us": int(output_age_us),
                    "inputs": inputs,
                    "outputs": outputs,
                }
            )

        for _ in range(node_frame_count):
            if offset + self.NODE_FRAME_SIZE > len(data):
                return None
            node_no, status, publish_age_us, raw = struct.unpack_from(self.NODE_FRAME_FMT, data, offset)
            offset += self.NODE_FRAME_SIZE
            node = self.schema_nodes.get(int(node_no))
            if node is None:
                return None
            packet["node_frames"].append(
                {**node, "status": int(status), "publish_age_us": int(publish_age_us), "raw": int(raw)}
            )

        return packet if offset == len(data) else None

    def _parse_schema_response(self, data: bytes):
        if len(data) < self.SCHEMA_RESP_HEADER_SIZE:
            return None
        (
            _magic,
            _version,
            _packet_type,
            schema_generation,
            chunk_index,
            chunk_total,
            entry_count,
            total_entries,
        ) = struct.unpack_from(self.SCHEMA_RESP_HEADER_FMT, data, 0)
        if chunk_total == 0 or chunk_index >= chunk_total:
            return None

        entries = []
        offset = self.SCHEMA_RESP_HEADER_SIZE
        for _ in range(entry_count):
            if offset + self.SCHEMA_ENTRY_HEADER_SIZE > len(data):
                return None
            entry_kind, payload_len = struct.unpack_from(self.SCHEMA_ENTRY_HEADER_FMT, data, offset)
            offset += self.SCHEMA_ENTRY_HEADER_SIZE
            payload_end = offset + payload_len
            if payload_end > len(data):
                return None
            entry = self._parse_schema_entry(entry_kind, data, offset, payload_end)
            if entry is None:
                return None
            entries.append(entry)
            offset = payload_end
        if offset != len(data):
            return None
        return {
            "type": "schema_resp",
            "schema_generation": int(schema_generation),
            "chunk_index": int(chunk_index),
            "chunk_total": int(chunk_total),
            "total_entries": int(total_entries),
            "entries": entries,
        }

    def _parse_schema_entry(self, kind: int, data: bytes, offset: int, end: int):
        if kind == self.SCHEMA_KIND_TASK:
            fixed_fmt = "<HBBBBB"
            fixed_size = struct.calcsize(fixed_fmt)
            if offset + fixed_size > end:
                return None
            task_id, input_count, output_count, input_groups, output_groups, name_len = struct.unpack_from(
                fixed_fmt, data, offset
            )
            offset += fixed_size
            if offset + name_len != end:
                return None
            return {
                "entry_kind": kind,
                "task_id": int(task_id),
                "input_count": int(input_count),
                "output_count": int(output_count),
                "input_timestamp_group_count": int(input_groups),
                "output_timestamp_group_count": int(output_groups),
                "name": data[offset:end].decode("utf-8", errors="ignore"),
            }

        if kind == self.SCHEMA_KIND_TASK_PORT:
            fixed_fmt = "<HBBBBBB"
            fixed_size = struct.calcsize(fixed_fmt)
            if offset + fixed_size > end:
                return None
            task_id, direction, slot, scalar_type, timestamp_group, name_len, unit_len = struct.unpack_from(
                fixed_fmt, data, offset
            )
            offset += fixed_size
            if offset + name_len + unit_len != end:
                return None
            name = data[offset:offset + name_len].decode("utf-8", errors="ignore")
            offset += name_len
            unit = data[offset:offset + unit_len].decode("utf-8", errors="ignore")
            return {
                "entry_kind": kind,
                "task_id": int(task_id),
                "direction": int(direction),
                "slot": int(slot),
                "scalar_type": int(scalar_type),
                "timestamp_group": int(timestamp_group),
                "name": name,
                "unit": unit,
            }

        if kind == self.SCHEMA_KIND_DATA_NODE:
            fixed_fmt = "<HHBBBB"
            fixed_size = struct.calcsize(fixed_fmt)
            if offset + fixed_size > end:
                return None
            node_no, node_id, scalar_type, group_len, name_len, unit_len = struct.unpack_from(
                fixed_fmt, data, offset
            )
            offset += fixed_size
            if offset + group_len + name_len + unit_len != end:
                return None
            group = data[offset:offset + group_len].decode("utf-8", errors="ignore")
            offset += group_len
            name = data[offset:offset + name_len].decode("utf-8", errors="ignore")
            offset += name_len
            unit = data[offset:offset + unit_len].decode("utf-8", errors="ignore")
            return {
                "entry_kind": kind,
                "node_no": int(node_no),
                "node_id": int(node_id),
                "scalar_type": int(scalar_type),
                "group": group,
                "name": name,
                "unit": unit,
            }
        return None

    def _parse_control(self, data: bytes, name: str):
        return {"type": name} if len(data) == self.CTRL_HEADER_SIZE else None

    def _parse_busy_ack(self, data: bytes):
        if len(data) != self.CTRL_HEADER_SIZE + self.BUSY_ACK_SIZE:
            return None
        raw_ip, owner_port = struct.unpack_from(self.BUSY_ACK_FMT, data, self.CTRL_HEADER_SIZE)
        return {
            "type": "busy_ack",
            "owner_ip": ".".join(str(int(byte)) for byte in raw_ip),
            "owner_port": int(owner_port),
        }
