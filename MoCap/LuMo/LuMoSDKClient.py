import zmq
import MoCap.LuMo.LusterFrameStruct_pb2 as LusterFrameStruct_pb2

def Init():
    context = zmq.Context()
    global subscriber
    subscriber = context.socket(zmq.SUB)

def Connnect(ip):
    subscriber.setsockopt(zmq.CONFLATE, 1)
    connectIp = "tcp://" + ip + ":6868"
    subscriber.connect(connectIp)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")

def Close():
    return subscriber.close()

def ReceiveData(flag):
    frame = LusterFrameStruct_pb2.Frame()
    if flag == 0:
        message = subscriber.recv()  
    elif flag == 1:
        try:
            message = subscriber.recv(zmq.DONTWAIT)
        except zmq.Again:
            return
    else:
        return
    frame.ParseFromString(message)
    return frame