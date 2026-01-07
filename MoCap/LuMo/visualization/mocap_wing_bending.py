"""
Plot Marker Trajectories, Wing Bending, and Flapping Angles from Motion Capture Data

This script processes motion capture marker data from a CSV file to visualize and analyze wing motion dynamics, including:

1. 3D Trajectories:
   - Visualizes 3D trajectories of specified markers on the wing.
   - Points are colored according to time using a plasma colormap, showing temporal progression.

2. Wing Bending Shapes:
   - Plots 2D wing bending shapes for both downstroke and upstroke phases within one selected flapping cycle.
   - View is oriented along the wing rotation axis to better illustrate bending.
   - Calculates maximum bending angles during downstroke and upstroke phases:
     * Angle is defined between the vector from the wing hinge to the first marker and from the hinge to the tip marker.
     * Angles are displayed in degrees on the corresponding subplot.

3. Flapping Angle Dynamics:
   - Calculates and plots the flapping angles of the first marker and wing tip marker relative to the wing hinge marker over the entire time series.
   - Shows the angle evolution with max and min envelope lines to highlight flapping range and variation.

Features:
- Selectable flapping cycle index for detailed bending shape analysis (default is the middle cycle).
- Consistent color mapping across all plots for time correlation.
- Horizontal layout for wing bending subplots for clear comparison.
- Prints and annotates maximum bending angles for both downstroke and upstroke phases.

Usage:
    python script.py -r Rigid2 [-c {middle,0,1,2,...}]

Parameters:
    -r/--rigid_id: Marker prefix (e.g., Rigid2)
    -c/--cycle: Cycle index for wing bending visualization ("middle" or integer index starting from 0)

Output:
- A multi-panel figure including:
  * 3D marker trajectories colored by time,
  * 2D wing bending plots for downstroke and upstroke phases with max bending angle annotations,
  * Flapping angle vs. time plot with min/max boundaries.
- Saves figures.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks

def print_info(text): 
    print(f"\033[92m{text}\033[0m")

def plot_marker_trajectories(file_path, marker_prefix, figure_prefix, cycle_index='middle'):
    data = pd.read_csv(file_path)
    filtered_data = data[data['makerName'].str.startswith(marker_prefix, na=False)]

    if filtered_data.empty:
        print_info(f'No data found for markers starting with {marker_prefix}')
        return

    # Convert Unix time to seconds relative to start time
    start_time = filtered_data['BroadcastTime'].iloc[0]
    filtered_data['TimeSec'] = (filtered_data['BroadcastTime'] - start_time) / 1e6
    unique_times = np.sort(filtered_data['TimeSec'].unique())

    # TODO Make sure the sequence below is from wing hinge to wing tip! Otherwise, second figure will be incorrect.
    marker_name_map = {
        'Rigid_WingLite_R_MainRodMarker20700': r'$0$',
        'Rigid_WingLite_R_MainRodMarker20701': r'$\frac{1}{3} L_{rod}$',
        'Rigid_WingLite_R_MainRodMarker20702': r'$\frac{2}{3} L_{rod}$',
        'Rigid_WingLite_R_MainRodMarker20703': r'$L_{rod}$',
    }
    # marker_name_map = {
    #     'Rigid_WingLite_R_MainRodMarker20703': r'$0$',
    #     'Rigid_WingLite_R_MainRodMarker20702': r'$\frac{1}{3} L_{rod}$',
    #     'Rigid_WingLite_R_MainRodMarker20701': r'$\frac{2}{3} L_{rod}$',
    #     'Rigid_WingLite_R_MainRodMarker20700': r'$L_{rod}$',
    # }
    marker_shapes = ['^', 'o', 's', 'd']  # Fixed marker shapes

    # Create figure with 3 subplots and space for colorbar below
    fig = plt.figure(figsize=(18, 6.3))
    gs = fig.add_gridspec(2, 3, height_ratios=[20, 1], width_ratios=[1.5, 1, 1])
    
    # Main plots
    ax1 = fig.add_subplot(gs[0, 0], projection='3d')
    ax_down = fig.add_subplot(gs[0, 1])  # Downstroke subplot
    ax_up = fig.add_subplot(gs[0, 2])    # Upstroke subplot
    
    # Colorbar axis
    cax = fig.add_subplot(gs[1, 0])

    cmap = plt.get_cmap('plasma')
    norm = plt.Normalize(unique_times.min(), unique_times.max())

    # --- First Figure: 3D trajectories of Main Rod and Wind Bending Over Time ---
    # Plot 3D trajectories
    for i, marker_name in enumerate(marker_name_map.keys()):
        marker_data = filtered_data[filtered_data['makerName'] == marker_name]
        if marker_data.empty:
            continue
        x = marker_data['makerX'].values
        y = marker_data['makerY'].values
        z = marker_data['makerZ'].values
        time = marker_data['TimeSec'].values

        norm_time = norm(time)
        colors = cmap(norm_time)
        marker_shape = marker_shapes[i]
        label = marker_name_map.get(marker_name, marker_name)

        ax1.plot(x, y, z, color='lightgray', linewidth=0.8, alpha=0.7)
        ax1.scatter(x, y, z, c=colors, marker=marker_shape, label=label, edgecolor='black', linewidth=0.1)

    ax1.set_title(f'3D Trajectories of markers starting with {marker_prefix}')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')
    ax1.legend(loc='upper left', bbox_to_anchor=(1.05, 1))
    ax1.view_init(elev=24, azim=60, roll=-1)

    # Prepare for wing bending plots
    angle_deg = 25
    angle_rad = np.deg2rad(angle_deg)
    rot_axis = np.array([np.cos(angle_rad), np.sin(angle_rad), 0])
    rot_axis /= np.linalg.norm(rot_axis)

    z_axis = np.array([0, 0, 1])
    v = np.cross(rot_axis, z_axis)
    if np.linalg.norm(v) < 1e-8:
        v = np.cross(rot_axis, np.array([1, 0, 0]))
    v /= np.linalg.norm(v)
    u = np.cross(v, rot_axis)
    u /= np.linalg.norm(u)

    # Get tip marker data for stroke detection
    tip_marker = 'Rigid_WingLite_R_MainRodMarker20703'
    tip_data = filtered_data[filtered_data['makerName'] == tip_marker]
    if tip_data.empty:
        print_info(f"Tip marker {tip_marker} not found")
        return

    # Find peaks (highest points) and troughs (lowest points) in Z coordinate
    z_values = tip_data['makerZ'].values
    peaks, _ = find_peaks(z_values, prominence=0.5)  # Highest points (end of upstroke)
    troughs, _ = find_peaks(-z_values, prominence=0.5)  # Lowest points (end of downstroke)

    # Select the desired cycle based on cycle_index parameter
    if len(peaks) < 2 or len(troughs) < 1:
        print_info("Couldn't detect complete wing stroke cycles")
        return
        
    if cycle_index == 'middle':
        cycle_idx = len(peaks) // 2
    elif isinstance(cycle_index, int):
        cycle_idx = min(cycle_index, len(peaks)-2)
    else:
        cycle_idx = 0  # Default to first cycle if invalid input
        
    start_peak = peaks[cycle_idx]
    next_trough = troughs[troughs > start_peak][0] if any(troughs > start_peak) else troughs[-1]
    next_peak = peaks[peaks > next_trough][0] if any(peaks > next_trough) else peaks[-1]
    
    # Get time values for this cycle
    cycle_start = tip_data['TimeSec'].iloc[start_peak]
    mid_cycle = tip_data['TimeSec'].iloc[next_trough]
    cycle_end = tip_data['TimeSec'].iloc[next_peak]

    print_info(f"Visualizing cycle {cycle_idx+1} of {len(peaks)-1} (time: {cycle_start:.2f}s to {cycle_end:.2f}s)")

    # Initialize variables to store max bending angles
    max_downstroke_angle = 0
    max_upstroke_angle = 0

    # Plot wing bending for downstroke and upstroke
    for t in unique_times:
        if t < cycle_start or t > cycle_end:
            continue
            
        time_slice = filtered_data[filtered_data['TimeSec'] == t]
        coords = []
        for marker_name in marker_name_map.keys():
            marker_row = time_slice[time_slice['makerName'] == marker_name]
            if marker_row.empty:
                continue
            x_m = marker_row['makerX'].values[0]
            y_m = marker_row['makerY'].values[0]
            z_m = marker_row['makerZ'].values[0]
            coords.append([x_m, y_m, z_m])
        coords = np.array(coords)
        if coords.shape[0] < 2:
            continue

        hinge_pos = coords[0, :]
        coords_centered = coords - hinge_pos
        coords_2d = np.zeros((coords_centered.shape[0], 2))
        coords_2d[:, 0] = coords_centered @ u
        coords_2d[:, 1] = coords_centered @ v

        # Calculate bending angle (angle between first and last segment)
        vec1 = coords_2d[1] - coords_2d[0]  # Hinge to first marker
        vec2 = coords_2d[-1] - coords_2d[0]   # Hinge to tip marker
        bending_angle = np.degrees(np.arccos(
            np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        ))

        color = cmap(norm(t))
        
        if t <= mid_cycle:  # Downstroke phase
            ax_down.plot(coords_2d[:, 1], coords_2d[:, 0], color=color, alpha=0.8, linewidth=1.5)
            for i, coord in enumerate(coords_2d):
                ax_down.scatter(coord[1], coord[0], color=color, edgecolor='black', 
                              marker=marker_shapes[i], s=40)
            if bending_angle > max_downstroke_angle:
                max_downstroke_angle = bending_angle
        else:  # Upstroke phase
            ax_up.plot(coords_2d[:, 1], coords_2d[:, 0], color=color, alpha=0.8, linewidth=1.5)
            for i, coord in enumerate(coords_2d):
                ax_up.scatter(coord[1], coord[0], color=color, edgecolor='black', 
                            marker=marker_shapes[i], s=40, label=marker_name_map[list(marker_name_map.keys())[i]] if t == mid_cycle else "")
            if bending_angle > max_upstroke_angle:
                max_upstroke_angle = bending_angle

    # Add max bending angle annotations
    ax_down.annotate(f'Max bending angle: {max_downstroke_angle:.1f}°', 
                    xy=(0.05, 0.95), xycoords='axes fraction',
                    ha='left', va='top', bbox=dict(boxstyle='round', fc='white', alpha=0.8))
    
    ax_up.annotate(f'Max bending angle: {max_upstroke_angle:.1f}°', 
                  xy=(0.05, 0.95), xycoords='axes fraction',
                  ha='left', va='top', bbox=dict(boxstyle='round', fc='white', alpha=0.8))

    # Configure downstroke plot (no legend)
    ax_down.axhline(0, color='gray', linestyle='--', linewidth=0.8)
    ax_down.axvline(0, color='gray', linestyle='--', linewidth=0.8)
    ax_down.set_aspect('equal', 'box')
    ax_down.grid(True, linestyle=':')
    ax_down.set_xlabel(r'Perpendicular direction $\mathbf{v}$')
    ax_down.set_ylabel(r'Perpendicular direction $\mathbf{u}$')
    ax_down.set_title(f'Downstroke Wing Bending (Cycle {cycle_idx+1})')

    # Configure upstroke plot (with legend)
    ax_up.axhline(0, color='gray', linestyle='--', linewidth=0.8)
    ax_up.axvline(0, color='gray', linestyle='--', linewidth=0.8)
    ax_up.set_aspect('equal', 'box')
    ax_up.grid(True, linestyle=':')
    ax_up.set_xlabel(r'Perpendicular direction $\mathbf{v}$')
    ax_up.set_ylabel(r'Perpendicular direction $\mathbf{u}$')
    ax_up.set_title(f'Upstroke Wing Bending (Cycle {cycle_idx+1})')

    # Add colorbar below the left subplot
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cax, orientation='horizontal', aspect=50, pad=0.)
    ticks = cbar.get_ticks()
    t_min, t_max = unique_times.min(), unique_times.max()
    norm_ticks = (ticks - t_min) / (t_max - t_min)
    cbar.set_ticklabels([f"{v:.2f}" for v in norm_ticks])
    cbar.set_label('Normalized Time (s)')

    plt.tight_layout()
    fig.savefig(f'{figure_prefix}_wing_bending.png', dpi=300, bbox_inches='tight')
    plt.show()

    # --- Second Figure: Two Flapping Angles Over Time with Separate Min/Max Lines ---
    marker_keys = list(marker_name_map.keys())
    hinge_marker = marker_keys[0]          # First marker = hinge
    second_marker = marker_keys[1]         # Second marker
    tip_marker = marker_keys[-1]           # Last marker = tip

    hinge_data = filtered_data[filtered_data['makerName'] == hinge_marker].sort_values('TimeSec')
    second_data = filtered_data[filtered_data['makerName'] == second_marker].sort_values('TimeSec')
    tip_data = filtered_data[filtered_data['makerName'] == tip_marker].sort_values('TimeSec')

    if hinge_data.empty or second_data.empty or tip_data.empty:
        print_info("One or more required marker data missing; skipping flapping angle plot.")
        return

    # Find common time points among all three markers
    common_times = np.intersect1d(
        hinge_data['TimeSec'].values,
        np.intersect1d(second_data['TimeSec'].values, tip_data['TimeSec'].values)
    )

    def compute_flapping_angle(hinge_df, other_df, times):
        angles = []
        for t in times:
            hinge_pos = hinge_df.loc[hinge_df['TimeSec'] == t, ['makerX', 'makerY', 'makerZ']].values
            other_pos = other_df.loc[other_df['TimeSec'] == t, ['makerX', 'makerY', 'makerZ']].values
            if hinge_pos.size == 0 or other_pos.size == 0:
                angles.append(np.nan)
                continue
            vec = other_pos[0] - hinge_pos[0]
            vec_norm = vec / np.linalg.norm(vec)
            angle_rad = np.arcsin(np.clip(vec_norm[2], -1.0, 1.0))  # Clamp for safety
            angles.append(np.degrees(angle_rad))
        return np.array(angles)

    # Calculate both flapping angles
    flapping_angles_1 = compute_flapping_angle(hinge_data, tip_data, common_times)
    flapping_angles_2 = compute_flapping_angle(hinge_data, second_data, common_times)

    # Compute max/min for each flapping angle separately
    max_angle_1 = np.nanmax(flapping_angles_1)
    min_angle_1 = np.nanmin(flapping_angles_1)
    max_angle_2 = np.nanmax(flapping_angles_2)
    min_angle_2 = np.nanmin(flapping_angles_2)

    # Elegant matplotlib style
    plt.rcParams.update({
        "font.size": 11,
        "font.family": "serif",
        "axes.labelsize": 12,
        "axes.titlesize": 13,
        "legend.fontsize": 11,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "lines.linewidth": 1.5,
        "axes.linewidth": 1.0,
    })

    fig, ax = plt.subplots(figsize=(12, 3.5))
    ax.plot(common_times, flapping_angles_1, color='black', label='Flapping angle (hinge-tip)')
    ax.plot(common_times, flapping_angles_2, color='orange', label='Flapping angle (hinge-2nd)')

    ax.axhline(0, color='gray', linestyle=':', linewidth=1.0)

    # Max/min lines for first flapping angle (hinge-tip)
    ax.axhline(max_angle_1, color='darkred', linestyle='--', linewidth=1.0,
            label=f'Max (hinge-tip) = {max_angle_1:.1f}°')
    ax.axhline(min_angle_1, color='darkblue', linestyle='--', linewidth=1.0,
            label=f'Min (hinge-tip) = {min_angle_1:.1f}°')

    # Max/min lines for second flapping angle (hinge-2nd)
    ax.axhline(max_angle_2, color='red', linestyle=':', linewidth=1.0,
            label=f'Max (hinge-2nd) = {max_angle_2:.1f}°')
    ax.axhline(min_angle_2, color='blue', linestyle=':', linewidth=1.0,
            label=f'Min (hinge-2nd) = {min_angle_2:.1f}°')

    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Flapping angle (°)')
    ax.set_title('Flapping angles over time', pad=10)
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), frameon=False)
    ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.4)

    plt.tight_layout()
    plt.savefig(f'{figure_prefix}_flapping_angle_vs_time.png', dpi=600, bbox_inches='tight')
    plt.show()



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Plot marker trajectories from motion capture data.')
    parser.add_argument('-r', '--rigid_id', type=str, default='Rigid2', help='Marker prefix (e.g., Rigid2)')
    parser.add_argument('-c', '--cycle', type=str, default='middle', 
                       help='Cycle index to plot ("middle", or integer index starting from 0)')
    args = parser.parse_args()

    # Convert cycle argument to int if it's a number
    try:
        cycle_index = int(args.cycle)
    except ValueError:
        cycle_index = args.cycle  # keep as string if not a number

    file_path = 'data20250522/wing_kinematics_airpulselite/20250522_182613_motion_data.csv'  # TODO Update path
    prefix = file_path.rsplit('_motion_data', 1)[0]
    plot_marker_trajectories(file_path, args.rigid_id, prefix, cycle_index=cycle_index)