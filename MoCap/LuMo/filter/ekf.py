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

        # Add velocity to state if you want better position integration (optional)
        # self.state = np.zeros(10)  # [x, y, z, vx, vy, vz, qx, qy, qz, qw]
        # Initialize accordingly

    def predict(self, u, dt):
        """
        u: input vector combining linear acceleration (ax, ay, az) and angular rate (wx, wy, wz)
        dt: time difference between steps
        """
        # For your current state format:
        # u[:3] = linear acceleration (ax, ay, az)
        # u[3:6] = angular velocity (wx, wy, wz)

        # --- Update position with simple integration (could be improved) ---
        # Here we keep it simple: self.state[:3] += u[:3]*dt  # if acceleration is in m/s² and velocity known

        # --- Update orientation using angular velocity ---
        q = self.state[3:]  # current quaternion [qx, qy, qz, qw]

        # Angular velocity in rad/s
        omega = u[3:6]

        # Create quaternion representation of angular velocity for integration:
        # Quaternion derivative: q_dot = 0.5 * Omega * q
        # Omega matrix from angular velocity vector omega
        Omega = np.array([
            [0,        -omega[0], -omega[1], -omega[2]],
            [omega[0],  0,         omega[2], -omega[1]],
            [omega[1], -omega[2],  0,         omega[0]],
            [omega[2],  omega[1], -omega[0],  0      ]
        ])

        q = q.reshape((4,1))
        q_dot = 0.5 * Omega @ q  # quaternion derivative

        q_new = q + q_dot * dt
        q_new = q_new.flatten()
        q_new /= np.linalg.norm(q_new)  # normalize quaternion

        self.state[3:] = q_new

        # For position update (simplified, assumes u[:3] is velocity increment or displacement):
        self.state[:3] += u[:3] * dt  # This is still a placeholder, replace with velocity integration if available

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
        imu_gyro = np.array([imu_data.loc[i, 'wx_y'], imu_data.loc[i, 'wy_y'], imu_data.loc[i, 'wz_y']]) 
        u = np.hstack((imu_acc, imu_gyro))

        # Calculate dt as difference in relative time
        if i == 0:
            dt = 0.01  # default small dt (e.g., 10 ms)
        else:
            dt = imu_data.loc[i, 'RelativeTime'] - imu_data.loc[i-1, 'RelativeTime']

        ekf.predict(u, dt)
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
