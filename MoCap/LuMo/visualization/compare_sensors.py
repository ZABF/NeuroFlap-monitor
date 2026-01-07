"""
Comparison of Euler Angles and Linear Velocities from Two CSV Files (MoCap and IMU)

This script compares the Euler angles (roll, pitch, yaw) and linear velocities (vx, vy, vz) from two CSV files.
The data is loaded, aligned based on timestamps using Unix time, and plotted for a side-by-side comparison.

Main Features:
1. Data Loading:
   - Reads two CSV files specified as arguments.
   - Supports MoCap (motion capture) and IMU (inertial measurement unit) CSV files.
   - Extracts time, Euler angles, and linear velocities.

2. Data Alignment:
   - Step 1: Extracts Unix time from MoCap ('BroadcastTime') and IMU ('time_y') fields.
   - Step 2: Checks if the MoCap time precedes the IMU time; if yes, clips the MoCap data to align with IMU.
   - Step 3: Uses IMU Unix time as the starting time reference, converting MoCap time into seconds for alignment.
   - Step 4: Uses the 'roll_x' field from IMU data as the time axis reference.

3. Visualization:
   - Plots Euler angles and linear velocities from both files, each quantity in separate subplots.
   - Uses a consistent and professional plotting style for clarity.

Usage:
- Run the script with the following arguments:
  python compare_sensors.py mocap.csv imu.csv
"""

import pandas as pd
import matplotlib.pyplot as plt
import sys

RIGIDBODY_NAME = 'Rigid_APLite'

def print_info(text): 
    print(f"\033[92m{text}\033[0m")

# Check for correct number of arguments
if len(sys.argv) != 3:
    print("Usage: python compare_sensors.py mocap.csv imu.csv")
    sys.exit(1)

# Load CSV files
mocap_file, imu_file = sys.argv[1], sys.argv[2]
mocap_data = pd.read_csv(mocap_file)
imu_data = pd.read_csv(imu_file)
prefix = imu_file.rsplit('.csv', 1)[0]

# Filter rigid body by name
mocap_data = mocap_data[mocap_data['RigidBody_Name'] == RIGIDBODY_NAME].copy()   
# Save filtered data to new CSV file
# filtered_filename = f"{prefix}_filtered_mocap.csv"
# mocap_data.to_csv(filtered_filename, index=False)
# print(f"Filtered MoCap data saved to: {filtered_filename}")

# Step 1: Get Unix time from respective fields
mocap_data['UnixTime'] = pd.to_datetime(mocap_data['BroadcastTime'], unit='us')
imu_data['UnixTime'] = pd.to_datetime(imu_data['time_y'], unit='us')
print_info(f"MoCap Unix Time: {mocap_data['UnixTime'].iloc[0]}")
print_info(f"IMU Unix Time: {imu_data['UnixTime'].iloc[0]}")

# Step 2: Check if MoCap time is before IMU time
if mocap_data['UnixTime'].iloc[0] < imu_data['UnixTime'].iloc[0]:
    mocap_data = mocap_data[mocap_data['UnixTime'] >= imu_data['UnixTime'].iloc[0]].reset_index(drop=True)
    print_info(f"MoCap Time is ahead of IMU Time.")

# Step 3: Use IMU Unix time as the reference and convert MoCap time to seconds
imu_start_time = imu_data['UnixTime'].iloc[0]
mocap_data['RelativeTime'] = (mocap_data['UnixTime'] - imu_start_time).dt.total_seconds()
# mocap_data['RelativeTime'] -= 8.4 # TODO REMOVE THIS LATER FOR TEMPORARY MANUAL CLOCK SYNC

print_info(f"MoCap Max Time: {mocap_data['RelativeTime'].max()}")
print_info(f"IMU Max Time: {imu_data['roll_x'].max()/1000}")

# Step 4: Use 'roll_x' as IMU starting time reference
imu_data['RelativeTime'] = imu_data['roll_x'] / 1000

# Step 5: Plot Euler angles
plt.figure(figsize=(10, 12))
plt.subplot(3, 1, 1)
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerX'], label='Roll - MoCap', color='blue')
plt.plot(imu_data['RelativeTime'], imu_data['roll_y'], label='Roll - IMU', color='red', linestyle='--')
plt.title('Roll')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 2)
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerY'], label='Pitch - MoCap', color='green')
plt.plot(imu_data['RelativeTime'], imu_data['pitch_y'], label='Pitch - IMU', color='orange', linestyle='--')
plt.title('Pitch')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 3)
plt.plot(mocap_data['RelativeTime'], mocap_data['EulerZ'], label='Yaw - MoCap', color='purple')
plt.plot(imu_data['RelativeTime'], imu_data['yaw_y'], label='Yaw - IMU', color='brown', linestyle='--')
plt.title('Yaw')
plt.xlabel('Time (s)')
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)
plt.tight_layout()

plt.savefig(f'{prefix}_mocap_vs_imu_euler.png', dpi=300, bbox_inches='tight')
plt.show()

# Step 6: Plot linear velocities 
plt.figure(figsize=(10, 12))
plt.subplot(3, 1, 1)
plt.plot(mocap_data['RelativeTime'], mocap_data['SpeedX'], label='Vx - MoCap', color='blue')
plt.plot(imu_data['roll_x']/1000, imu_data['vx_y'], label='Vx - IMU', color='red', linestyle='--')
plt.title('Vx')
plt.xlabel('Time (s)')
plt.ylabel('Velocity (m/s)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 2)
plt.plot(mocap_data['RelativeTime'], mocap_data['SpeedY'], label='Vy - MoCap', color='green')
plt.plot(imu_data['roll_x']/1000, imu_data['vy_y'], label='Vy - IMU', color='orange', linestyle='--')
plt.title('Vy')
plt.xlabel('Time (s)')
plt.ylabel('Velocity (m/s)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 3)
plt.plot(mocap_data['RelativeTime'], mocap_data['SpeedZ'], label='Vz - MoCap', color='purple')
plt.plot(imu_data['roll_x']/1000, imu_data['vz_y'], label='Vz - IMU', color='brown', linestyle='--')
plt.title('Vz')
plt.xlabel('Time (s)')
plt.ylabel('Velocity (m/s)')
plt.legend()
plt.grid(True)
plt.tight_layout()

plt.savefig(f'{prefix}_mocap_vs_imu_linvel.png', dpi=300, bbox_inches='tight')
plt.show()