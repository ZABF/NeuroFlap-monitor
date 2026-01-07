import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R

# Extended Kalman Filter class for fusion
class EKF:
    def __init__(self):
        self.state = np.zeros(7)  # [x, y, z, qx, qy, qz, qw]
        self.state[6] = 1.0  # Initialize quaternion w=1
        self.P = np.eye(7) * 0.01
        self.Q = np.eye(7) * 0.001
        self.R = np.eye(7) * 0.01

    def predict(self, u):
        # Simple position update with acceleration input integration (could be improved)
        self.state[:3] += u[:3]  # This is a placeholder, normally you'd integrate velocity & acceleration properly
        self.P += self.Q

    def update(self, z):
        # Innovation
        y = z - self.state
        S = self.P + self.R  # Innovation covariance
        K = self.P @ np.linalg.inv(S)  # Kalman gain
        self.state += K @ y  # Update state
        self.P = (np.eye(7) - K) @ self.P  # Update covariance
        # Normalize quaternion part
        norm = np.linalg.norm(self.state[3:])
        if norm > 0:
            self.state[3:] /= norm
        else:
            self.state[3:] = np.array([0, 0, 0, 1], dtype=float)

# Convert quaternions to Euler angles (degrees), safely handling zero norms
def safe_quat_to_euler(qx, qy, qz, qw):
    quats = np.vstack((qx, qy, qz, qw)).T
    norms = np.linalg.norm(quats, axis=1)
    zero_norm_idx = norms == 0
    quats[zero_norm_idx] = np.array([0, 0, 0, 1])
    r = R.from_quat(quats)
    return r.as_euler('xyz', degrees=True)

def main():
    if len(sys.argv) != 3:
        print("Usage: python script.py mocap.csv imu.csv")
        sys.exit(1)

    mocap_file, imu_file = sys.argv[1], sys.argv[2]
    mocap_data = pd.read_csv(mocap_file)
    imu_data = pd.read_csv(imu_file)

    # Step 1: Get Unix time from respective fields
    mocap_data['UnixTime'] = pd.to_datetime(mocap_data['BroadcastTime'], unit='us')
    imu_data['UnixTime'] = pd.to_datetime(imu_data['time_y'], unit='ns')

    # Step 2: Check if MoCap time is before IMU time
    if mocap_data['UnixTime'].iloc[0] < imu_data['UnixTime'].iloc[0]:
        mocap_data = mocap_data[mocap_data['UnixTime'] >= imu_data['UnixTime'].iloc[0]].reset_index(drop=True)

    # Step 3: Use IMU Unix time as the reference and convert MoCap time to seconds
    imu_start_time = imu_data['UnixTime'].iloc[0]
    mocap_data['RelativeTime'] = (mocap_data['UnixTime'] - imu_start_time).dt.total_seconds()

    # Step 4: Use 'roll_x' as IMU starting time reference
    imu_data['RelativeTime'] = imu_data['roll_x'] / 1000

    # Calculate MoCap Euler angles from quaternions (in degrees)
    mocap_eulers = safe_quat_to_euler(mocap_data['qx'], mocap_data['qy'], mocap_data['qz'], mocap_data['qw'])
    mocap_data['EulerX'] = mocap_eulers[:, 0]
    mocap_data['EulerY'] = mocap_eulers[:, 1]
    mocap_data['EulerZ'] = mocap_eulers[:, 2]

    ekf = EKF()
    fused_data = []

    # Use min length to avoid indexing errors
    length = min(len(mocap_data), len(imu_data))

    for i in range(length):
        mocap_pos = np.array([mocap_data.loc[i, 'X'], mocap_data.loc[i, 'Y'], mocap_data.loc[i, 'Z']])
        mocap_quat = np.array([mocap_data.loc[i, 'qx'], mocap_data.loc[i, 'qy'], mocap_data.loc[i, 'qz'], mocap_data.loc[i, 'qw']])

        imu_acc = np.array([imu_data.loc[i, 'ax_y'], imu_data.loc[i, 'ay_y'], imu_data.loc[i, 'az_y']])
        # Note: Angular velocity and quaternion from IMU not directly used in EKF predict/update here, but can be included for improvement

        # IMU quaternion is given as q0_y, q1_y, q2_y, q3_y - reorder to [qx, qy, qz, qw]
        imu_quat = np.array([imu_data.loc[i, 'q1_y'], imu_data.loc[i, 'q2_y'], imu_data.loc[i, 'q3_y'], imu_data.loc[i, 'q0_y']])

        ekf.predict(imu_acc)  # Very basic predict step
        ekf.update(np.hstack((mocap_pos, mocap_quat)))
        fused_data.append(ekf.state.copy())

    fused_data = np.array(fused_data)

    # Extract fused positions and quaternions
    fused_positions = fused_data[:, :3]
    fused_quats = fused_data[:, 3:]

    # Convert fused quaternion to Euler angles (degrees)
    r = R.from_quat(fused_quats)
    fused_eulers = r.as_euler('xyz', degrees=True)

    # Plot Position comparison
    plt.figure(figsize=(15, 12))
    axes = ['X', 'Y', 'Z']
    for i, axis in enumerate(axes):
        plt.subplot(3, 1, i+1)
        plt.plot(mocap_data['RelativeTime'][:length], mocap_data[axis][:length], label=f'MoCap {axis}', color='blue')
        plt.plot(mocap_data['RelativeTime'][:length], fused_positions[:, i], label=f'Fused {axis}', color='green', linestyle='-.')
        plt.title(f'Position {axis} Comparison')
        plt.xlabel('Time (s)')
        plt.ylabel('Position (m)')
        plt.legend()
        plt.grid(True)
    plt.tight_layout()
    plt.show()

    # Plot Euler angles comparison
    plt.figure(figsize=(15, 12))
    angles = ['X', 'Y', 'Z']  # roll, pitch, yaw
    imu_euler_fields = ['roll_y', 'pitch_y', 'yaw_y']  # Correct IMU Euler fields
    for i, angle in enumerate(angles):
        plt.subplot(3, 1, i+1)
        plt.plot(mocap_data['RelativeTime'][:length], mocap_data[f'Euler{angle}'][:length], label=f'MoCap Euler {angle}', color='blue')
        plt.plot(imu_data['roll_x'][:length]/1000, imu_data[imu_euler_fields[i]][:length], label=f'IMU Euler {angle}', color='red', linestyle='--')
        plt.plot(mocap_data['RelativeTime'][:length], fused_eulers[:, i], label=f'Fused Euler {angle}', color='green', linestyle='-.')
        plt.title(f'Euler Angle {angle} Comparison')
        plt.xlabel('Time (s)')
        plt.ylabel('Degrees')
        plt.legend()
        plt.grid(True)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
