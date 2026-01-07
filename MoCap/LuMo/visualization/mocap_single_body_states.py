"""
3D Motion Data Visualization Script for Rigid Body from the MoCap System

This script processes and visualizes 3D motion data recorded from AirPulse, 
using a professional plotting style. It includes features for customizable 
analysis of rigid body trajectories and visualizes key metrics.

Main Features:
1. Data Loading:
   - Uses a customizable data file path.
   - Supports motion data from CSV files.

2. Visualization:
   - 3D Trajectory Plot: Displays the velocity in 3D space.
   - 2D Projection Plots: Visualizes velocity projections on 2D planes.
   - Velocity Component Plot: Separates individual velocity components.
   - Euler Angles Plot: Illustrates the orientation over time.
   - Customizable Rigid Body ID: Analyzes specified rigid body via command-line arguments.

3. Professional Plotting:
   - Utilizes a consistent, professional plotting style for clear presentations.
   - Generates figures with appropriate dimensions and saves them with tight bounding boxes.

4. Error Handling:
   - Catches and reports errors during data loading or visualization.

Usage:
- Run the script with the following optional argument:
  python script.py -r <rigid_id>
- Replace the data file path as needed in the script.

Requirements:
- Python packages: pandas, matplotlib, argparse, sys, pathlib
- Custom modules: CustomFunc (with functions for setting style and plotting)
"""

import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import matplotlib as mpl
import argparse
import os

import sys
from pathlib import Path
# Get the parent directory of the current script's directory
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

from CustomFunc import set_professional_plotting_style, load_data, plot_3d_velocity, plot_2d_projections, plot_euler_angles, plot_velocity_components

# Set professional style
set_professional_plotting_style()

if __name__ == "__main__":
    try:
      #   datafile = 'data/20250516_192102_motion_data.csv' # TODO: Replace here if needed.
      #   datafile = 'data/WingKinematics/20250516_203127_motion_data_marker_points.csv'
        datafile = '20250522_181938_motion_data.csv'
        df = load_data(datafile)
        prefix = datafile.rsplit('_motion_data', 1)[0]
        print(prefix)

        # Set up argument parser
        parser = argparse.ArgumentParser(description='Process motion data.')
        parser.add_argument('-r', '--rigid_id', type=str, default="Rigid0",
                          help='The rigid body ID to analyze (default: Rigid0)')
        
        args = parser.parse_args()
        
        # Generate properly sized figures
        fig1 = plot_3d_velocity(df, rigid_body_name=args.rigid_id, figsize=(6, 5))
        fig2 = plot_2d_projections(df, rigid_body_name=args.rigid_id, figsize=(6, 3.5))
        fig3 = plot_velocity_components(df, rigid_body_name=args.rigid_id, figsize=(7, 2.5))
        fig4 = plot_euler_angles(df, rigid_body_name=args.rigid_id, figsize=(7, 3.5))
        
        # Save with tight bounding boxes
        fig1.savefig(f'{prefix}_3d_trajectory.png', bbox_inches='tight', pad_inches=0.1)
        fig2.savefig(f'{prefix}_2d_projections.png', bbox_inches='tight', pad_inches=0.1)
        fig3.savefig(f'{prefix}_velocity_components.png', bbox_inches='tight', pad_inches=0.05)
        fig4.savefig(f'{prefix}_euler_angles.png', bbox_inches='tight', dpi=300, pad_inches=0.1)
        
        plt.show()
        
    except Exception as e:
        print(f"Error: {str(e)}")