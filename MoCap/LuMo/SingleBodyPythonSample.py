import LuMoSDKClient
import csv
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import matplotlib as mpl

# Set professional style
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

def plot_3d_velocity(df, rigid_body_name='Rigid2', figsize=(8, 6)):
    """Compact 3D trajectory plot"""
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
    cbar.set_label('Speed (mm/s)', rotation=270, labelpad=15)
    
    # Key points
    ax.plot(body_data['X'].iloc[[0,-1]], 
           body_data['Y'].iloc[[0,-1]], 
           body_data['Z'].iloc[[0,-1]], 
           'r-', lw=1, alpha=0.3)
    ax.scatter(body_data['X'].iloc[0], body_data['Y'].iloc[0], body_data['Z'].iloc[0],
              s=30, c='lime', edgecolor='k', label='Start')
    ax.scatter(body_data['X'].iloc[-1], body_data['Y'].iloc[-1], body_data['Z'].iloc[-1],
              s=30, c='red', edgecolor='k', label='End')
    
    # Labels
    ax.set(xlabel='X (mm)', ylabel='Y (mm)', zlabel='Z (mm)',
          title=f'{rigid_body_name} Trajectory by Speed')
    ax.legend(loc='upper right', framealpha=1)
    
    return fig

def plot_2d_projections(df, rigid_body_name='Rigid2', figsize=(8, 3)):
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
                label='Speed (mm/s)', pad=0.05)
    
    fig.suptitle(f'{rigid_body_name} Projections', y=1.05)
    return fig

def plot_velocity_components(df, rigid_body_name='Rigid2', figsize=(8, 3)):
    """Compact velocity time series"""
    body_data = df[df['RigidBody_Name'] == rigid_body_name]
    
    fig, ax = plt.subplots(figsize=figsize)
    
    components = {
        'SpeedX': 'X Velocity',
        'SpeedY': 'Y Velocity',
        'SpeedZ': 'Z Velocity',
        'Speed': 'Total Velocity'
    }
    
    for col, label in components.items():
        if col in body_data:
            ax.plot(body_data['TimeStamp'], body_data[col], 
                   label=label, lw=1, alpha=0.8)
    
    ax.set(xlabel='Time', ylabel='Velocity (mm/s)',
          title=f'{rigid_body_name} Velocity Components')
    ax.legend(ncol=2, loc='upper right')
    ax.grid(True, alpha=0.2)
    plt.xticks(rotation=45)
    return fig

def plot_euler_angles(df, rigid_body_name='Rigid2', figsize=(8, 4)):
    """
    Plot Euler angles (X, Y, Z) over time with proper formatting
    """
    # Filter data for specified rigid body
    body_data = df[df['RigidBody_Name'] == rigid_body_name].copy()
    
    if body_data.empty:
        raise ValueError(f"No data found for RigidBody: {rigid_body_name}")
    
    # Create figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Plot each Euler angle
    angles = ['EulerX', 'EulerY', 'EulerZ']
    labels = ['Roll (X)', 'Pitch (Y)', 'Yaw (Z)']
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']  # Colorblind-friendly
    
    for angle, label, color in zip(angles, labels, colors):
        if angle in body_data.columns:
            ax.plot(body_data['TimeStamp'], body_data[angle], 
                   label=label, color=color, linewidth=1.5, alpha=0.8)
    
    # Formatting
    ax.set_title(f'Euler Angles: {rigid_body_name}', pad=12)
    ax.set_ylabel('Angle (degrees)')
    ax.set_xlabel('Time')
    ax.legend(loc='upper right', framealpha=1)
    ax.grid(True, alpha=0.3)
    
    # Improve x-axis formatting for timestamps
    if pd.api.types.is_datetime64_any_dtype(body_data['TimeStamp']):
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.xticks(rotation=45)
        fig.autofmt_xdate()  # Auto-rotate for better fit
    
    return fig

