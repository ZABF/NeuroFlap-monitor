"""
Plot Full Wing 3D Trajectories with Cycle-Normalized Time

This script visualizes:
- Left: Downstroke phase of one wingbeat cycle 
- Right: Upstroke phase of the same cycle
- Colorbar shows 0-1 normalized cycle time
- Semi-transparent colored planes show wing surface
- Light markers for clear visibility
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
from scipy.signal import find_peaks
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def plot_wing_phases(file_path, wing_prefix, figure_prefix, cycle_index='middle'):
    # Load and preprocess data
    data = pd.read_csv(file_path)
    filtered_data = data[data['makerName'].str.startswith(wing_prefix, na=False)]

    if filtered_data.empty:
        print(f'No data found for markers starting with {wing_prefix}')
        return

    # Convert Unix time to seconds
    start_time = filtered_data['BroadcastTime'].iloc[0]
    filtered_data['TimeSec'] = (filtered_data['BroadcastTime'] - start_time) / 1e6
    unique_times = np.sort(filtered_data['TimeSec'].unique())

    # Get all wing markers
    wing_markers = filtered_data['makerName'].unique()
    
    # Find wing tip for cycle detection
    mean_positions = filtered_data.groupby('makerName')[['makerX','makerY','makerZ']].mean()
    tip_marker = mean_positions['makerX'].idxmax()

    # Detect stroke cycles
    tip_data = filtered_data[filtered_data['makerName'] == tip_marker]
    z_values = tip_data['makerZ'].values
    peaks, _ = find_peaks(z_values, prominence=0.5)  # Highest points
    troughs, _ = find_peaks(-z_values, prominence=0.5)  # Lowest points

    if len(peaks) < 2 or len(troughs) < 1:
        print("Couldn't detect complete wing stroke cycles")
        return
        
    # Select cycle
    if cycle_index == 'middle':
        cycle_idx = len(peaks) // 2
    elif isinstance(cycle_index, int):
        cycle_idx = min(cycle_index, len(peaks)-2)
    else:
        cycle_idx = 0
        
    start_peak = peaks[cycle_idx]
    next_trough = troughs[troughs > start_peak][0] if any(troughs > start_peak) else troughs[-1]
    next_peak = peaks[peaks > next_trough][0] if any(peaks > next_trough) else peaks[-1]
    
    cycle_start = tip_data['TimeSec'].iloc[start_peak]
    mid_cycle = tip_data['TimeSec'].iloc[next_trough]
    cycle_end = tip_data['TimeSec'].iloc[next_peak]
    cycle_duration = cycle_end - cycle_start

    print(f"Visualizing cycle {cycle_idx+1} ({cycle_duration:.3f}s total)")
    print(f"Downstroke: {cycle_start:.3f}s to {mid_cycle:.3f}s")
    print(f"Upstroke: {mid_cycle:.3f}s to {cycle_end:.3f}s")

    # Create figure with two 3D subplots
    fig = plt.figure(figsize=(16, 10))
    ax_down = fig.add_subplot(121, projection='3d')
    ax_up = fig.add_subplot(122, projection='3d')

    # Colormap normalized to cycle duration
    cmap = plt.get_cmap('plasma')
    norm = plt.Normalize(cycle_start, cycle_end)

    # Plot trajectories for each phase
    for t in unique_times:
        if t < cycle_start or t > cycle_end:
            continue
            
        time_slice = filtered_data[filtered_data['TimeSec'] == t]
        coords = []
        for marker in wing_markers:
            marker_row = time_slice[time_slice['makerName'] == marker]
            if not marker_row.empty:
                coords.append([
                    marker_row['makerX'].values[0],
                    marker_row['makerY'].values[0],
                    marker_row['makerZ'].values[0]
                ])
        coords = np.array(coords)
        if len(coords) < 3:
            continue

        # Create 3D convex hull
        try:
            hull = ConvexHull(coords[:, :3])
            tris = coords[hull.simplices]
            color = cmap(norm(t))
            plane_color = (*color[:3], 0.3)  # Semi-transparent
            
            if t <= mid_cycle:  # Downstroke
                ax_down.add_collection3d(Poly3DCollection(
                    tris,
                    facecolors=[plane_color],
                    edgecolors='none',
                    linewidths=0
                ))
            else:  # Upstroke
                ax_up.add_collection3d(Poly3DCollection(
                    tris,
                    facecolors=[plane_color],
                    edgecolors='none',
                    linewidths=0
                ))
        except:
            continue

        # Plot markers
        marker_color = 'lightyellow' if t <= mid_cycle else 'lightcyan'
        ax = ax_down if t <= mid_cycle else ax_up
        ax.scatter(coords[:,0], coords[:,1], coords[:,2], 
                  c=marker_color, edgecolor='gray', s=20, alpha=0.8)

    # Configure downstroke plot
    ax_down.set_title(f'Downstroke (Cycle {cycle_idx+1})')
    ax_down.set_xlabel('X (mm)')
    ax_down.set_ylabel('Y (mm)')
    ax_down.set_zlabel('Z (mm)')
    ax_down.set_box_aspect([1,1,1])

    # Configure upstroke plot
    ax_up.set_title(f'Upstroke (Cycle {cycle_idx+1})')
    ax_up.set_xlabel('X (mm)')
    ax_up.set_ylabel('Y (mm)')
    ax_up.set_zlabel('Z (mm)')
    ax_up.set_box_aspect([1,1,1])

    # TODO Change here for view angle
    ax_down.view_init(elev=33, azim=6, roll=1)
    ax_up.view_init(elev=33, azim=6, roll=1)
    # ax_down.view_init(elev=30, azim=-170, roll=0)
    # ax_up.view_init(elev=30, azim=-170, roll=0)

    # Create normalized colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax_down, ax_up], 
                       orientation='horizontal',
                       fraction=0.05, 
                       pad=0.05,
                       aspect=50)
    
    # Get the colorbar axes and reposition manually
    cbar_ax = cbar.ax
    pos = cbar_ax.get_position()
    cbar_ax.set_position([pos.x0, pos.y0 - 0.08, pos.width, pos.height])  # move down 8å%
    
    # Set ticks to show cycle progression
    cbar.set_ticks([cycle_start, mid_cycle, cycle_end])
    cbar.set_ticklabels(['0.0\n(Downstroke start)', 
                        f'{(mid_cycle-cycle_start)/cycle_duration:.2f}\n(Transition)', 
                        '1.0\n(Upstroke end)'])
    cbar.set_label('Normalized Cycle Time', fontsize=10)

    plt.tight_layout(rect=[0, 0.1, 1, 1])
    fig.savefig(f'{figure_prefix}_wing_3d_single_wingstroke_normalized.png', 
               dpi=300, 
               bbox_inches='tight')
    plt.show()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Plot 3D wing trajectories with cycle-normalized time.')
    parser.add_argument('-r', '--rigid_id', type=str, 
                       default='Rigid_WingLite_R_FullWing',
                       help='Marker prefix (e.g., Rigid_WingLite_R_FullWing)')
    parser.add_argument('-c', '--cycle', type=str, default='middle',
                       help='Cycle index ("middle" or integer)')
    args = parser.parse_args()

    try:
        cycle_index = int(args.cycle)
    except ValueError:
        cycle_index = args.cycle

    file_path = 'data20250522/wing_kinematics_airpulselite/20250522_182851_motion_data.csv'
    prefix = file_path.rsplit('_motion_data', 1)[0]
    plot_wing_phases(file_path, args.rigid_id, prefix, cycle_index=cycle_index)