import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R
import sys

# Kalman Filter functions
class EKF:
    def __init__(self):
        self.x = np.zeros(4)  # Quaternion state [qx, qy, qz, qw]
        self.P = np.eye(4)   # State covariance
        self.Q = np.eye(4) * 0.01  # Process noise
        self.R = np.eye(4) * 0.1   # Measurement noise

    def predict(self):
        self.P = self.P + self.Q

    def update(self, z):
        y = z - self.x
        S = self.P + self.R
        K = self.P @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K) @ self.P

    def get_state(self):
        return self.x / np.linalg.norm(self.x)

# Quaternion normalization
def normalize_quaternion(quat):
    norm = np.linalg.norm(quat, axis=1, keepdims=True)
    norm[norm == 0] = 1
    return quat / norm

# Load data
if len(sys.argv) != 3:
    print("Usage: python ekf_fusion.py mocap.csv imu.csv")
    sys.exit(1)

mocap_file, imu_file = sys.argv[1], sys.argv[2]
mocap_data = pd.read_csv(mocap_file)
imu_data = pd.read_csv(imu_file)

mocap_data['UnixTime'] = pd.to_datetime(mocap_data['BroadcastTime'], unit='us')
imu_data['UnixTime'] = pd.to_datetime(imu_data['time_y'], unit='ns')

if mocap_data['UnixTime'].iloc[0] < imu_data['UnixTime'].iloc[0]:
    mocap_data = mocap_data[mocap_data['UnixTime'] >= imu_data['UnixTime'].iloc[0]].reset_index(drop=True)

imu_start_time = imu_data['UnixTime'].iloc[0]
mocap_data['RelativeTime'] = (mocap_data['UnixTime'] - imu_start_time).dt.total_seconds()
imu_data['RelativeTime'] = imu_data['roll_x'] / 1000

# Normalize quaternions
mocap_quats = normalize_quaternion(mocap_data[['qx', 'qy', 'qz', 'qw']].values)
mocap_data[['qx', 'qy', 'qz', 'qw']] = mocap_quats
imu_quats = normalize_quaternion(imu_data[['q0_y', 'q1_y', 'q2_y', 'q3_y']].values)
imu_data[['q0_y', 'q1_y', 'q2_y', 'q3_y']] = imu_quats

# Apply EKF
ekf = EKF()
filtered_quats = []

for i in range(len(mocap_quats)):
    ekf.predict()
    ekf.update(mocap_quats[i])
    filtered_quats.append(ekf.get_state())

filtered_quats = np.array(filtered_quats)
mocap_data[['qx_kf', 'qy_kf', 'qz_kf', 'qw_kf']] = filtered_quats

# Convert to Euler angles
def quat_to_euler(q):
    r = R.from_quat(q)
    return r.as_euler('xyz', degrees=True)

mocap_data[['Roll_KF', 'Pitch_KF', 'Yaw_KF']] = np.apply_along_axis(quat_to_euler, 1, filtered_quats)

# Plot EKF filtered vs raw Euler angles
plt.figure(figsize=(12, 8))

plt.subplot(3, 1, 1)
plt.plot(mocap_data['RelativeTime'], mocap_data['Roll_KF'], label='Roll (EKF)', color='blue')
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerX'], label='Roll (Raw)', color='gray', linestyle='--')
plt.title('EKF Filtered vs Raw Pitch')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 2)
plt.plot(mocap_data['RelativeTime'], mocap_data['Pitch_KF'], label='Pitch (EKF)', color='green')
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerY'], label='Pitch (Raw)', color='orange', linestyle='--')
plt.title('EKF Filtered vs Raw Pitch')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 3)
plt.plot(mocap_data['RelativeTime'], mocap_data['Yaw_KF'], label='Yaw (EKF)', color='purple')
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerZ'], label='Yaw (Raw)', color='brown', linestyle='--')
plt.title('EKF Filtered vs Raw Yaw')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()

