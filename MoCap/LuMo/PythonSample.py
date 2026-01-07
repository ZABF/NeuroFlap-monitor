import LuMoSDKClient

# ip = '192.168.31.44' #"127.0.0.1"
ip = '172.20.10.4'
# ip = '169.254.179.2'
# ip = '169.254.15.56'

LuMoSDKClient.Init()
LuMoSDKClient.Connnect(ip)

while True:
    frame = LuMoSDKClient.ReceiveData(0) # 0 :阻塞接收 1：非阻塞接收
    if frame is None:
        continue
    FrameID = frame.FrameId
    print(FrameID) #打印帧ID
    TimeStamp = frame.TimeStamp
    print(TimeStamp) #打印当前帧时间戳
    uCameraSyncTime = frame.uCameraSyncTime
    print(uCameraSyncTime) #打印相机同步时间
    uBroadcastTime = frame.uBroadcastTime
    print(uBroadcastTime) #打印数据广播时间
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

LuMoSDKClient.Close()