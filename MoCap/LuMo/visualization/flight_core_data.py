"""
Data Visualization Script for Flight Data

This script processes and visualizes flight data recorded from AirPulse, extracted 
from a CSV file located in the 'data' directory. The script performs the following tasks:

1. Data Loading and Preprocessing:
   - Reads flight data from a CSV file, including time, Euler angles, PWM signals, 
     flapping angles, ADC values, flapping frequency, altitude, accelerations, 
     body rates, linear velocities, and quaternions.
   - Converts time from nanoseconds to relative seconds.

2. Visualization:
   - Plots the following flight metrics as time series:
     (1) Euler Angles (Roll, Pitch, Yaw)
     (2) PWM Signals, Flapping Angles, and ADC Values
     (3) Flapping Frequency
     (4) Flight Altitude
     (5) Accelerations (Ax, Ay, Az)
     (6) Body Rates (Wx, Wy, Wz)
     (7) Linear Velocities (Vx, Vy, Vz)
     (8) Quaternions (Q0, Q1, Q2, Q3)
   - Adapts the time axis label based on the time duration (seconds, milliseconds, or minutes).

Requirements:
- Python packages: pandas, matplotlib, sys, pathlib
- A CSV file containing flight data in the specified format.

Usage:
- Ensure the data file path is correctly specified.
- Run the script to generate visualizations of the recorded flight data.
"""

import pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path

# Get the parent directory of the current script's directory
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

# Load the CSV file
file_path = f'{root_dir}/data/131706.csv' # TODO: Replace here if needed.
data = pd.read_csv(file_path)
# print(f'Number of rows/samples: {len(data)}')

# Convert time from nanoseconds to relative seconds
time_ns = data['time_y']
# time_seconds = (time_ns - time_ns.iloc[0]) / 1e6 # Convert to seconds starting from 0
time_seconds = data['roll_x'] / 1000

# Extract relevant columns
# (1) Euler Angles
roll = data['roll_y']
pitch = data['pitch_y']
yaw = data['yaw_y']

# (2) PWM signals, flapping angles, and ADC values
pwm1 = data['pwm1_y']
pwm2 = data['pwm2_y']
ang1 = data['ang1_y']
ang2 = data['ang2_y']
adc = data['adc_y']

# (3) Flapping Frequency
freq = data['freq_y']

# (4) Flight Altitude
alt = data['alt_y']

# (5) Accelerations
ax = data['ax_y']
ay = data['ay_y']
az = data['az_y']

# (6) Body Rates
wx = data['wx_y']
wy = data['wy_y']
wz = data['wz_y']

# (7) Linear Velocities
vx = data['vx_y']
vy = data['vy_y']
vz = data['vz_y']

# (8) Quaternions
q0 = data['q0_y']
q1 = data['q1_y']
q2 = data['q2_y']
q3 = data['q3_y']

# Function to format time axis
def format_time_axis(ax, max_time):
    if max_time < 1.0:  # Show milliseconds if <1s
        ax.set_xlabel('Time (milliseconds)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x * 1000:.0f}'))
    elif max_time > 60:  # Show minutes if >60s
        ax.set_xlabel('Time (minutes)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x / 60:.1f}'))
    else:  # Default to seconds
        ax.set_xlabel('Time (seconds)')

max_time = time_seconds.max()
print(f"max_time: {max_time}")

# (1) Euler Angles
plt.figure()
plt.plot(time_seconds, roll, label='Roll', color='blue')
# plt.plot(time_seconds, pitch, label='Pitch', color='green')
# plt.plot(time_seconds, yaw, label='Yaw', color='red')
plt.title('Euler Angles')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)
plt.show()

# (2) PWM, Flapping Angles, ADC
plt.figure()
plt.subplot(3, 1, 1)
plt.plot(time_seconds, pwm1, label='PWM1', color='purple')
plt.plot(time_seconds, pwm2, label='PWM2', color='orange')
plt.title('PWM Signals')
format_time_axis(plt.gca(), max_time)
plt.ylabel('PWM Value')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 2)
plt.plot(time_seconds, ang1, label='Angle 1', color='cyan')
plt.plot(time_seconds, ang2, label='Angle 2', color='magenta')
plt.title('Flapping Angles')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Angle (degrees)')
plt.legend()
plt.grid(True)

plt.subplot(3, 1, 3)
plt.plot(time_seconds, adc, label='ADC', color='brown')
plt.title('ADC Values')
format_time_axis(plt.gca(), max_time)
plt.ylabel('ADC')
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()

# (3) Flapping Frequency
plt.figure()
plt.plot(time_seconds, freq, label='Frequency', color='teal')
plt.title('Flapping Frequency')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Frequency (Hz)')
plt.legend()
plt.grid(True)
plt.show()

# (4) Flight Altitude
plt.figure()
plt.plot(time_seconds, alt, label='Altitude', color='darkblue')
plt.title('Flight Altitude')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Altitude (m)')
plt.legend()
plt.grid(True)
plt.show()

# (5) Accelerations
plt.figure()
plt.plot(time_seconds, ax, label='Ax', color='crimson')
plt.plot(time_seconds, ay, label='Ay', color='darkorange')
plt.plot(time_seconds, az, label='Az', color='forestgreen')
plt.title('Accelerations')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Acceleration (m/s²)')
plt.legend()
plt.grid(True)
plt.show()

# (6) Body Rates
plt.figure()
plt.plot(time_seconds, wx, label='Wx', color='blue')
plt.plot(time_seconds, wy, label='Wy', color='purple')
plt.plot(time_seconds, wz, label='Wz', color='green')
plt.title('Body Rates')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Rate (rad/s)')
plt.legend()
plt.grid(True)
plt.show()

# (7) Linear Velocities
plt.figure()
plt.plot(time_seconds, vx, label='Vx', color='navy')
plt.plot(time_seconds, vy, label='Vy', color='coral')
plt.plot(time_seconds, vz, label='Vz', color='olive')
plt.title('Linear Velocities')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Velocity (m/s)')
plt.legend()
plt.grid(True)
plt.show()

# (8) Quaternions
plt.figure()
plt.plot(time_seconds, q0, label='Q0', color='black')
plt.plot(time_seconds, q1, label='Q1', color='gray')
plt.plot(time_seconds, q2, label='Q2', color='silver')
plt.plot(time_seconds, q3, label='Q3', color='lightgray')
plt.title('Quaternions')
format_time_axis(plt.gca(), max_time)
plt.ylabel('Quaternion Value')
plt.legend()
plt.grid(True)
plt.show()