from PyQt5.QtCore import QThread, pyqtSignal
import time
import csv
import socket
import struct
from datetime import datetime
import argparse
import LuMoSDKClient
import matplotlib.pyplot as plt
import pandas as pd
from CustomFunc import (
    set_professional_plotting_style, load_data,
    plot_3d_velocity, plot_2d_projections,
    plot_euler_angles, plot_velocity_components
)

class LuMo2EspSender:
    def __init__(self,
                 sdk_ip='172.16.23.64',
                 esp32_ip='172.16.23.10',
                 esp32_port=28090,
                 rigid_id='Rigid_WingLite_R_MainRod'):

        self.sdk_ip = sdk_ip
        self.esp32_ip = esp32_ip
        self.esp32_port = esp32_port
        self.rigid_id = rigid_id
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_filename = f"{self.timestamp}_motion_data.csv"
        self.csv_file = open(self.csv_filename, 'w', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        self.write_csv_header()
        set_professional_plotting_style()


    def send_udp_message(self, rigid):
        func_code = 0x01 if rigid.Name == self.rigid_id else 0x02
        payload = [
            int(rigid.Id), int(rigid.QualityGrade),
            rigid.X, rigid.Y, rigid.Z,
            rigid.qx, rigid.qy, rigid.qz, rigid.qw,
            rigid.speeds.fSpeed, rigid.speeds.XfSpeed, rigid.speeds.YfSpeed, rigid.speeds.ZfSpeed,
            rigid.acceleratedSpeeds.fAcceleratedSpeed,
            rigid.acceleratedSpeeds.XfAcceleratedSpeed, rigid.acceleratedSpeeds.YfAcceleratedSpeed, rigid.acceleratedSpeeds.ZfAcceleratedSpeed,
            rigid.eulerAngle.X, rigid.eulerAngle.Y, rigid.eulerAngle.Z,
            rigid.palstance.fXPalstance, rigid.palstance.fYPalstance, rigid.palstance.fZPalstance,
            rigid.accpalstance.AccfXPalstance, rigid.accpalstance.AccfYPalstance, rigid.accpalstance.AccfZPalstance
        ]
        fmt = '!BBii' + 'f' * (len(payload) - 2)
        packed_data = struct.pack(fmt, 0xBB, func_code, payload[0], payload[1], *payload[2:])
        self.udp_sock.sendto(packed_data, (self.esp32_ip, self.esp32_port))

    def run(self):
        LuMoSDKClient.Init()
        LuMoSDKClient.Connnect(self.sdk_ip)
        try:
            while True:
                frame = LuMoSDKClient.ReceiveData(0)
                if frame is None:
                    continue

                base = [frame.FrameId, frame.TimeStamp, frame.uCameraSyncTime, frame.uBroadcastTime]

                for marker in frame.markers:
                    self.csv_writer.writerow(base + [marker.Id, marker.Name, marker.X, marker.Y, marker.Z] + [None]*28)
                    self.csv_file.flush()

                for rigid in frame.rigidBodys:
                    if rigid.IsTrack:
                        data = base + [None]*5 + [
                            rigid.Id, rigid.Name, rigid.X, rigid.Y, rigid.Z,
                            rigid.qx, rigid.qy, rigid.qz, rigid.qw, rigid.QualityGrade,
                            rigid.speeds.fSpeed, rigid.speeds.XfSpeed, rigid.speeds.YfSpeed, rigid.speeds.ZfSpeed,
                            rigid.acceleratedSpeeds.fAcceleratedSpeed, rigid.acceleratedSpeeds.XfAcceleratedSpeed,
                            rigid.acceleratedSpeeds.YfAcceleratedSpeed, rigid.acceleratedSpeeds.ZfAcceleratedSpeed,
                            rigid.eulerAngle.X, rigid.eulerAngle.Y, rigid.eulerAngle.Z,
                            rigid.palstance.fXPalstance, rigid.palstance.fYPalstance, rigid.palstance.fZPalstance,
                            rigid.accpalstance.AccfXPalstance, rigid.accpalstance.AccfYPalstance, rigid.accpalstance.AccfZPalstance
                        ]
                        self.csv_writer.writerow(data)
                        self.csv_file.flush()
                        self.send_udp_message(rigid)
        except KeyboardInterrupt:
            print("Interrupted. Saving figures...")
            self.generate_figures()
        finally:
            self.cleanup()

    def generate_figures(self):
        df = load_data(self.csv_filename)
        fig1 = plot_3d_velocity(df, rigid_body_name=self.rigid_id, figsize=(6, 5))
        fig2 = plot_2d_projections(df, rigid_body_name=self.rigid_id, figsize=(7, 2.5))
        fig3 = plot_velocity_components(df, rigid_body_name=self.rigid_id, figsize=(7, 2.5))
        fig4 = plot_euler_angles(df, rigid_body_name=self.rigid_id, figsize=(7, 3.5))

        fig1.savefig(f'{self.timestamp}_3d_trajectory.png', bbox_inches='tight', pad_inches=0.1)
        fig2.savefig(f'{self.timestamp}_2d_projections.png', bbox_inches='tight', pad_inches=0.1)
        fig3.savefig(f'{self.timestamp}_velocity_components.png', bbox_inches='tight', pad_inches=0.05)
        fig4.savefig(f'{self.timestamp}_euler_angles.png', bbox_inches='tight', dpi=300, pad_inches=0.1)
        plt.show()

    def cleanup(self):
        self.csv_file.close()
        LuMoSDKClient.Close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk_ip', type=str, default='172.16.23.64')
    parser.add_argument('--esp32_ip', type=str, default='192.168.236.44')
    parser.add_argument('--esp32_port', type=int, default=28090)
    parser.add_argument('--rigid_id', type=str, default='Rigid_WingLite_R_MainRod')
    args = parser.parse_args()

    app = LuMoMotionCaptureLogger(
        sdk_ip=args.sdk_ip,
        esp32_ip=args.esp32_ip,
        esp32_port=args.esp32_port,
        rigid_id=args.rigid_id
    )
    app.run()
