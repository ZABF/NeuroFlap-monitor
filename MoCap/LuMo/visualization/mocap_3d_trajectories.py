'''
visualization/mocap_3d_trajectories.py: Visualizes 3D flight trajectories from MoCap data.

Features:
- Loads and processes all qualifying CSV files from a specified directory.
- Supports rigid body filtering to isolate specific tracked objects (e.g., "Rigid_APLite").
- Generates interactive 3D trajectory plots with customizable viewing angles.

Usage:
  python mocap_3d_trajectories.py -d <data_directory> [--rigid_filter]

Arguments:
  -d, --data_dir      Path to directory containing MoCap CSV files 
  -f, --rigid_filter  Enable rigid body filtering (default: False)
'''
import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
import argparse

def plot_all_3d_trajectories(data_folder='data/', rigid_body_filter=False, figsize=(12, 9)):
    """
    Enhanced 3D trajectory visualization with:
    - Equal X/Y grid spacing
    - Visible start/end markers
    - Optimized legend placement
    - Tightened title spacing
    """
    # Find CSV files
    csv_files = (glob.glob(os.path.join(data_folder, '*_motion_data.csv')) + 
                glob.glob('*_motion_data.csv'))
    
    if not csv_files:
        print("No motion data files found!")
        return None

    # Create figure with professional layout
    fig = plt.figure(figsize=figsize, dpi=120)
    ax = fig.add_subplot(111, projection='3d')
    
    # Color palette
    colors = plt.cm.tab20(np.linspace(0, 1, len(csv_files)))
    
    # Store all coordinates
    all_coords = {'x': [], 'y': [], 'z': []}
    
    # Process each file
    for i, csv_file in enumerate(csv_files):
        base_name = os.path.basename(csv_file).replace('_motion_data.csv', '')
        
        try:
            df = pd.read_csv(csv_file)

            if rigid_body_filter:
                RIGIDBODY_NAME = 'Rigid_APLite'
                df = df[df['RigidBody_Name'] == RIGIDBODY_NAME].copy()   

            rigid_bodies = df['RigidBody_Name'].unique()
            
            for rigid_body in rigid_bodies:
                body_data = df[df['RigidBody_Name'] == rigid_body]
                if len(body_data) < 2:
                    continue
                
                # Store coordinates
                for axis in ['X', 'Y', 'Z']:
                    all_coords[axis.lower()].extend(body_data[axis])
                
                # Plot trajectory (main line)
                line = ax.plot(
                    body_data['X'], body_data['Y'], body_data['Z'],
                    color=colors[i],
                    alpha=0.8,
                    linewidth=2.2,
                    label=f"{base_name.replace('_', ' ')} - {rigid_body}"
                )[0]
                
                # Enhanced start/end markers (preserved)
                ax.scatter(
                    body_data['X'].iloc[0], body_data['Y'].iloc[0], body_data['Z'].iloc[0],
                    color=colors[i], marker='o', s=80, 
                    edgecolor='white', linewidth=1.2, zorder=10
                )
                ax.scatter(
                    body_data['X'].iloc[-1], body_data['Y'].iloc[-1], body_data['Z'].iloc[-1],
                    color=colors[i], marker='X', s=90, 
                    edgecolor='white', linewidth=1.2, zorder=10
                )
                
        except Exception as e:
            print(f"Skipping {csv_file}: {str(e)}")
            continue
    
    # Equal X/Y grid calculation
    if all_coords['x'] and all_coords['y']:
        max_range = max(max(all_coords['x']) - min(all_coords['x']), 
                       max(all_coords['y']) - min(all_coords['y'])) * 0.55
        mid_x = (max(all_coords['x']) + min(all_coords['x'])) / 2
        mid_y = (max(all_coords['y']) + min(all_coords['y'])) / 2
        
        ax.set_xlim(mid_x - max_range, mid_x + max_range)
        ax.set_ylim(mid_y - max_range, mid_y + max_range)
    
    # Equal aspect ratio
    try:
        ax.set_box_aspect([1, 1, 1])
    except:
        pass
    
    # Reference frame
    axis_length = max(200, max_range*0.15) if 'max_range' in locals() else 200
    for vec, color in zip([[1,0,0], [0,1,0], [0,0,1]], ['#FF355E', '#3CB371', '#4682B4']):
        ax.quiver(0, 0, 0, *vec, color=color, 
                 arrow_length_ratio=0.1, linewidth=1.8, alpha=0.9)
    
    # Adjustable grid style
    ax.grid(True, linestyle=':', linewidth=0.6, alpha=0.5)
    
    # Optimized title and labels
    ax.set_title("3D Flight Trajectories", fontsize=14, pad=15, loc='right', x=0.8)
    ax.set_xlabel('X (mm)', fontsize=10, labelpad=8)
    ax.set_ylabel('Y (mm)', fontsize=10, labelpad=8)
    ax.set_zlabel('Z (mm)', fontsize=10, labelpad=8)
    ax.view_init(elev=30, azim=-59, roll=1)
    
    # Perfectly positioned legend
    legend = ax.legend(
        bbox_to_anchor=(1.28, 0.92),  # Moved further right
        frameon=True,
        framealpha=0.92,
        edgecolor='#333333',
        facecolor='white',
        title="Experiment - Rigid Body",
        title_fontsize=9,
        fontsize=9,
        borderpad=0.8,
        handlelength=1.5
    )
    
    # Adjust layout to prevent clipping
    plt.tight_layout(rect=[0, 0, 0.85, 1])  # Right margin for legend
    
    return fig

# Example usage
if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--data_dir', default='data', help="Path to data folder")
    parser.add_argument('-f', '--rigid_filter', action='store_true', default=False, help="Enable rigid body filtering (default: False)")
    args = parser.parse_args()
    
    fig = plot_all_3d_trajectories(data_folder=args.data_dir, rigid_body_filter=args.rigid_filter)
    if fig:
        fig.savefig('3d_trajectories.png', dpi=300, bbox_inches='tight')
        plt.show()