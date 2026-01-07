# data_transporter.py
import socket
import struct
import threading
import queue

class DataTransporterThread(threading.Thread):
    def __init__(self, ip="172.16.23.13", port=28090):
        super().__init__(daemon=True)
        self.esp32_ip = ip
        self.esp32_port = port
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_queue = queue.Queue()
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            try:
                rigid_data = self.send_queue.get(timeout=0.1)
                self._send_udp_message(rigid_data)
            except queue.Empty:
                continue

    def stop(self):
        self.running = False

    def enqueue(self, rigid_data):
        """放入一个刚体数据，准备异步发送"""
        if self.running:
            self.send_queue.put(rigid_data)

    def _send_udp_message(self, rigid_data):
        """打包并发送刚体数据"""
        frame_header = 0xBB
        func_code = 0x01  # 可改为动态选择

        payload = [
            int(rigid_data.Id),
            int(rigid_data.QualityGrade),
            float(rigid_data.X),
            float(rigid_data.Y),
            float(rigid_data.Z),
            float(rigid_data.qx),
            float(rigid_data.qy),
            float(rigid_data.qz),
            float(rigid_data.qw),
            float(rigid_data.speeds.fSpeed),
            float(rigid_data.speeds.XfSpeed),
            float(rigid_data.speeds.YfSpeed),
            float(rigid_data.speeds.ZfSpeed),
            float(rigid_data.acceleratedSpeeds.fAcceleratedSpeed),
            float(rigid_data.acceleratedSpeeds.XfAcceleratedSpeed),
            float(rigid_data.acceleratedSpeeds.YfAcceleratedSpeed),
            float(rigid_data.acceleratedSpeeds.ZfAcceleratedSpeed),
            float(rigid_data.eulerAngle.X),
            float(rigid_data.eulerAngle.Y),
            float(rigid_data.eulerAngle.Z),
            float(rigid_data.palstance.fXPalstance),
            float(rigid_data.palstance.fYPalstance),
            float(rigid_data.palstance.fZPalstance),
            float(rigid_data.accpalstance.AccfXPalstance),
            float(rigid_data.accpalstance.AccfYPalstance),
            float(rigid_data.accpalstance.AccfZPalstance),
        ]

        fmt = '!BBii' + 'f' * (len(payload) - 2)
        try:
            packed_data = struct.pack(fmt, frame_header, func_code, payload[0], payload[1], *payload[2:])
            self.udp_sock.sendto(packed_data, (self.esp32_ip, self.esp32_port))
        except Exception as e:
            print(f"[UDP ERROR] Failed to send mocap data: {e}")
