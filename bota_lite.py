import serial
import struct
import time

class BotaSerialSensor:
    # 保留基本配置参数
    BAUDERATE = 460800
    FRAME_HEADER = b'\xAA'
    
    def __init__(self, port):
        self._port = port
        self._ser = serial.Serial()
        # 基本数据存储
        # self._fx = 0.0
        # self._fy = 0.0
        # self._fz = 0.0
        # self._mx = 0.0
        # self._my = 0.0
        # self._mz = 0.0
        # self._temperature = 0.0

    def setup(self, sinc_length=4):
        """基本设置，并配置采样频率（sinc_length）"""
        self._ser.baudrate = self.BAUDERATE
        self._ser.port = self._port
        self._ser.timeout = 10
        try:
            self._ser.open()
            print(f"已打开串口 {self._port}")
            # 等待传感器初始化
            self._ser.read_until(b'App Init')
            time.sleep(0.5)
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
            print(f"已初始化")
            # 进入配置模式
            self._ser.write(b'C')
            self._ser.read_until(b'r,0,C,0')
            print(f"已进入配置模式")
            # 配置滤波参数（采样频率由sinc_length决定）
            filter_setup = f"f,{sinc_length},0,0,1"
            self._ser.write(filter_setup.encode('ascii'))
            self._ser.read_until(b'r,0,f,0')
            print(f"已配置")
            # 进入运行模式
            self._ser.write(b'R')
            self._ser.read_until(b'r,0,R,0')
            print(f"已设置采样频率参数 sinc_length={sinc_length}")
            return True
        except Exception as e:
            print(f"无法打开串口或配置失败: {e}")
            return False

    def read_data(self):
        """读取一帧数据"""
        try:
            # 等待帧头
            header = self._ser.read(1)
            if header != self.FRAME_HEADER:
                return None
                
            # 读取数据
            data_frame = self._ser.read(34)
            
            # 解析数据
            self._fx = struct.unpack_from('f', data_frame, 2)[0]
            self._fy = struct.unpack_from('f', data_frame, 6)[0]
            self._fz = struct.unpack_from('f', data_frame, 10)[0]
            self._mx = struct.unpack_from('f', data_frame, 14)[0]
            self._my = struct.unpack_from('f', data_frame, 18)[0]
            self._mz = struct.unpack_from('f', data_frame, 22)[0]
            self._temperature = struct.unpack_from('f', data_frame, 30)[0]
            
            return {
                'fx': self._fx,
                'fy': self._fy,
                'fz': self._fz,
                'mx': self._mx,
                'my': self._my,
                'mz': self._mz,
                'temperature': self._temperature
            }
            
        except Exception as e:
            print(f"读取数据错误: {str(e)}")
            return None

    def close(self):
        """关闭连接"""
        if self._ser.is_open:
            self._ser.close()

# 使用示例
if __name__ == '__main__':
    sensor = BotaSerialSensor('COM3')
    if sensor.setup():
        try:
            while True:
                data = sensor.read_data()
                if data:
                    print(f"力: {data['fx']:.2f}, {data['fy']:.2f}, {data['fz']:.2f}")
                    print(f"力矩: {data['mx']:.2f}, {data['my']:.2f}, {data['mz']:.2f}")
                time.sleep(0.1)
        except KeyboardInterrupt:
            print('已停止')
        finally:
            sensor.close()