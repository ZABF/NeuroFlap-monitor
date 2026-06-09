import struct


class NFv1Parser:
    MAGIC = 0x464E
    VERSION = 2

    TYPE_DATA = 0x01
    TYPE_SCHEMA_REQ = 0x10
    TYPE_SCHEMA_RESP = 0x11
    TYPE_CONNECT_REQ = 0x20
    TYPE_CONNECT_ACK = 0x21
    TYPE_BUSY_ACK = 0x22
    TYPE_LINK_PING = 0x23
    TYPE_LINK_PONG = 0x24
    TYPE_DISCONNECT_REQ = 0x25

    # DATA: magic + ver + type + schema_generation + packet_seq + build_us + send_us + item_count
    DATA_HEADER_FMT = "<HBBIIQQH"
    # DATA item: signal_no + dt_us16 + raw
    DATA_ITEM_FMT = "<BHI"
    # SCHEMA_REQ: magic + ver + type + request_id
    SCHEMA_REQ_FMT = "<HBBI"
    # SCHEMA_RESP: magic + ver + type + schema_generation + section_mask + chunk_index + chunk_total + entry_count
    SCHEMA_RESP_HEADER_FMT = "<HBBIIHHH"
    # CTRL header: magic + ver + type
    CTRL_HEADER_FMT = "<HBB"
    # BUSY_ACK payload: owner_ip[4] + owner_port(u16)
    BUSY_ACK_FMT = "<4sH"

    DATA_HEADER_SIZE = struct.calcsize(DATA_HEADER_FMT)
    DATA_ITEM_SIZE = struct.calcsize(DATA_ITEM_FMT)
    SCHEMA_REQ_SIZE = struct.calcsize(SCHEMA_REQ_FMT)
    SCHEMA_RESP_HEADER_SIZE = struct.calcsize(SCHEMA_RESP_HEADER_FMT)
    CTRL_HEADER_SIZE = struct.calcsize(CTRL_HEADER_FMT)
    BUSY_ACK_SIZE = struct.calcsize(BUSY_ACK_FMT)

    TYPE_UNKNOWN = 0
    TYPE_BOOL = 1
    TYPE_U8 = 2
    TYPE_U16 = 3
    TYPE_U32 = 4
    TYPE_I32 = 5
    TYPE_F32 = 6

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
            return self._parse_connect_ack(data)
        if packet_type == self.TYPE_BUSY_ACK:
            return self._parse_busy_ack(data)
        if packet_type == self.TYPE_LINK_PONG:
            return self._parse_link_pong(data)
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

        magic, version, packet_type, schema_generation, packet_seq, build_us, send_us, item_count = struct.unpack_from(
            self.DATA_HEADER_FMT, data, 0
        )
        expected_size = self.DATA_HEADER_SIZE + item_count * self.DATA_ITEM_SIZE
        if len(data) != expected_size:
            return None

        items = []
        offset = self.DATA_HEADER_SIZE
        for _ in range(item_count):
            signal_no, dt_us, raw = struct.unpack_from(self.DATA_ITEM_FMT, data, offset)
            items.append(
                {
                    "signal_no": signal_no,
                    "dt_us": dt_us,
                    "raw": raw,
                }
            )
            offset += self.DATA_ITEM_SIZE

        return {
            "type": "data",
            "schema_generation": schema_generation,
            "packet_seq": packet_seq,
            "build_us": build_us,
            "send_us": send_us,
            "item_count": item_count,
            "items": items,
        }

    def _parse_schema_response(self, data: bytes):
        if len(data) < self.SCHEMA_RESP_HEADER_SIZE:
            return None

        magic, version, packet_type, schema_generation, section_mask, chunk_index, chunk_total, entry_count = struct.unpack_from(
            self.SCHEMA_RESP_HEADER_FMT, data, 0
        )
        if chunk_total == 0:
            return None

        entries = []
        offset = self.SCHEMA_RESP_HEADER_SIZE
        for _ in range(entry_count):
            if (offset + 8) > len(data):
                return None

            gid, scalar_type, name_len, unit_len, section_len = struct.unpack_from("<IBBBB", data, offset)
            offset += 8

            if (offset + name_len + unit_len + section_len) > len(data):
                return None

            name = data[offset:offset + name_len].decode("utf-8", errors="ignore")
            offset += name_len
            unit = data[offset:offset + unit_len].decode("utf-8", errors="ignore")
            offset += unit_len
            section = data[offset:offset + section_len].decode("utf-8", errors="ignore")
            offset += section_len

            entries.append(
                {
                    "gid": gid,
                    "scalar_type": scalar_type,
                    "name": name,
                    "unit": unit,
                    "section": section or "Other",
                }
            )

        if offset != len(data):
            return None

        return {
            "type": "schema_resp",
            "schema_generation": schema_generation,
            "section_mask": section_mask,
            "chunk_index": chunk_index,
            "chunk_total": chunk_total,
            "entries": entries,
        }

    def _parse_connect_ack(self, data: bytes):
        if len(data) != self.CTRL_HEADER_SIZE:
            return None
        return {"type": "connect_ack"}

    def _parse_link_pong(self, data: bytes):
        if len(data) != self.CTRL_HEADER_SIZE:
            return None
        return {"type": "link_pong"}

    def _parse_busy_ack(self, data: bytes):
        expected = self.CTRL_HEADER_SIZE + self.BUSY_ACK_SIZE
        if len(data) != expected:
            return None
        raw_ip, owner_port = struct.unpack_from(self.BUSY_ACK_FMT, data, self.CTRL_HEADER_SIZE)
        owner_ip = ".".join(str(int(b)) for b in raw_ip)
        return {
            "type": "busy_ack",
            "owner_ip": owner_ip,
            "owner_port": int(owner_port),
        }
