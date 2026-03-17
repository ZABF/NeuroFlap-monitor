from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple


@dataclass
class SourceBucket:
    src: str
    src_timestamp: Deque[float] = field(default_factory=deque)
    recon_timestamp: Deque[float] = field(default_factory=deque)
    session: Deque[int] = field(default_factory=deque)
    last_src_timestamp: Optional[float] = None
    current_session: int = 1


@dataclass
class VarBucket:
    var: str
    src: str
    value: Deque[float] = field(default_factory=deque)


class DataModel:
    def __init__(self, variable_names):
        self.JUMP_THRESHOLD_MS = 200
        self.sources: Dict[str, SourceBucket] = {}
        self.vars: Dict[str, VarBucket] = {}
        self.offsets: Dict[Tuple[str, int], float] = {}
        for var_name in variable_names:
            self.vars.setdefault(var_name, None)
        self.vars = {k: v for k, v in self.vars.items() if v is not None}

    def ensure_source(self, src: str) -> SourceBucket:
        bucket = self.sources.get(src)
        if bucket is None:
            bucket = SourceBucket(src=src)
            self.sources[src] = bucket
        return bucket

    def ensure_var(self, var: str, src: str) -> VarBucket:
        bucket = self.vars.get(var)
        if bucket is None:
            bucket = VarBucket(var=var, src=src)
            self.vars[var] = bucket
        elif bucket.src != src:
            raise ValueError(f"variable '{var}' is already bound to source '{bucket.src}', cannot bind to '{src}'")
        return bucket

    def add_timestamp(self, src: str, src_timestamp: float, recon_timestamp: float, session: int) -> None:
        bucket = self.ensure_source(src)
        bucket.src_timestamp.append(float(src_timestamp))
        bucket.recon_timestamp.append(float(recon_timestamp))
        bucket.session.append(int(session))
        assert len(bucket.src_timestamp) == len(bucket.recon_timestamp) == len(bucket.session)

    def add_value(self, var: str, src: str, value: float) -> None:
        var_bucket = self.ensure_var(var, src)
        self.ensure_source(var_bucket.src)
        var_bucket.value.append(float(value))

    def update_source_timestamp(self, src: str, unix_timestamp: float, src_timestamp: float) -> None:
        source_bucket = self.ensure_source(src)
        if (
            source_bucket.last_src_timestamp is not None
            and abs(src_timestamp - source_bucket.last_src_timestamp) > self.JUMP_THRESHOLD_MS
        ):
            source_bucket.current_session += 1
        source_bucket.last_src_timestamp = src_timestamp

        offset_key = (src, source_bucket.current_session)
        current_offset = unix_timestamp - src_timestamp
        last_offset = self.offsets.get(offset_key)
        if last_offset is None or current_offset < last_offset:
            self.offsets[offset_key] = current_offset

        recon_timestamp = src_timestamp + self.offsets[offset_key]
        self.add_timestamp(src, src_timestamp, recon_timestamp, source_bucket.current_session)

    def add_data(self, src: str, unix_timestamp: float, src_timestamp: float, data) -> None:
        self.update_source_timestamp(src, unix_timestamp, src_timestamp)
        for key, value in data.items():
            self.add_value(key, src, value)

    def get_series(self, var: str, series_time_ms: float):
        var_bucket = self.vars.get(var)
        if not var_bucket or not var_bucket.src:
            return [], []

        source_bucket = self.sources.get(var_bucket.src)
        if not source_bucket or not source_bucket.src_timestamp:
            return [], []

        count = min(len(var_bucket.value), len(source_bucket.src_timestamp), len(source_bucket.session))
        if count == 0:
            return [], []

        recon_ts = list(source_bucket.recon_timestamp)[:count]
        if series_time_ms is not None and series_time_ms >= 0:
            cutoff = recon_ts[-1] - series_time_ms
            start_idx = bisect_left(recon_ts, cutoff)
        else:
            start_idx = 0

        src_ts = list(source_bucket.src_timestamp)[start_idx:count]
        sessions = list(source_bucket.session)[start_idx:count]
        values = list(var_bucket.value)[start_idx:count]
        timestamps = [
            src_t + self.offsets.get((var_bucket.src, session_id), 0.0)
            for src_t, session_id in zip(src_ts, sessions)
        ]
        return timestamps, values

    def get_series_fast(self, var: str, series_time_ms: float):
        del series_time_ms
        var_bucket = self.vars.get(var)
        if not var_bucket or not var_bucket.src:
            return [], []

        source_bucket = self.sources.get(var_bucket.src)
        if not source_bucket or not source_bucket.src_timestamp:
            return [], []

        count = min(len(var_bucket.value), len(source_bucket.src_timestamp), len(source_bucket.session))
        if count == 0:
            return [], []

        values = list(var_bucket.value)[:count]
        timestamps = list(source_bucket.recon_timestamp)[:count]
        return timestamps, values

    def clear(self) -> None:
        self.sources.clear()
        self.vars.clear()
        self.offsets.clear()

    def clear_source(self, src: str, *, clear_offsets: bool = True) -> None:
        source_bucket = self.sources.get(src)
        if source_bucket is not None:
            source_bucket.src_timestamp.clear()
            source_bucket.recon_timestamp.clear()
            source_bucket.session.clear()
            source_bucket.last_src_timestamp = None
            source_bucket.current_session = 1

        if clear_offsets:
            to_delete = [key for key in self.offsets if key[0] == src]
            for key in to_delete:
                del self.offsets[key]

        for var_bucket in self.vars.values():
            if var_bucket.src == src:
                var_bucket.value.clear()

    def clear_sources_with_prefix(self, prefix: str, *, clear_offsets: bool = True) -> None:
        for src in list(self.sources.keys()):
            if src.startswith(prefix):
                self.clear_source(src, clear_offsets=clear_offsets)

    def clear_var(self, var: str) -> None:
        var_bucket = self.vars.get(var)
        if var_bucket is not None:
            var_bucket.value.clear()
