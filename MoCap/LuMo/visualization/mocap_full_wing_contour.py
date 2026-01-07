"""
Visualize a flapping wing stroke cycle for the full wing (front and hind wing) from motion capture CSV data.

This script:
- Parses marker trajectories from a specified wing
- Automatically detects flapping cycles based on Z-peaks of the tip marker
- Plots:
  (1) 3D trajectories of all markers during a stroke cycle with time-colored dots
  (2) Flapping angle of the hind wing versus time, also colored by time
- Saves the resulting figure as 'flapping_cycle.png'

Usage:
    python mocap_full_wing_contour.py your_data.csv -w Rigid_WingLite_R_FullWing -c 2
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import argparse
from scipy.signal import find_peaks
from mpl_toolkits.mplot3d import Axes3D

def plot_wing_trajectories(file_path, wing_prefix, cycle_index, figure_prefix):
    data = pd.read_csv(file_path)
    filtered_data = data[data['makerName'].str.startswith(wing_prefix, na=False)]

    if filtered_data.empty:
        print(f'No data found for markers starting with {wing_prefix}')
        return

    # Normalize time
    start_time = filtered_data['BroadcastTime'].iloc[0]
    filtered_data['TimeSec'] = (filtered_data['BroadcastTime'] - start_time) / 1e6
    unique_times = np.sort(filtered_data['TimeSec'].unique())

    # TODO: Change here with correct root and hindwing markers, otherwise, the results will be wrong.
    root_marker = 'Rigid_WingLite_R_FullWingMarker20900'
    hind_marker = 'Rigid_WingLite_R_FullWingMarker20907'

    all_markers = filtered_data['makerName'].unique()
    if root_marker not in all_markers or hind_marker not in all_markers:
        print(f"Required markers not found.\nAvailable markers:\n{all_markers}")
        return

    tip_marker = filtered_data.groupby('makerName')['makerX'].mean().idxmax()
    tip_data = filtered_data[filtered_data['makerName'] == tip_marker]
    z_values = tip_data['makerZ'].values

    peaks, _ = find_peaks(z_values, prominence=0.5)
    troughs, _ = find_peaks(-z_values, prominence=0.5)

    if len(peaks) < 2 or len(troughs) < 1:
        print("Couldn't detect full stroke cycles.")
        return

    if cycle_index == 'middle':
        cycle_idx = len(peaks) // 2
    else:
        cycle_idx = min(int(cycle_index), len(peaks) - 2)

    start_peak = peaks[cycle_idx]
    next_trough = troughs[troughs > start_peak][0] if any(troughs > start_peak) else troughs[-1]
    next_peak = peaks[peaks > next_trough][0] if any(peaks > next_trough) else peaks[-1]

    cycle_start = tip_data['TimeSec'].iloc[start_peak]
    cycle_end = tip_data['TimeSec'].iloc[next_peak]
    print(f"Visualizing stroke cycle {cycle_idx+1} from {cycle_start:.3f}s to {cycle_end:.3f}s")

    cycle_data = filtered_data[(filtered_data['TimeSec'] >= cycle_start) & (filtered_data['TimeSec'] <= cycle_end)]
    cycle_times = np.sort(cycle_data['TimeSec'].unique())

    fig = plt.figure(figsize=(14, 7))
    gs = fig.add_gridspec(2, 2, height_ratios=[5, 0.3])
    ax1 = fig.add_subplot(gs[0, 0], projection='3d')
    ax2 = fig.add_subplot(gs[0, 1])
    cax = fig.add_subplot(gs[1, :])

    cmap = plt.get_cmap('plasma')
    norm = plt.Normalize(cycle_start, cycle_end)

    for marker in cycle_data['makerName'].unique():
        marker_data = cycle_data[cycle_data['makerName'] == marker]
        x = marker_data['makerX'].values
        y = marker_data['makerY'].values
        z = marker_data['makerZ'].values
        t = marker_data['TimeSec'].values

        ax1.plot(x, y, z, color='lightgray', linewidth=0.8, alpha=0.8)
        ax1.scatter(x, y, z, c=t, cmap=cmap, norm=norm, s=8, alpha=0.9)

    ax1.set_title(f'3D Trajectories (Cycle {cycle_idx+1})')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')
    ax1.view_init(elev=24, azim=60)

    flapping_times = []
    flapping_angles = []

    for t in cycle_times:
        frame = cycle_data[np.isclose(cycle_data['TimeSec'], t, atol=1e-6)]
        root_row = frame[frame['makerName'] == root_marker]
        hind_row = frame[frame['makerName'] == hind_marker]

        if root_row.empty or hind_row.empty:
            continue

        root_pos = root_row[['makerX', 'makerY', 'makerZ']].values[0]
        hind_pos = hind_row[['makerX', 'makerY', 'makerZ']].values[0]
        vec = hind_pos - root_pos
        if np.linalg.norm(vec) == 0:
            continue

        angle_deg = 90 - np.degrees(np.arccos(np.dot(vec / np.linalg.norm(vec), [0, 0, 1])))
        flapping_times.append(t)
        flapping_angles.append(angle_deg)

    if flapping_times:
        ax2.plot(flapping_times, flapping_angles, color='lightgray', linewidth=1.0, alpha=0.7)
        ax2.scatter(flapping_times, flapping_angles, c=flapping_times, cmap=cmap, norm=norm, s=25)
        ax2.set_xlabel('Time (s)')
        ax2.set_ylabel('Flapping Angle (deg)')
        ax2.set_title('Hindwing Flapping Angle')
        ax2.grid(True)
    else:
        print("No flapping angle data computed.")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax, orientation='horizontal')
    cbar.set_label('Time (s) in Stroke Cycle')

    plt.tight_layout()
    fig.savefig(f'{figure_prefix}_full_wing_contour.png', 
               dpi=300, 
               bbox_inches='tight')
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--wing_prefix", type=str, default="Rigid_WingLite_R_FullWing", help="Wing marker prefix")
    parser.add_argument("-c", "--cycle", type=str, default="middle", help="Stroke cycle index to visualize (int or 'middle')")
    args = parser.parse_args()

    file_path = 'data20250522/wing_kinematics_airpulselite/20250522_182912_motion_data.csv'
    prefix = file_path.rsplit('_motion_data', 1)[0]
    plot_wing_trajectories(file_path, args.wing_prefix, args.cycle, prefix)
