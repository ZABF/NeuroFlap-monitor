import argparse
import math
import socket
import struct
import threading
import time


MAGIC = 0x464E
VERSION = 2

TYPE_DATA = 0x01
TYPE_SCHEMA_REQ = 0x10
TYPE_SCHEMA_RESP = 0x11

TYPE_BOOL = 1
TYPE_U8 = 2
TYPE_U16 = 3
TYPE_U32 = 4
TYPE_I32 = 5
TYPE_F32 = 6

DATA_HEADER_FMT = "<HBBIIQQH"
DATA_ITEM_FMT = "<BHI"
SCHEMA_REQ_FMT = "<HBBI"
SCHEMA_RESP_HEADER_FMT = "<HBBIIHHH"
SCHEMA_ENTRY_PREFIX_FMT = "<IBBBB"

MAX_PAYLOAD = 1200


def f32_to_raw(value):
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def u16_to_raw(value):
    return int(value) & 0xFFFF


def u32_to_raw(value):
    return int(value) & 0xFFFFFFFF


def bool_to_raw(value):
    return 1 if value else 0


def make_gid(section, signal_id):
    return ((int(section) & 0xFFFF) << 16) | (int(signal_id) & 0xFFFF)


class NFv3UdpSimulator:
    def __init__(self, bind_ip, bind_port, target_ip, target_port, period_ms, duration_s=None, chunk_size=0):
        self.bind_ip = bind_ip
        self.bind_port = int(bind_port)
        self.target = (target_ip, int(target_port))
        self.period_s = max(0.001, float(period_ms) / 1000.0)
        self.duration_s = float(duration_s) if duration_s is not None else None
        self.chunk_size = int(chunk_size)
        self.sock = None
        self.stop_event = threading.Event()
        self.schema_generation = 1
        self.section_mask = 0xFFFFFFFF
        self.packet_seq = 0
        self.send_count = 0
        self.last_stat_ts = time.time()
        self.last_raw_by_signal_no = {}

        # GID stays stable as (section << 16) | id; DATA signal_no follows schema order.
        self.schema = [
            {"gid": make_gid(1, 10), "type": TYPE_F32, "name": "roll_6", "unit": "deg", "section": "Att"},
            {"gid": make_gid(1, 11), "type": TYPE_F32, "name": "pitch", "unit": "deg", "section": "Att"},
            {"gid": make_gid(1, 12), "type": TYPE_F32, "name": "yaw", "unit": "deg", "section": "Att"},
            {"gid": make_gid(0, 20), "type": TYPE_U16, "name": "pwm1", "unit": "us", "section": "Actuator"},
            {"gid": make_gid(0, 21), "type": TYPE_U16, "name": "pwm2", "unit": "us", "section": "Actuator"},
            {"gid": make_gid(4, 30), "type": TYPE_U32, "name": "loop_hz", "unit": "hz", "section": "Control"},
            {"gid": make_gid(4, 31), "type": TYPE_BOOL, "name": "armed", "unit": "", "section": "Control"},
        ]

    def _build_schema_chunks(self):
        chunks = []
        current_entries = []
        current_size = struct.calcsize(SCHEMA_RESP_HEADER_FMT)

        for entry in self.schema:
            name_bytes = entry["name"].encode("utf-8")
            unit_bytes = entry["unit"].encode("utf-8")
            section_bytes = entry["section"].encode("utf-8")
            entry_size = struct.calcsize(SCHEMA_ENTRY_PREFIX_FMT) + len(name_bytes) + len(unit_bytes) + len(section_bytes)
            if entry_size > (MAX_PAYLOAD - struct.calcsize(SCHEMA_RESP_HEADER_FMT)):
                raise ValueError("schema entry too large for one UDP packet")

            if current_entries and (current_size + entry_size > MAX_PAYLOAD):
                chunks.append(current_entries)
                current_entries = []
                current_size = struct.calcsize(SCHEMA_RESP_HEADER_FMT)

            current_entries.append((entry, name_bytes, unit_bytes, section_bytes))
            current_size += entry_size

        if current_entries or not chunks:
            chunks.append(current_entries)

        packets = []
        chunk_total = len(chunks)
        for chunk_index, chunk in enumerate(chunks):
            packet = bytearray(
                struct.pack(
                    SCHEMA_RESP_HEADER_FMT,
                    MAGIC,
                    VERSION,
                    TYPE_SCHEMA_RESP,
                    self.schema_generation & 0xFFFFFFFF,
                    self.section_mask & 0xFFFFFFFF,
                    chunk_index,
                    chunk_total,
                    len(chunk),
                )
            )
            for entry, name_bytes, unit_bytes, section_bytes in chunk:
                packet.extend(
                    struct.pack(
                        SCHEMA_ENTRY_PREFIX_FMT,
                        entry["gid"],
                        entry["type"],
                        len(name_bytes),
                        len(unit_bytes),
                        len(section_bytes),
                    )
                )
                packet.extend(name_bytes)
                packet.extend(unit_bytes)
                packet.extend(section_bytes)
            packets.append(bytes(packet))
        return packets

    def _send_schema_response(self, remote_addr):
        packets = self._build_schema_chunks()
        for packet in packets:
            self.sock.sendto(packet, remote_addr)
        print(f"[schema] response sent to {remote_addr[0]}:{remote_addr[1]}, chunks={len(packets)}")

    def _try_handle_control_packets(self):
        while True:
            try:
                data, remote_addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                return
            except OSError:
                return

            if len(data) != struct.calcsize(SCHEMA_REQ_FMT):
                continue

            magic, version, packet_type, request_id = struct.unpack(SCHEMA_REQ_FMT, data)
            if magic != MAGIC or version != VERSION or packet_type != TYPE_SCHEMA_REQ:
                continue

            print(f"[schema] request from {remote_addr[0]}:{remote_addr[1]}, request_id={request_id}")
            self._send_schema_response(remote_addr)

    def _build_data_packets(self, now_s):
        build_us = time.monotonic_ns() // 1000
        send_us = build_us

        roll = 30.0 * math.sin(2.0 * math.pi * 0.5 * now_s)
        pitch = 20.0 * math.cos(2.0 * math.pi * 0.6 * now_s)
        yaw = 90.0 * math.sin(2.0 * math.pi * 0.2 * now_s)
        pwm1 = 1500 + int(200 * math.sin(2.0 * math.pi * 2.0 * now_s))
        pwm2 = 1500 + int(200 * math.cos(2.0 * math.pi * 2.0 * now_s))
        loop_hz = 1000
        armed = (int(now_s) % 4) < 2

        values = [
            (0, f32_to_raw(roll)),
            (1, f32_to_raw(pitch)),
            (2, f32_to_raw(yaw)),
            (3, u16_to_raw(pwm1)),
            (4, u16_to_raw(pwm2)),
            (5, u32_to_raw(loop_hz)),
            (6, bool_to_raw(armed)),
        ]

        changed_values = []
        for signal_no, raw in values:
            last_raw = self.last_raw_by_signal_no.get(signal_no)
            if last_raw is not None and last_raw == raw:
                continue
            self.last_raw_by_signal_no[signal_no] = raw
            changed_values.append((signal_no, raw))

        if not changed_values:
            return []

        if self.chunk_size > 0:
            chunk_size = self.chunk_size
        else:
            chunk_size = len(changed_values)

        packets = []
        for offset in range(0, len(changed_values), chunk_size):
            chunk = changed_values[offset:offset + chunk_size]
            packet = bytearray(
                struct.pack(
                    DATA_HEADER_FMT,
                    MAGIC,
                    VERSION,
                    TYPE_DATA,
                    self.schema_generation & 0xFFFFFFFF,
                    self.packet_seq & 0xFFFFFFFF,
                    build_us & 0xFFFFFFFFFFFFFFFF,
                    send_us & 0xFFFFFFFFFFFFFFFF,
                    len(chunk),
                )
            )
            for signal_no, raw in chunk:
                packet.extend(
                    struct.pack(
                        DATA_ITEM_FMT,
                        signal_no & 0xFF,
                        0,
                        raw & 0xFFFFFFFF,
                    )
                )

            packets.append(bytes(packet))
            self.packet_seq = (self.packet_seq + 1) & 0xFFFFFFFF

        return packets

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((self.bind_ip, self.bind_port))
        except OSError as exc:
            # Common on Windows when previous process still owns the port.
            if getattr(exc, "winerror", None) == 10048:
                print(
                    f"[warn] bind {self.bind_ip}:{self.bind_port} failed (in use), "
                    "fallback to ephemeral port."
                )
                self.sock.bind((self.bind_ip, 0))
                self.bind_port = int(self.sock.getsockname()[1])
            else:
                raise
        self.sock.setblocking(False)

        print(
            f"NFv3 simulator started: bind={self.bind_ip}:{self.bind_port}, "
            f"target={self.target[0]}:{self.target[1]}, period={self.period_s * 1000:.1f}ms"
        )
        print("Press Ctrl+C to stop.")

        start = time.monotonic()
        next_send = start
        while not self.stop_event.is_set():
            if self.duration_s is not None and (time.monotonic() - start) >= self.duration_s:
                self.stop_event.set()
                continue

            self._try_handle_control_packets()

            now = time.monotonic()
            if now >= next_send:
                elapsed = now - start
                packets = self._build_data_packets(elapsed)
                for packet in packets:
                    self.sock.sendto(packet, self.target)
                    self.send_count += 1
                next_send += self.period_s

            wall_now = time.time()
            if wall_now - self.last_stat_ts >= 1.0:
                print(f"[data] sent_packets={self.send_count}, next_seq={self.packet_seq}")
                self.last_stat_ts = wall_now

            time.sleep(0.001)

        try:
            self.sock.close()
        except OSError:
            pass
        print("NFv3 simulator stopped.")


def main():
    parser = argparse.ArgumentParser(description="NFv3 UDP simulator for NeuroFlap monitor")
    parser.add_argument("--bind-ip", default="0.0.0.0", help="local bind ip")
    parser.add_argument("--bind-port", type=int, default=28090, help="local bind port")
    parser.add_argument("--target-ip", default="127.0.0.1", help="monitor udp listen ip")
    parser.add_argument("--target-port", type=int, default=28080, help="monitor udp listen port")
    parser.add_argument("--period-ms", type=float, default=20.0, help="DATA send period in ms")
    parser.add_argument("--duration-s", type=float, default=None, help="optional run duration in seconds")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="DATA items per packet; 0 means all items in one packet",
    )
    args = parser.parse_args()

    sim = NFv3UdpSimulator(
        bind_ip=args.bind_ip,
        bind_port=args.bind_port,
        target_ip=args.target_ip,
        target_port=args.target_port,
        period_ms=args.period_ms,
        duration_s=args.duration_s,
        chunk_size=args.chunk_size,
    )

    try:
        sim.run()
    except KeyboardInterrupt:
        sim.stop_event.set()


if __name__ == "__main__":
    main()
