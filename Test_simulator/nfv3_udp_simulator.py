import argparse
import math
import socket
import struct
import threading
import time


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
DEFAULT_TIMESTAMP_GROUP = 0xFF

TYPE_BOOL = 1
TYPE_U16 = 3
TYPE_F32 = 6

DATA_HEADER_FMT = "<HBBIIQHH"
TASK_FRAME_HEADER_FMT = "<HBII"
NODE_FRAME_FMT = "<HBII"
SCHEMA_REQ_FMT = "<HBBI"
SCHEMA_RESP_HEADER_FMT = "<HBBIHHHH"
SCHEMA_ENTRY_HEADER_FMT = "<BH"
CTRL_HEADER_FMT = "<HBB"
MAX_PAYLOAD = 1200


def f32_to_raw(value):
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def schema_entry(kind, payload):
    return struct.pack(SCHEMA_ENTRY_HEADER_FMT, kind, len(payload)) + payload


class NFv3UdpSimulator:
    def __init__(self, bind_ip, bind_port, period_ms, duration_s=None):
        self.bind_ip = bind_ip
        self.bind_port = int(bind_port)
        self.period_s = max(0.001, float(period_ms) / 1000.0)
        self.duration_s = float(duration_s) if duration_s is not None else None
        self.sock = None
        self.stop_event = threading.Event()
        self.schema_generation = 1
        self.packet_seq = 0
        self.send_count = 0
        self.last_stat_ts = time.time()
        self.active_client = None
        self.schema_entries = self._make_schema_entries()

    def _make_schema_entries(self):
        task_name = b"SimTask"
        task = schema_entry(
            SCHEMA_KIND_TASK,
            struct.pack("<HBBBBB", 5, 2, 2, 0, 1, len(task_name)) + task_name,
        )

        def port(direction, slot, scalar_type, timestamp_group, name, unit=b""):
            name = name.encode()
            payload = struct.pack(
                "<HBBBBBB",
                5,
                direction,
                slot,
                scalar_type,
                timestamp_group,
                len(name),
                len(unit),
            ) + name + unit
            return schema_entry(SCHEMA_KIND_TASK_PORT, payload)

        group = b"sim"
        node_name = b"armed"
        node_payload = struct.pack(
            "<HHBBBB",
            0,
            1,
            TYPE_BOOL,
            len(group),
            len(node_name),
            0,
        ) + group + node_name
        return [
            task,
            port(PORT_INPUT, 0, TYPE_F32, DEFAULT_TIMESTAMP_GROUP, "roll", b"deg"),
            port(PORT_INPUT, 1, TYPE_F32, DEFAULT_TIMESTAMP_GROUP, "pitch", b"deg"),
            port(PORT_OUTPUT, 0, TYPE_U16, DEFAULT_TIMESTAMP_GROUP, "pwm_left", b"us"),
            port(PORT_OUTPUT, 1, TYPE_U16, 0, "pwm_right", b"us"),
            schema_entry(SCHEMA_KIND_DATA_NODE, node_payload),
        ]

    def _schema_packets(self):
        chunks = []
        current = []
        current_size = struct.calcsize(SCHEMA_RESP_HEADER_FMT)
        for entry in self.schema_entries:
            if current and current_size + len(entry) > MAX_PAYLOAD:
                chunks.append(current)
                current = []
                current_size = struct.calcsize(SCHEMA_RESP_HEADER_FMT)
            current.append(entry)
            current_size += len(entry)
        chunks.append(current)

        packets = []
        for chunk_index, chunk in enumerate(chunks):
            header = struct.pack(
                SCHEMA_RESP_HEADER_FMT,
                MAGIC,
                VERSION,
                TYPE_SCHEMA_RESP,
                self.schema_generation,
                chunk_index,
                len(chunks),
                len(chunk),
                len(self.schema_entries),
            )
            packets.append(header + b"".join(chunk))
        return packets

    def _send_control(self, packet_type, remote_addr):
        self.sock.sendto(struct.pack(CTRL_HEADER_FMT, MAGIC, VERSION, packet_type), remote_addr)

    def _handle_packets(self):
        while True:
            try:
                data, remote_addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                return
            except OSError:
                return
            if len(data) < 4:
                continue
            magic, version, packet_type = struct.unpack_from(CTRL_HEADER_FMT, data)
            if magic != MAGIC or version != VERSION:
                continue

            if packet_type == TYPE_CONNECT_REQ:
                if self.active_client is None or self.active_client == remote_addr:
                    self.active_client = remote_addr
                    self._send_control(TYPE_CONNECT_ACK, remote_addr)
                    print(f"[link] connected {remote_addr[0]}:{remote_addr[1]}")
                else:
                    owner_ip = socket.inet_aton(self.active_client[0])
                    busy = struct.pack(CTRL_HEADER_FMT, MAGIC, VERSION, TYPE_BUSY_ACK)
                    busy += struct.pack("<4sH", owner_ip, self.active_client[1])
                    self.sock.sendto(busy, remote_addr)
                continue

            if remote_addr != self.active_client:
                continue
            if packet_type == TYPE_LINK_PING:
                self._send_control(TYPE_LINK_PONG, remote_addr)
            elif packet_type == TYPE_DISCONNECT_REQ:
                self.active_client = None
                print("[link] disconnected")
            elif packet_type == TYPE_SCHEMA_REQ and len(data) == struct.calcsize(SCHEMA_REQ_FMT):
                request_id = struct.unpack(SCHEMA_REQ_FMT, data)[3]
                for packet in self._schema_packets():
                    self.sock.sendto(packet, remote_addr)
                print(f"[schema] request_id={request_id}, entries={len(self.schema_entries)}")

    def _data_packet(self, elapsed_s):
        packet_time_us = time.monotonic_ns() // 1000
        roll = 30.0 * math.sin(2.0 * math.pi * 0.5 * elapsed_s)
        pitch = 20.0 * math.cos(2.0 * math.pi * 0.6 * elapsed_s)
        pwm_left = 1500 + int(200 * math.sin(2.0 * math.pi * 2.0 * elapsed_s))
        pwm_right = 1500 + int(200 * math.cos(2.0 * math.pi * 2.0 * elapsed_s))
        armed = (int(elapsed_s) % 4) < 2

        header = struct.pack(
            DATA_HEADER_FMT,
            MAGIC,
            VERSION,
            TYPE_DATA,
            self.schema_generation,
            self.packet_seq,
            packet_time_us,
            1,
            1,
        )
        flags = 0x07
        task = struct.pack(TASK_FRAME_HEADER_FMT, 5, flags, 100, 50)
        task += struct.pack(
            "<IIII",
            f32_to_raw(roll),
            f32_to_raw(pitch),
            pwm_left & 0xFFFF,
            pwm_right & 0xFFFF,
        )
        task += struct.pack("<I", 25)
        node = struct.pack(NODE_FRAME_FMT, 0, 1, 10, 1 if armed else 0)
        self.packet_seq = (self.packet_seq + 1) & 0xFFFFFFFF
        return header + task + node

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, self.bind_port))
        self.sock.setblocking(False)
        print(
            f"NFv3 simulator listening on {self.bind_ip}:{self.bind_port}, "
            f"period={self.period_s * 1000:.1f}ms"
        )

        start = time.monotonic()
        next_send = start
        while not self.stop_event.is_set():
            if self.duration_s is not None and time.monotonic() - start >= self.duration_s:
                break
            self._handle_packets()
            now = time.monotonic()
            if self.active_client is not None and now >= next_send:
                self.sock.sendto(self._data_packet(now - start), self.active_client)
                self.send_count += 1
                next_send = now + self.period_s
            elif self.active_client is None:
                next_send = now

            if time.time() - self.last_stat_ts >= 1.0:
                print(f"[data] client={self.active_client}, sent_packets={self.send_count}")
                self.last_stat_ts = time.time()
            time.sleep(0.001)

        self.sock.close()
        print("NFv3 simulator stopped")


def main():
    parser = argparse.ArgumentParser(description="Compact NFv3 UDP simulator")
    parser.add_argument("--bind-ip", default="0.0.0.0")
    parser.add_argument("--bind-port", type=int, default=28090)
    parser.add_argument("--period-ms", type=float, default=20.0)
    parser.add_argument("--duration-s", type=float, default=None)
    args = parser.parse_args()
    simulator = NFv3UdpSimulator(args.bind_ip, args.bind_port, args.period_ms, args.duration_s)
    try:
        simulator.run()
    except KeyboardInterrupt:
        simulator.stop_event.set()


if __name__ == "__main__":
    main()
