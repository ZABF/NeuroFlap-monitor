import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

def set_professional_plotting_style():
    plt.style.use('default')  # Clean base style
    mpl.rcParams.update({
        'font.size': 9,
        'axes.titlesize': 10,
        'axes.labelsize': 9,
        'xtick.labelsize': 8,
        'ytick.labelsize': 8,
        'legend.fontsize': 8,
        'figure.dpi': 300,
        'savefig.dpi': 300,
        'figure.autolayout': True
    })

def load_data(filename):
    """Load data with efficient parsing"""
    return pd.read_csv(filename, parse_dates=['TimeStamp'], 
                     infer_datetime_format=True)

def plot_3d_velocity(df, rigid_body_name='Rigid2', figsize=(6, 5)):
    """Compact 3D trajectory plot with equal-length reference frame"""
    body_data = df[df['RigidBody_Name'] == rigid_body_name]
    
    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection='3d')
    
    # Main trajectory
    sc = ax.scatter(
        body_data['X'], body_data['Y'], body_data['Z'],
        c=body_data['Speed'],
        cmap='viridis',
        s=8,
        alpha=0.7,
        linewidths=0
    )
    
    # Colorbar
    cbar = fig.colorbar(sc, ax=ax, shrink=0.6, aspect=20, pad=0.1)
    cbar.set_label('Speed (m/s)', rotation=270, labelpad=15)
    
    # Key points
    ax.plot(body_data['X'].iloc[[0,-1]], 
           body_data['Y'].iloc[[0,-1]], 
           body_data['Z'].iloc[[0,-1]], 
           'r-', lw=1, alpha=0.3)
    ax.scatter(body_data['X'].iloc[0], body_data['Y'].iloc[0], body_data['Z'].iloc[0],
              s=30, c='lime', edgecolor='k', label='Start')
    ax.scatter(body_data['X'].iloc[-1], body_data['Y'].iloc[-1], body_data['Z'].iloc[-1],
              s=30, c='red', edgecolor='k', label='End')
    
    # Determine axis limits based on data
    max_range = max(
        body_data['X'].max() - body_data['X'].min(),
        body_data['Y'].max() - body_data['Y'].min(),
        body_data['Z'].max() - body_data['Z'].min()
    ) * 0.6  # Scale to 60% of max range for better visibility
    
    mid_x = (body_data['X'].max() + body_data['X'].min()) * 0.5
    mid_y = (body_data['Y'].max() + body_data['Y'].min()) * 0.5
    mid_z = (body_data['Z'].max() + body_data['Z'].min()) * 0.5
    
    # Set equal limits
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)
    
    # Add reference frame at origin (equal-length axes)
    axis_length = max_range * 0.15  # Scale to 80% of max_range
    
    # X axis (red)
    ax.quiver(0, 0, 0, axis_length, 0, 0, color='r', arrow_length_ratio=0.1, linewidth=2)
    # Y axis (green)
    ax.quiver(0, 0, 0, 0, axis_length, 0, color='g', arrow_length_ratio=0.1, linewidth=2)
    # Z axis (blue)
    ax.quiver(0, 0, 0, 0, 0, axis_length, color='b', arrow_length_ratio=0.1, linewidth=2)
    
    # Add labels for the axes
    ax.text(axis_length, 0, 0, 'X', color='r', fontsize=8)
    ax.text(0, axis_length, 0, 'Y', color='g', fontsize=8)
    ax.text(0, 0, axis_length, 'Z', color='b', fontsize=8)
    
    # Labels
    ax.set(xlabel='X (mm)', ylabel='Y (mm)', zlabel='Z (mm)',
          title=f'3D Flight Trajectory: {rigid_body_name}')
    ax.legend(loc='upper right', framealpha=1)

    return fig