# 创建 CSV 文件
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_filename = f"{timestamp}_motion_data.csv"
csv_file = open(csv_filename, 'w', newline='', encoding='utf-8')
csv_writer = csv.writer(csv_file)

# 写入表头
header = ['FrameID', 'TimeStamp', 'CameraSyncTime', 'BroadcastTime',
          'RigidBody_ID', 'RigidBody_Name', 'X', 'Y', 'Z',
          'qx', 'qy', 'qz', 'qw', 'QualityGrade',
          'Speed', 'SpeedX', 'SpeedY', 'SpeedZ',
          'Acc', 'AccX', 'AccY', 'AccZ',
          'EulerX', 'EulerY', 'EulerZ',
          'AngularVelX', 'AngularVelY', 'AngularVelZ',
          'AngularAccX', 'AngularAccY', 'AngularAccZ']
csv_writer.writerow(header)

ip = "192.168.0.235"
try:
    LuMoSDKClient.Init()
    LuMoSDKClient.Connnect(ip)

    while True:
        frame = LuMoSDKClient.ReceiveData(0) # 0 :阻塞接收 1：非阻塞接收
        if frame is None:
            continue
        FrameID = frame.FrameId
        print(FrameID) #打印帧ID
        TimeStamp = frame.TimeStamp
        print("timestamp")
        print(TimeStamp) #打印当前帧时间戳
        uCameraSyncTime = frame.uCameraSyncTime
        print("uCamera")
        print(uCameraSyncTime) #打印相机同步时间
        uBroadcastTime = frame.uBroadcastTime
        print("uBroadcast")
        print(uBroadcastTime) #打印数据广播时间

        frame_data = [
                frame.FrameId,
                frame.TimeStamp,
                frame.uCameraSyncTime,
                frame.uBroadcastTime
            ]
        

        markers = frame.markers
        for marker in markers:
            print(marker.Id)  #打印散点ID
            print(marker.Name) #打印散点名称
            print(marker.X)  #打印散点的坐标数据 :X
            print(marker.Y)  #打印散点的坐标数据 :Y
            print(marker.Z)  #打印散点的坐标数据 :Z
        for rigid in frame.rigidBodys:
            if rigid.IsTrack is True: #判断刚体追踪状态
                print(rigid.Id)  #打印刚体ID
                print(rigid.Name) #打印刚体名称
                print(rigid.X)  #打印刚体坐标信息：X
                print(rigid.Y)  #打印刚体坐标信息：Y
                print(rigid.Z)  #打印刚体坐标信息：Z
                print(rigid.qx)  #打印刚体姿态信息：qx
                print(rigid.qy)  #打印刚体姿态信息：qy
                print(rigid.qz)  #打印刚体姿态信息：qz
                print(rigid.qw)  #打印刚体姿态信息：qw
                print(rigid.QualityGrade)   #打印刚体质量等级
                print(rigid.speeds.fSpeed)  #打印刚体速度
                print(rigid.speeds.XfSpeed) #打印刚体x轴方向速度
                print(rigid.speeds.YfSpeed) #打印刚体y轴方向速度
                print(rigid.speeds.ZfSpeed) #打印刚体z轴方向速度
                print(rigid.acceleratedSpeeds.fAcceleratedSpeed)  #打印刚体加速度
                print(rigid.acceleratedSpeeds.XfAcceleratedSpeed) #打印刚体x轴方向加速度
                print(rigid.acceleratedSpeeds.YfAcceleratedSpeed) #打印刚体y轴方向加速度
                print(rigid.acceleratedSpeeds.ZfAcceleratedSpeed) #打印刚体z轴方向加速度
                print(rigid.eulerAngle.X)  #打印x轴欧拉角
                print(rigid.eulerAngle.Y)  #打印y轴欧拉角
                print(rigid.eulerAngle.Z)  #打印z轴欧拉角
                print(rigid.palstance.fXPalstance) #打印x轴角速度
                print(rigid.palstance.fYPalstance) #打印y轴角速度
                print(rigid.palstance.fZPalstance) #打印z轴角速度
                print(rigid.accpalstance.AccfXPalstance) #打印x轴角加速度
                print(rigid.accpalstance.AccfYPalstance) #打印y轴角加速度
                print(rigid.accpalstance.AccfZPalstance) #打印z轴角加速度
                row_data = frame_data.copy()  # 复制基本数据
                    # 添加刚体数据
                row_data.extend([
                    rigid.Id,
                    rigid.Name,
                    rigid.X,
                    rigid.Y,
                    rigid.Z,
                    rigid.qx,
                    rigid.qy,
                    rigid.qz,
                    rigid.qw,
                    rigid.QualityGrade,
                    rigid.speeds.fSpeed,
                    rigid.speeds.XfSpeed,
                    rigid.speeds.YfSpeed,
                    rigid.speeds.ZfSpeed,
                    rigid.acceleratedSpeeds.fAcceleratedSpeed,
                    rigid.acceleratedSpeeds.XfAcceleratedSpeed,
                    rigid.acceleratedSpeeds.YfAcceleratedSpeed,
                    rigid.acceleratedSpeeds.ZfAcceleratedSpeed,
                    rigid.eulerAngle.X,
                    rigid.eulerAngle.Y,
                    rigid.eulerAngle.Z,
                    rigid.palstance.fXPalstance,
                    rigid.palstance.fYPalstance,
                    rigid.palstance.fZPalstance,
                    rigid.accpalstance.AccfXPalstance,
                    rigid.accpalstance.AccfYPalstance,
                    rigid.accpalstance.AccfZPalstance
                ])
                # 写入 CSV
                csv_writer.writerow(row_data)
                # 定期刷新文件缓冲区
                # if frame.FrameId % 100 == 0:  # 每100帧刷新一次
                csv_file.flush()
            else:
                print(rigid.Id)  #打印刚体ID

        for skeleton in frame.skeletons:
            if skeleton.IsTrack is True:
                print(skeleton.Id)   #打印人体ID
                print(skeleton.Name) #打印人体名称
                for bone in skeleton.skeletonBones:
                    print(bone.Id)   #打印人体内骨骼ID
                    print(bone.Name) #打印人体内骨骼名称
                    print(bone.X)    #打印人体内骨骼坐标：X
                    print(bone.Y)    #打印人体内骨骼坐标：Y
                    print(bone.Z)    #打印人体内骨骼坐标：Z
                    print(bone.qx)   #打印人体内骨骼姿态：qx
                    print(bone.qy)   #打印人体内骨骼姿态：qy
                    print(bone.qz)   #打印人体内骨骼姿态：qz
                    print(bone.qw)   #打印人体内骨骼姿态：qw
                print(skeleton.RobotName) #打印机器人名称
                for Key in skeleton.MotorAngle:
                    print(Key)         #打印机器人电机名称
                    print(skeleton.MotorAngle[Key])  #打印机器人电机角度值
            else:
                print(skeleton.Id)   #打印人体ID
        for markerset in frame.markerSet:
            print(markerset.Name)  #打印点集名称
            for marker in markerset.markers:
                print(marker.Id)   #打印点集内点ID
                print(marker.Name) #打印点集内点名称
                print(marker.X)    #打印点集内点坐标：X
                print(marker.Y)    #打印点集内点坐标：Y
                print(marker.Z)    #打印点集内点坐标：Z

        #时码信息
        print(frame.timeCode.mHours)   #打印时码：时
        print(frame.timeCode.mMinutes) #打印时码：分
        print(frame.timeCode.mSeconds) #打印时码：秒
        print(frame.timeCode.mFrames)  #打印时码：帧
        print(frame.timeCode.mSubFrame)#打印时码：子帧

    #自定义骨骼信息
        for CustomSkeleton in frame.customSkeleton:
            print(CustomSkeleton.Id)  #打印自定义骨骼ID
            print(CustomSkeleton.Name) #打印自定义骨骼名称
            print(CustomSkeleton.Type) #打印自定义骨骼类型
            for JointData in CustomSkeleton.customSkeletonBones:
                print(JointData.Id)   #打印自定义骨骼内骨骼ID
                print(JointData.Name) #打印自定义骨骼内骨骼名称
                print(JointData.X)    #打印自定义骨骼内骨骼坐标：X
                print(JointData.Y)    #打印自定义骨骼内骨骼坐标：Y
                print(JointData.Z)    #打印自定义骨骼内骨骼坐标：Z
                print(JointData.qx)   #打印自定义骨骼内骨骼姿态：qx
                print(JointData.qy)   #打印自定义骨骼内骨骼姿态：qy
                print(JointData.qz)   #打印自定义骨骼内骨骼姿态：qz
                print(JointData.qw)   #打印自定义骨骼内骨骼姿态：qw
                print(JointData.Confidence)  #打印自定义骨骼内骨骼置信度
                print(JointData.AngleX)  #打印自定义骨骼内骨骼姿态角：X
                print(JointData.AngleY)  #打印自定义骨骼内骨骼姿态角: Y
                print(JointData.AngleZ)  #打印自定义骨骼内骨骼姿态角: Z


        newForceplate = frame.ForcePlate
        for Key in newForceplate.ForcePlateData:
            print(Key)         #打印测力台ID
            print(newForceplate.ForcePlateData[Key].Fx)  #打印测力台矢量力的分量：Fx
            print(newForceplate.ForcePlateData[Key].Fy)  #打印测力台矢量力的分量：Fy
            print(newForceplate.ForcePlateData[Key].Fz)  #打印测力台矢量力的分量：Fz
            print(newForceplate.ForcePlateData[Key].Mx)  #力矩：X
            print(newForceplate.ForcePlateData[Key].My)  #力矩：Y
            print(newForceplate.ForcePlateData[Key].Mz)  #力矩：Z
            print(newForceplate.ForcePlateData[Key].Lx)  #压心坐标
            print(newForceplate.ForcePlateData[Key].Lz)  #压心坐标

