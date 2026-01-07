"""
This uses a basic 1D Kalman filter assuming constant position model with process noise Q and measurement noise R.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys

# Kalman filter function for 1D signals
def kalman_filter(z, Q=1e-5, R=1e-2):
    """
    Simple 1D Kalman filter for a signal z
    Q: process noise covariance
    R: measurement noise covariance
    Returns filtered signal array
    """
    n = len(z)
    x_hat = np.zeros(n)      # filtered estimate
    P = np.zeros(n)          # error covariance
    x_hat_minus = np.zeros(n)
    P_minus = np.zeros(n)
    K = np.zeros(n)          # Kalman gain
    
    # Initial guesses
    x_hat[0] = z[0]
    P[0] = 1.0
    
    for k in range(1, n):
        # Predict
        x_hat_minus[k] = x_hat[k-1]
        P_minus[k] = P[k-1] + Q
        
        # Update
        K[k] = P_minus[k] / (P_minus[k] + R)
        x_hat[k] = x_hat_minus[k] + K[k] * (z[k] - x_hat_minus[k])
        P[k] = (1 - K[k]) * P_minus[k]
    
    return x_hat

# Your original loading and alignment code
if len(sys.argv) != 3:
    print("Usage: python compare_sensors.py mocap.csv imu.csv")
    sys.exit(1)

mocap_file, imu_file = sys.argv[1], sys.argv[2]
mocap_data = pd.read_csv(mocap_file)
imu_data = pd.read_csv(imu_file)
prefix = imu_file.rsplit('.csv', 1)[0]

mocap_data['UnixTime'] = pd.to_datetime(mocap_data['BroadcastTime'], unit='us')
imu_data['UnixTime'] = pd.to_datetime(imu_data['time_y'], unit='ns')

if mocap_data['UnixTime'].iloc[0] < imu_data['UnixTime'].iloc[0]:
    mocap_data = mocap_data[mocap_data['UnixTime'] >= imu_data['UnixTime'].iloc[0]].reset_index(drop=True)

imu_start_time = imu_data['UnixTime'].iloc[0]
mocap_data['RelativeTime'] = (mocap_data['UnixTime'] - imu_start_time).dt.total_seconds()
imu_data['RelativeTime'] = imu_data['roll_x'] / 1000

# Apply Kalman filter to Euler angles in MoCap and IMU
mocap_data['Roll_KF'] = kalman_filter(mocap_data['EulerX'].values)
mocap_data['Pitch_KF'] = kalman_filter(mocap_data['EulerY'].values)
mocap_data['Yaw_KF'] = kalman_filter(mocap_data['EulerZ'].values)

imu_data['Roll_KF'] = kalman_filter(imu_data['roll_y'].values)
imu_data['Pitch_KF'] = kalman_filter(imu_data['pitch_y'].values)
imu_data['Yaw_KF'] = kalman_filter(imu_data['yaw_y'].values)

# Plotting filtered vs original for Roll as example
plt.figure(figsize=(10, 6))
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerX'], label='Roll - MoCap Raw', color='blue', alpha=0.5)
plt.plot(mocap_data['RelativeTime'], mocap_data['Roll_KF'], label='Roll - MoCap KF', color='blue')
plt.plot(imu_data['RelativeTime'], imu_data['roll_y'], label='Roll - IMU Raw', color='red', alpha=0.5, linestyle='--')
plt.plot(imu_data['RelativeTime'], imu_data['Roll_KF'], label='Roll - IMU KF', color='red', linestyle='--')
plt.title('Roll Angle Comparison with Kalman Filter')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)
plt.show()

# You can add similar plots for Pitch, Yaw or velocities as needed
