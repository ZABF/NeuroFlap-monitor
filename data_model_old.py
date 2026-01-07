from collections import defaultdict, deque
from typing import Dict, Deque, List, Tuple, Any, Optional
from dataclasses import dataclass

@dataclass
class _SourceState:
    last_ts: Optional[float] = None       # 上一次的 source_ts
    session_id: int = 1                   # 当前会话号
    min_offset: Optional[float] = None    # 当前会话已知最小 offset
    first_flag: bool = False              # 当前会话是否已见到第一包
    current_record_idx: Optional[int] = None  # 刚写入的时间戳在 timeline 中的索引

class DataModel_old:
    def __init__(self, variable_names, max_points=100000):
        self.max_points = max_points
        self.source_state = {}
        self.offsets = {}
        self.data = {}
        self._init_variables(variable_names)
        self.session_offsets = {}

    def _init_variables(self, variable_names):
        for var in variable_names:
            self.data[var] = {
                "timestamps": deque(maxlen=self.max_points),
                "device_timestamps": deque(maxlen=self.max_points),
                "values": deque(maxlen=self.max_points),
                "session_ids": deque(maxlen=self.max_points),
            }

    def ensure_variable(self, var_name: str) -> None:
        if var_name not in self.data:
            self.data[var_name] = {
                "timestamps": deque(maxlen=self.max_points),
                "device_timestamps": deque(maxlen=self.max_points),
                "values": deque(maxlen=self.max_points),
                "session_ids": deque(maxlen=self.max_points),
            }


    def add_data(self,var_name, raw_ts, adj_ts, value, session_id):
        if var_name not in self.data:
            self.ensure_variable(var_name)

        slot = self.data[var_name]
        slot["timestamps"].append(raw_ts)
        slot["device_timestamps"].append(adj_ts)
        slot["values"].append(value)
        slot["session_ids"].append(session_id)

    def get_series(self, var_name):
        if var_name in self.data:
            return list(self.data[var_name]["timestamps"]), list(self.data[var_name]["values"])
        return [], []

    def get_series_raw(self, var_name):
        if var_name in self.data:
            return list(self.data[var_name]["device_timestamps"]), list(self.data[var_name]["values"])
        return [], []

    def reapply_offset_for_session(self, session_id, new_offset):

        # 记录当前会会话最小offset
        self.session_offsets[session_id] = new_offset

        # 回填更正当前会话时间戳
        for var_name, slot in self.data.items():
            ts = slot["timestamps"]
            raw_ts = slot["device_timestamps"]
            sess   = slot["session_ids"]

            # 遍历该变量的所有点，回填本会话的 adj_ts
            # 注意：deque 支持索引与赋值操作
            for i in range(len(sess)):
                if sess[i] == session_id:
                    ts[i] = raw_ts[i] + new_offset

    def clear(self):
        for var in self.data:
            self.data[var]["timestamps"].clear()
            self.data[var]["device_timestamps"].clear()
            self.data[var]["values"].clear()
            self.data[var]["session_ids"].clear()

        self.session_offsets.clear()