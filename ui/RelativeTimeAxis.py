from pyqtgraph import AxisItem

class RelativeTimeAxis(AxisItem):
    def __init__(self, orientation='top', **kwargs):
        super().__init__(orientation, **kwargs)
        self.start_time = 0  # 窗口起点时间戳（ms）

    def set_start_time(self, start_time):
        self.start_time = start_time

    def tickStrings(self, values, scale, spacing):
        # 返回相对时间（单位 ms）
        return [f"{int(v - self.start_time)}" for v in values]
        # 或者返回以秒为单位（保留一位小数）：
        # return [f"{(v - self.start_time)/1000:.1f}s" for v in values]