def plot_2d_projections(df, rigid_body_name='Rigid2', figsize=(6, 3.5)):
    """Compact 2D views with shared colorbar"""
    body_data = df[df['RigidBody_Name'] == rigid_body_name]
    
    fig, axes = plt.subplots(1, 3, figsize=figsize, 
                            sharey=False, gridspec_kw={'wspace': 0.4})
    
    # Shared color normalization
    norm = mpl.colors.Normalize(
        vmin=body_data['Speed'].min(),
        vmax=body_data['Speed'].max()
    )
    
    # Plot each plane
    planes = [('XY', 'X', 'Y'), ('XZ', 'X', 'Z'), ('YZ', 'Y', 'Z')]
    for ax, (title, x, y) in zip(axes, planes):
        sc = ax.scatter(
            body_data[x], body_data[y],
            c=body_data['Speed'],
            cmap='viridis',
            norm=norm,
            s=6,
            alpha=0.7
        )
        ax.set(xlabel=f'{x} (mm)', ylabel=f'{y} (mm)', title=title)
        ax.grid(True, alpha=0.2)
    
    # Single colorbar
    fig.colorbar(sc, ax=axes.tolist(), shrink=0.8, aspect=20,
                label='Speed (m/s)', pad=0.05)
    
    fig.suptitle(f'{rigid_body_name} Projections', y=1.05)
    return fig

def plot_velocity_components(df, rigid_body_name='Rigid2', figsize=(7, 2.5)):
    """Compact velocity time series"""
    body_data = df[df['RigidBody_Name'] == rigid_body_name]

    # Convert BroadcastTime (ns) to relative seconds
    start_time = body_data['BroadcastTime'].iloc[0]
    body_data['RelativeTime'] = (body_data['BroadcastTime'] - start_time) / 1e6  # us → s
    
    fig, ax = plt.subplots(figsize=figsize)
    
    components = {
        'SpeedX': 'X Velocity',
        'SpeedY': 'Y Velocity',
        'SpeedZ': 'Z Velocity',
        'Speed': 'Total Velocity'
    }
    
    for col, label in components.items():
        if col in body_data:
            ax.plot(body_data['RelativeTime'], body_data[col], 
                   label=label, lw=1, alpha=0.8)
    
    ax.set(xlabel='Time (seconds)', ylabel='Velocity (m/s)',
          title=f'Linear Velocities: {rigid_body_name}')
    ax.legend(ncol=2, loc='upper right')
    ax.grid(True, alpha=0.2)
    plt.xticks(rotation=45)

    # Auto-adjust x-axis for short/long durations
    max_time = body_data['RelativeTime'].max()
    print(f"max_time: {max_time}")
    if max_time < 1.0:  # Show milliseconds if <1s
        ax.set_xlabel('Time (milliseconds)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x * 1000:.0f}'))
    elif max_time > 60:  # Show minutes if >60s
        ax.set_xlabel('Time (minutes)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x / 60:.1f}'))

    return fig

def plot_euler_angles(df, rigid_body_name='Rigid2', figsize=(7, 3.5)):
    """
    Plot Euler angles (X, Y, Z) over time.
    - Uses BroadcastTime (nanoseconds since Unix epoch) as x-axis.
    - Converts to relative seconds starting from 0.
    """
    # Filter data for the specified rigid body
    body_data = df[df['RigidBody_Name'] == rigid_body_name].copy()
    
    if body_data.empty:
        raise ValueError(f"No data found for RigidBody: {rigid_body_name}")

    # Convert BroadcastTime (ns) to relative seconds
    start_time = body_data['BroadcastTime'].iloc[0]
    body_data['RelativeTime'] = (body_data['BroadcastTime'] - start_time) / 1e6  # us → s

    # Create plot
    fig, ax = plt.subplots(figsize=figsize)
    
    angles = ['EulerX', 'EulerY', 'EulerZ']
    labels = ['Roll (X)', 'Pitch (Y)', 'Yaw (Z)']
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']  # Colorblind-friendly

    for angle, label, color in zip(angles, labels, colors):
        if angle in body_data.columns:
            ax.plot(body_data['RelativeTime'], body_data[angle],
                   label=label, color=color, linewidth=1.5, alpha=0.8)

    # Formatting
    ax.set_title(f'Euler Angles: {rigid_body_name}', pad=12)
    ax.set_ylabel('Angle (degrees)')
    ax.set_xlabel('Time (seconds)')
    ax.legend(loc='upper right', framealpha=1)
    ax.grid(True, alpha=0.3)

    # Auto-adjust x-axis for short/long durations
    max_time = body_data['RelativeTime'].max()
    if max_time < 1.0:  # Show milliseconds if <1s
        ax.set_xlabel('Time (milliseconds)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x * 1000:.0f}'))
    elif max_time > 60:  # Show minutes if >60s
        ax.set_xlabel('Time (minutes)')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x / 60:.1f}'))

    plt.tight_layout()  # Prevent label cutoff
    return fig