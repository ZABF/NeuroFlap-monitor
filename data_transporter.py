# data_transporter.py
import socket
import struct


class DataTransporter:
    def __init__(self, ip="172.16.23.13", port=28090):
        self.esp32_ip = ip
        self.esp32_port = port
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def udp_send_mocap_message(self, rigid_data):
        """
        将 rigid 数据结构打包并通过UDP发送到ESP32
        """
        frame_header = 0xBB

        func_code = 0x01

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
        packed_data = struct.pack(fmt, frame_header, func_code, payload[0], payload[1], *payload[2:])

        try:
            self.udp_sock.sendto(packed_data, (self.esp32_ip, self.esp32_port))
            print("data_transport.py: Send UDP packet to {}:{} ".format(self.esp32_ip,esp32_port))

        except Exception as e:
            print(f"[UDP ERROR] Failed to send mocap data: {e}")

