"""
This script reads motion capture marker trajectory data from a CSV file and plots 3D trajectories 
for markers that start with a specified prefix.

Features:
- Filters markers based on the given prefix (e.g., 'Rigid2').
- Plots 3D trajectories with light gray lines for continuity.
- Colors the marker points based on normalized timestamp using the 'plasma' colormap.
- Assigns unique marker shapes to different markers for distinction.
- Uses LaTeX formatting for axis labels, title, and legend for publication-quality figures.
- Displays a vertical colorbar indicating normalized time progression.
- Places the legend outside the main plot area to avoid overlap.
- Saves the figure as a high-resolution PNG file with tight layout and padding.

Usage:
- Specify the marker prefix via command line argument `-r` or `--rigid_id` (default is 'Rigid2').
- The file path for the CSV data is hardcoded but can be updated in the script.
- The figure is saved with a prefix derived from the input filename.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D
import itertools
import argparse

def plot_marker_trajectories(file_path, marker_prefix, figure_prefix):
    # Load the CSV file
    data = pd.read_csv(file_path)

    # Filter rows where markerName starts with the specified prefix
    filtered_data = data[data['makerName'].str.startswith(marker_prefix, na=False)]

    if filtered_data.empty:
        print(f'No data found for markers starting with {marker_prefix}')
        return

    # Example mapping dictionary
    marker_name_map = {
        'Rigid2Marker20202': r'$0$',
        'Rigid2Marker20200': r'$\frac{1}{3} L_{rod}$',
        'Rigid2Marker20203': r'$\frac{2}{3} L_{rod}$',
        'Rigid2Marker20201': r'$L_{rod}$',
    }

    # Define marker shapes (using a distinct triangle for the first one)
    marker_shapes = itertools.cycle(['^', 'o', 's', 'd', 'p', '*', 'h'])

    # Plot the trajectories for each marker
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    cmap = plt.get_cmap('viridis')

    # Plot markers in the specified order
    for marker_name in marker_name_map.keys():
        marker_data = filtered_data[filtered_data['makerName'] == marker_name]
        if marker_data.empty:
            continue
        x = marker_data['makerX']
        y = marker_data['makerY']
        z = marker_data['makerZ']
        time = marker_data['TimeStamp']

        # Normalize time for color mapping
        norm_time = (time - time.min()) / (time.max() - time.min())
        colors = cmap(norm_time)

        # Assign a unique marker shape for each marker
        marker_shape = next(marker_shapes)

        # Get the mapped label or use the original name
        label = marker_name_map.get(marker_name, marker_name)

        # Plot the trajectory curve in light gray
        ax.plot(x, y, z, color='lightgray', linewidth=0.8, alpha=0.7)

        # Plot with varying colors and markers
        ax.scatter(x, y, z, c=norm_time, cmap='viridis', marker=marker_shape, label=label, edgecolor='black', linewidth=0.1)

    # Add color bar for time
    sc = ax.scatter([], [], [], c=[], cmap='viridis')
    cbar = fig.colorbar(sc, ax=ax, orientation='vertical', pad=0.1)
    cbar.set_label('Normalized Time')

    ax.set_title(f'Trajectories of markers starting with {marker_prefix}')
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    ax.legend()

    # fig.savefig(f'{figure_prefix}_marker_trajectories.png', dpi=300, bbox_inches='tight')

    plt.show()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Plot marker trajectories from motion capture data.')
    parser.add_argument('-r', '--rigid_id', type=str, default='Rigid2', help='Marker prefix (e.g., Rigid2)')
    args = parser.parse_args()

    # Example usage
    file_path = 'data/WingKinematics/20250516_203127_motion_data_marker_points.csv'  # TODO: Update with actual file path
    prefix = file_path.rsplit('_motion_data', 1)[0]

    plot_marker_trajectories(file_path, args.rigid_id, prefix)
