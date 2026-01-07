from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Tuple, Deque, Optional
from bisect import bisect_left

@dataclass
class SourceBucket:
    """每个数据源一桶：源时间 + 会话"""
    src: str                                 # 冗余记录源名（也可不存，用外层键）
    src_timestamp: Deque[float] = field(default_factory=deque)  # 设备自带时间
    recon_timestamp: Deque[float] = field(default_factory=deque) # 重建后的timestamp
    session: Deque[int] = field(default_factory=deque)          # 会话号（mocap没有就留空）
    # state
    last_src_timestamp: Optional[float] = None
    current_session: int = 1


@dataclass
class VarBucket:
    """每个变量：绑定来源 + 值序列（与来源时间线按顺序对齐）"""
    var: str    # 冗余记录变量名（也可不存，用外层键）
    src: str    # 数据源
    value: Deque[float] = field(default_factory=deque)

class DataModel:
    def __init__(self, variable_names):
        self.JUMP_THRESHOLD_MS = 200
        self.sources: Dict[str, SourceBucket] = {}  # 源： "udp" | "ft" | "mocap" -> SourceBucket
        self.vars: Dict[str, VarBucket] = {}        # 变量： "pwm" | "roll" ... -> VarBucket（每个变量绑定一个源）
        self.offsets: Dict[Tuple[str, int], float] = {}  # offset 索引: (src, session_id) -> offset（当某变量未单独设定时回退）

    # ---- 确保/获取桶 ----
    def ensure_source(self, src: str):
        b = self.sources.get(src)
        if b is None:
            b = SourceBucket(src=src)
            self.sources[src] = b
        return b

    def ensure_var(self, var: str, src: str):
        b = self.vars.get(var)
        if b is None:
            b = VarBucket(var=var, src=src)
            self.vars[var] = b
        elif b.src != src:
            raise ValueError(f"变量 '{var}' 已绑定来源 '{b.src}'，不能改为 '{src}'")
        return b

    def add_timestamp(self, src: str, src_timestamp: float, recon_timestamp: float, session: int):
        sb = self.ensure_source(src)
        sb.src_timestamp.append(float(src_timestamp))
        sb.recon_timestamp.append(float(recon_timestamp))
        sb.session.append(int(session))

        # 基本一致性：两条 deque 长度应保持一致
        assert len(sb.src_timestamp) == len(sb.session), "源时间线长度不一致"


    def add_value(self, var: str, src: str, value: float):
        """
        变量值按顺序入队。约定：与该变量绑定源的 src_timestamp/session 按追加顺序对齐。
        """
        vb = self.ensure_var(var, src)
        # 可选：简单一致性检查——长度差超过 1 给个告警（不抛错，避免阻塞）
        sb = self.ensure_source(vb.src)
        if len(vb.value) > len(sb.src_timestamp):
            # 变量值比源时间多，通常是写入顺序问题
            # 这里不抛异常，只是你可以改成 raise 或日志
            pass
        vb.value.append(float(value))

    def update_source_timestamp(self, src: str, unix_timestamp: float, src_timestamp: float):
        sb = self.ensure_source(src)
        last_src_timestamp = sb.last_src_timestamp
        if last_src_timestamp is not None and abs(src_timestamp - last_src_timestamp) > self.JUMP_THRESHOLD_MS:
            sb.current_session += 1
        sb.last_src_timestamp = src_timestamp

        last_offset = self.offsets.get((src, sb.current_session))
        current_offset = unix_timestamp - src_timestamp
        if last_offset is not None:
            if current_offset < last_offset:
                self.offsets[(src, sb.current_session)] = current_offset
        else:
            self.offsets[(src, sb.current_session)] = current_offset
        recon_timestamp = src_timestamp + self.offsets[(src, sb.current_session)]
        self.add_timestamp(src, src_timestamp, recon_timestamp, sb.current_session)

    def add_data(self, src: str, unix_timestamp: float, src_timestamp: float, data):
        self.update_source_timestamp(src, unix_timestamp, src_timestamp)
        for k, v in data.items():
            self.add_value(k, src, v)

    def get_series(self, var:str, series_time_ms:float):
        vb = self.vars.get(var)
        if not vb or not vb.src:
            return [],[]
        sb = self.sources.get(vb.src)
        if not sb or not sb.src_timestamp:
            return [],[]
        n = min(len(vb.value), len(sb.src_timestamp), len(sb.session))
        if n == 0:
            return [],[]

        recon_ts = list(sb.recon_timestamp)[:n]
        if series_time_ms is not None and series_time_ms >=0:
            cutoff = recon_ts[-1] - series_time_ms
            idx0 = bisect_left(recon_ts, cutoff)
        else:
            idx0 = 0

        src_ts = list(sb.src_timestamp)[idx0:n]
        sess = list(sb.session)[idx0:n]
        vals = list(vb.value)[idx0:]
        ts = [t + self.offsets.get((vb.src,s))for t,s in zip(src_ts, sess)]

        return ts, vals

    def get_series_fast(self, var:str, series_time_ms:float):
        vb = self.vars.get(var)
        if not vb or not vb.src:
            return [], []
        sb = self.sources.get(vb.src)
        if not sb or not sb.src_timestamp:
            return [], []
        n = min(len(vb.value), len(sb.src_timestamp), len(sb.session))
        if n == 0:
            return [], []

        vals = list(vb.value)[:n]
        ts = list(sb.recon_timestamp)[:n]


        return ts, vals
    def clear(self) -> None:
        """清空所有源、变量与 offset（完全重置）。"""
        self.sources.clear()
        self.vars.clear()
        self.offsets.clear()

    def clear_source(self, src: str, *, clear_offsets: bool = True) -> None:
        """清空某个数据源的时间线与状态；可选同时清掉该源的 offsets。"""
        sb = self.sources.get(src)
        if sb:
            sb.src_timestamp.clear()
            sb.session.clear()
            sb.last_src_timestamp = None
            sb.current_session = 1
        if clear_offsets:
            # 删除该源的所有会话 offset
            to_del = [k for k in self.offsets.keys() if k[0] == src]
            for k in to_del:
                del self.offsets[k]
        # 变量数据若需要一并清理：
        for vb in self.vars.values():
            if vb.src == src:
                vb.value.clear()

    def clear_var(self, var: str) -> None:
        """只清空某个变量的值，保留变量与其绑定关系。"""
        vb = self.vars.get(var)
        if vb:
            vb.value.clear()