except KeyboardInterrupt:
    print("程序被用户中断")

    # trial_prefix = "01"
    df = load_data(csv_filename)
    
    # Generate properly sized figures
    fig1 = plot_3d_velocity(df, figsize=(6, 5))
    fig2 = plot_2d_projections(df, figsize=(7, 2.5))
    fig3 = plot_velocity_components(df, figsize=(7, 2.5))
    fig4 = plot_euler_angles(df, figsize=(7, 3.5))
    
    # Save with tight bounding boxes
    fig1.savefig(f'{timestamp}_3d_trajectory.png', bbox_inches='tight', pad_inches=0.1)
    fig2.savefig(f'{timestamp}_2d_projections.png', bbox_inches='tight', pad_inches=0.1)
    fig3.savefig(f'{timestamp}_velocity_components.png', bbox_inches='tight', pad_inches=0.05)
    fig4.savefig(f'{timestamp}_euler_angles.png', bbox_inches='tight', dpi=300, pad_inches=0.1)
    
    plt.show()
finally:
    csv_file.close()
    LuMoSDKClient.Close()

    # df = load_data(csv_filename)
    
    # # Generate properly sized figures
    # fig1 = plot_3d_velocity(df, figsize=(6, 5))
    # fig2 = plot_2d_projections(df, figsize=(7, 2.5))
    # fig3 = plot_velocity_components(df, figsize=(7, 2.5))
    
    # # Save with tight bounding boxes
    # fig1.savefig('3d_trajectory.png', bbox_inches='tight', pad_inches=0.1)
    # fig2.savefig('2d_projections.png', bbox_inches='tight', pad_inches=0.1)
    # fig3.savefig('velocity_components.png', bbox_inches='tight', pad_inches=0.05)
    
    # plt.show()
        




