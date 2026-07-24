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

    SCHEMA_KIND_TASK = 1
    SCHEMA_KIND_TASK_PORT = 2
    SCHEMA_KIND_DATA_NODE = 3
    PORT_INPUT = 0
    PORT_OUTPUT = 1

    TASK_FLAG_BUSINESS_ENABLED = 1 << 0
    TASK_FLAG_INPUTS_VALID = 1 << 1
    TASK_FLAG_OUTPUTS_VALID = 1 << 2
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

    DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FMT)
    TASK_FRAME_HEADER_SIZE = struct.calcsize(TASK_FRAME_HEADER_FMT)
    NODE_FRAME_SIZE = struct.calcsize(NODE_FRAME_FMT)
    SCHEMA_REQ_SIZE = struct.calcsize(SCHEMA_REQ_FMT)
    SCHEMA_RESP_HEADER_SIZE = struct.calcsize(SCHEMA_RESP_HEADER_FMT)
    SCHEMA_ENTRY_HEADER_SIZE = struct.calcsize(SCHEMA_ENTRY_HEADER_FMT)
    CTRL_HEADER_SIZE = struct.calcsize(CTRL_HEADER_FMT)
    BUSY_ACK_SIZE = struct.calcsize(BUSY_ACK_FMT)

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

    def parse_packet(self, data: bytes):
        if not data or len(data) < 4:
            return None
        magic, version, packet_type = struct.unpack_from("<HBB", data, 0)
        if magic != self.MAGIC or version != self.VERSION:
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
        return None

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
