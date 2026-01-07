import pandas as pd
import numpy as np
import numpy.linalg as la
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
from scipy.signal import find_peaks
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

def plot_wing_phases(file_path, wing_prefix, figure_prefix, cycle_index='middle'):
    # Load and preprocess data
    data = pd.read_csv(file_path)
    filtered_data = data[data['makerName'].str.startswith(wing_prefix, na=False)]

    if filtered_data.empty:
        print(f'No data found for markers starting with {wing_prefix}')
        return

    start_time = filtered_data['BroadcastTime'].iloc[0]
    filtered_data['TimeSec'] = (filtered_data['BroadcastTime'] - start_time) / 1e6
    unique_times = np.sort(filtered_data['TimeSec'].unique())
    wing_markers = filtered_data['makerName'].unique()

    mean_positions = filtered_data.groupby('makerName')[['makerX', 'makerY', 'makerZ']].mean()
    tip_marker = mean_positions['makerX'].idxmax()

    tip_data = filtered_data[filtered_data['makerName'] == tip_marker]
    z_values = tip_data['makerZ'].values
    peaks, _ = find_peaks(z_values, prominence=0.5)
    troughs, _ = find_peaks(-z_values, prominence=0.5)

    if len(peaks) < 2 or len(troughs) < 1:
        print("Couldn't detect complete wing stroke cycles")
        return

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

    fig = plt.figure(figsize=(16, 10))
    ax_down = fig.add_subplot(121, projection='3d')
    ax_up = fig.add_subplot(122, projection='3d')

    cmap = plt.get_cmap('plasma')
    norm = plt.Normalize(cycle_start, cycle_end)

    # 2D wing outline (replace this with real wing coordinates)
    wing_outline_2d = np.array([
        [-1.94, 20.45], [-6.73, 42.25], [-10.22, 65.39], [-11.43, 93.43],
        [-8.31, 120.88], [0.8, 148.4], [18.56, 175.24], [43.33, 193.17],
        [82.32, 196.34], [115.42, 188.28], [130.46, 154.65], [133.95, 125.24],
        [129.04, 102], [111.73, 70.35], [89.67, 47.89], [70.95, 34.16],
        [51.55, 22.49], [70.29, 31.56], [91.09, 42.25], [108.16, 51.31],
        [126.16, 60.29], [139.98, 63.88], [155.47, 60.63], [170.53, 55.39],
        [184.29, 46.19], [197.1, 30.34], [210.68, 7.18], [222.36, -15.77],
        [237.46, -44.3], [251.42, -72.34], [263.57, -97.4], [269.02, -108.64],
        [265.07, -117.4], [254.59, -127.01], [233.19, -135.55], [201.72, -140.1],
        [160.95, -136.8], [119.47, -125.36], [88.12, -110], [54.65, -83.79],
        [31.34, -56.96], [15.65, -30.67], [5.65, -6.05], [-1.94, 20.45]
    ])

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

        try:
            hull = ConvexHull(coords[:, :3])
            tris = coords[hull.simplices]
            color = cmap(norm(t))
            plane_color = (*color[:3], 0.3)

            ax = ax_down if t <= mid_cycle else ax_up
            ax.add_collection3d(Poly3DCollection(tris, facecolors=[plane_color], edgecolors='none', linewidths=0))
        except Exception as e:
            # You can uncomment below for debugging if needed
            # print(f"ConvexHull error at t={t}: {e}")
            continue

        ax = ax_down if t <= mid_cycle else ax_up

        # Plot wing markers
        marker_color = 'lightyellow' if t <= mid_cycle else 'lightcyan'
        ax.scatter(coords[:, 0], coords[:, 1], coords[:, 2], c=marker_color, edgecolor='gray', s=20, alpha=0.8)

        # --- HERE: Align and plot the 2D wing outline in the wing plane ---
        if coords.shape[0] > 2:
            coords_mean = coords.mean(axis=0)
            centered = coords - coords_mean

            # PCA for local wing frame
            U, S, Vt = la.svd(centered)
            normal = Vt[2, :]    # Wing plane normal
            axis1 = Vt[0, :]     # First principal axis (wing span direction)
            axis2 = Vt[1, :]     # Second principal axis (wing chord direction)

            # Build rotation matrix from local 2D coords to 3D wing coords
            rotation = np.column_stack((axis1, axis2, normal))  # 3x3 matrix

            # Prepare 2D outline points (x, y, 0) in local coords
            wing_outline_local = np.column_stack((
                wing_outline_2d[:, 0],
                wing_outline_2d[:, 1],
                np.zeros(len(wing_outline_2d))
            ))

            # Rotate and translate 2D outline into 3D wing plane
            wing_outline_3d = (rotation @ wing_outline_local.T).T + coords_mean

            # Connect outline points as segments for plotting
            segments = [[wing_outline_3d[i], wing_outline_3d[i+1]] for i in range(len(wing_outline_3d)-1)]
            ax.add_collection3d(Line3DCollection(segments, colors='k', linewidths=1.5))

    for ax, label in zip([ax_down, ax_up], ["Downstroke", "Upstroke"]):
        ax.set_title(f'{label} (Cycle {cycle_idx+1})')
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_zlabel('Z (mm)')
        ax.set_box_aspect([1, 1, 1])
        ax.view_init(elev=33, azim=6, roll=1)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax_down, ax_up],
                        orientation='horizontal',
                        fraction=0.05,
                        pad=0.05,
                        aspect=50)

    cbar_ax = cbar.ax
    pos = cbar_ax.get_position()
    cbar_ax.set_position([pos.x0, pos.y0 - 0.08, pos.width, pos.height])

    cbar.set_ticks([cycle_start, mid_cycle, cycle_end])
    cbar.set_ticklabels([
        '0.0\n(Downstroke start)',
        f'{(mid_cycle-cycle_start)/cycle_duration:.2f}\n(Transition)',
        '1.0\n(Upstroke end)'
    ])
    cbar.set_label('Normalized Cycle Time', fontsize=10)

    plt.tight_layout(rect=[0, 0.1, 1, 1])
    fig.savefig(f'{figure_prefix}_wing_3d_single_wingstroke_normalized.png',
                dpi=300, bbox_inches='tight')
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
    prefix = file_path.split('/')[-1].split('_motion')[0]

    plot_wing_phases(file_path=file_path,
                     wing_prefix=args.rigid_id,
                     figure_prefix=prefix,
                     cycle_index=cycle_index)
