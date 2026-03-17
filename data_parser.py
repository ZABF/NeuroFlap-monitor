import struct
from collections import deque
import time

from crc import Calculator, Configuration


class DataParser:
    def parse_packet(self, data):
        if len(data) < 5 or data[0:2] != b"\xAA\xAA":
            print("Invalid packet: wrong header")
            print(data[0:5])
            return None, None, None, None

        func = data[2]
        data_len = data[3]

        if len(data) != data_len + 5:
            print("Invalid packet: wrong length")
            return None, None, None, None

        try:
            if func == 0x01:
                timestamp, att = self._parse_attitude(data)
                return timestamp, att, None, None,
            elif func == 0x02:
                timestamp, imu = self._parse_imu(data)
                return timestamp, None, imu, None
            elif func == 0xF3:
                timestamp, servo = self._parse_servo(data)
                return timestamp, None, None, servo
            else:
                print("Unknown function code")
        except Exception as e:
            print(f"解析错误: {str(e)}")
        return None, None, None, None

    def _to_value(self, l, h, scale=100.0):
        val = (h << 8) | l
        if val & 0x8000:
            val = -((~val + 1) & 0xFFFF)
        return val / scale

    def _to_unsigned_value(self, low_byte, high_byte):
        """解析无符号数值（16位）"""
        value = (high_byte << 8) | low_byte
        return value

    def to_uint64(self, bytes_list):
        """
        将一个长度为 8 的字节列表（或元组）组合成一个 64 位无符号整数。
        假设 bytes_list[0] 是最低位，bytes_list[7] 是最高位（小端），你也可以改为大端。
        """
        if len(bytes_list) != 8:
            raise ValueError("Expected 8 bytes to form a 64-bit unsigned integer")

        value = 0
        for i in range(8):
            value |= bytes_list[i] << (8 * i)  # 小端序：低字节在前
        return value

    def _parse_attitude(self, d):
        # frame_num = self.to_uint64(d[22:30][::-1])
        # timestamp = frame_num / 1000000  # ms
        frame_num = self._to_unsigned_value(d[23], d[22])
        timestamp = frame_num * 10  # ms
        parse_data = {
            "roll": self._to_value(d[5], d[4]),
            "pitch": self._to_value(d[7], d[6]),
            "yaw": self._to_value(d[9], d[8]),
            "roll_6": self._to_value(d[11], d[10]),
            "pitch_6": self._to_value(d[13], d[12]),
            "yaw_6": self._to_value(d[15], d[14]),
            "roll_Mocap":self._to_value(d[17], d[16]),
            "pitch_Mocap":self._to_value(d[19], d[18]),
            "yaw_Mocap":self._to_value(d[21], d[20]),
        }
        return timestamp, parse_data

    def _parse_servo(self, d):

        i = 4  # 起始位置
        items = []
        items.append(("pwm1", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("ang1", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("pwm2", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("ang2", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("adc", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("freq", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("alt", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("vol", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("Target_posx", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("Target_posy", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("Target_posz", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("RLS_posx", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("RLS_posy", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("RLS_posz", self._to_value(d[i + 1], d[i], 1.0)));i += 2
        items.append(("Target_pitch", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Target_roll", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("RLS_pitch", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("RLS_roll", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Pitch_offset", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Roll_offset", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Pitch_p", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Roll_p", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Left_A", self._to_value(d[i + 1], d[i])));i += 2
        items.append(("Right_A", self._to_value(d[i + 1], d[i])));i += 2
        parse_data = dict(items)
        # timestamp
        frame_num = self._to_unsigned_value(d[i + 1], d[i])
        timestamp = frame_num * 10  # ms
        return timestamp, parse_data

    def _parse_imu(self, d):
        # frame_num = self.to_uint64(d[36:44][::-1])
        # timestamp = frame_num / 1000000  # ms
        frame_num = self._to_unsigned_value(d[37], d[36])
        timestamp = frame_num * 10  # ms
        parse_data = {
            "acc.x": self._to_value(d[5], d[4]),
            "acc.y": self._to_value(d[7], d[6]),
            "acc.z": self._to_value(d[9], d[8]),
            "gyro.x": self._to_value(d[11], d[10]),
            "gyro.y": self._to_value(d[13], d[12]),
            "gyro.z": self._to_value(d[15], d[14]),
            "vx": self._to_value(d[17], d[16]),
            "vy": self._to_value(d[19], d[18]),
            "vz": self._to_value(d[21], d[20]),
            "q0": self._to_value(d[23], d[22]),
            "q1": self._to_value(d[25], d[24]),
            "q2": self._to_value(d[27], d[26]),
            "q3": self._to_value(d[29], d[28]),
            "mx": self._to_value(d[31], d[30]),
            "my": self._to_value(d[33], d[32]),
            "mz": self._to_value(d[35], d[34]),
        }
        return timestamp, parse_data

    def parse_ft_frame(self, data):
        if len(data) != 36:
            return {}
        crc16X25Configuration = Configuration(16, 0x1021, 0xFFFF, 0xFFFF, True, True)
        crc_calc = Calculator(crc16X25Configuration)
        payload = data[:34]
        recv_crc = struct.unpack_from('<H', data, 34)[0]
        calc_crc = crc_calc.checksum(payload)
        if recv_crc != calc_crc:
            return {}

        timestamp = struct.unpack_from('I', data, 26)[0] / 1000.0  # ms
        parse_data = {
            "F_X": round(struct.unpack_from('f', data, 2)[0], 4),
            "F_Y": round(struct.unpack_from('f', data, 6)[0], 4),
            "F_Z": round(struct.unpack_from('f', data, 10)[0], 4),
            "T_X": round(struct.unpack_from('f', data, 14)[0], 4),
            "T_Y": round(struct.unpack_from('f', data, 18)[0], 4),
            "T_Z": round(struct.unpack_from('f', data, 22)[0], 4),
        }
        return timestamp, parse_data

    def parse_mocap_frame(self, frame, rigid_id, wing1_id, wing2_id):
        CameraSyncTime = frame.uCameraSyncTime / 1000.0  # ms
        BroadcastTime = frame.uBroadcastTime / 1000.0  # ms
        mocap_data = {}
        # ====== Marker 解析 ======
        for marker in frame.markers:
            if marker.Name in( f"{rigid_id}Marker{marker.Id}",f"{wing1_id}Marker{marker.Id}",f"{wing2_id}Marker{marker.Id}"):
                mocap_data[f"{marker.Name}_X"] = marker.X
                mocap_data[f"{marker.Name}_Y"] = marker.Y
                mocap_data[f"{marker.Name}_Z"] = marker.Z

        # ====== Rigid 解析 ======
        for rigid in frame.rigidBodys:
            if rigid.IsTrack: #判断刚体追踪状态
                if rigid.Name == rigid_id:
                    pre  = "Mocap"
                elif rigid.Name == wing1_id:
                    pre  = "Wing1"
                elif rigid.Name == wing2_id:
                    pre  = "Wing2"
                else:
                    continue

                mocap_data.update({
                    # 位置与姿态
                    f"{pre}_X": rigid.X,
                    f"{pre}_Y": rigid.Y,
                    f"{pre}_Z": rigid.Z,
                    f"{pre}_qx": rigid.qx,
                    f"{pre}_qy": rigid.qy,
                    f"{pre}_qz": rigid.qz,
                    f"{pre}_qw": rigid.qw,
                    f"{pre}_roll": rigid.eulerAngle.X,
                    f"{pre}_pitch": rigid.eulerAngle.Y,
                    f"{pre}_yaw": rigid.eulerAngle.Z,

                    # 速度
                    f"{pre}_Speed": rigid.speeds.fSpeed,
                    f"{pre}_SpeedX": rigid.speeds.XfSpeed,
                    f"{pre}_SpeedY": rigid.speeds.YfSpeed,
                    f"{pre}_SpeedZ": rigid.speeds.ZfSpeed,

                    # 加速度
                    f"{pre}_Acc": rigid.acceleratedSpeeds.fAcceleratedSpeed,
                    f"{pre}_AccX": rigid.acceleratedSpeeds.XfAcceleratedSpeed,
                    f"{pre}_AccY": rigid.acceleratedSpeeds.YfAcceleratedSpeed,
                    f"{pre}_AccZ": rigid.acceleratedSpeeds.ZfAcceleratedSpeed,

                    # 角速度
                    f"{pre}_AVX": rigid.palstance.fXPalstance,
                    f"{pre}_AVY": rigid.palstance.fYPalstance,
                    f"{pre}_AVZ": rigid.palstance.fZPalstance,

                    # 角加速度
                    f"{pre}_AAX": rigid.accpalstance.AccfXPalstance,
                    f"{pre}_AAY": rigid.accpalstance.AccfYPalstance,
                    f"{pre}_AAZ": rigid.accpalstance.AccfZPalstance,

                    # 质量等级
                    f"{pre}_Quality": rigid.QualityGrade,
                })

        return CameraSyncTime, mocap_data
