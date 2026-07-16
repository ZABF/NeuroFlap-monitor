from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple


@dataclass
class SourceBucket:
    src: str
    offset_src: Optional[str] = None
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

    def update_source_timestamp(
        self,
        src: str,
        unix_timestamp: float,
        src_timestamp: float,
        *,
        offset_src: Optional[str] = None,
        offset_timestamp: Optional[float] = None,
    ) -> None:
        source_bucket = self.ensure_source(src)
        clock_src = offset_src or src
        clock_timestamp = float(src_timestamp if offset_timestamp is None else offset_timestamp)
        clock_bucket = self.ensure_source(clock_src)
        source_bucket.offset_src = clock_src

        if (
            clock_bucket.last_src_timestamp is not None
            and abs(clock_timestamp - clock_bucket.last_src_timestamp) > self.JUMP_THRESHOLD_MS
        ):
            clock_bucket.current_session += 1
        clock_bucket.last_src_timestamp = clock_timestamp
        if clock_bucket is not source_bucket:
            source_bucket.last_src_timestamp = src_timestamp

        offset_key = (clock_src, clock_bucket.current_session)
        current_offset = unix_timestamp - clock_timestamp
        last_offset = self.offsets.get(offset_key)
        if last_offset is None or current_offset < last_offset:
            self.offsets[offset_key] = current_offset

        recon_timestamp = src_timestamp + self.offsets[offset_key]
        self.add_timestamp(src, src_timestamp, recon_timestamp, clock_bucket.current_session)

    def add_data(
        self,
        src: str,
        unix_timestamp: float,
        src_timestamp: float,
        data,
        *,
        offset_src: Optional[str] = None,
        offset_timestamp: Optional[float] = None,
    ) -> None:
        self.update_source_timestamp(
            src,
            unix_timestamp,
            src_timestamp,
            offset_src=offset_src,
            offset_timestamp=offset_timestamp,
        )
        for key, value in data.items():
            self.add_value(key, src, value)

    def add_series(self, var: str, src: str, timestamps, values) -> None:
        count = min(len(timestamps), len(values))
        if count <= 0:
            return

        source_bucket = self.ensure_source(src)
        var_bucket = self.ensure_var(var, src)
        if source_bucket.src_timestamp or var_bucket.value:
            self.clear_source(src, clear_offsets=True)
            source_bucket = self.ensure_source(src)
            var_bucket = self.ensure_var(var, src)

        self.offsets[(src, 1)] = 0.0
        source_bucket.offset_src = src
        source_bucket.current_session = 1
        source_bucket.last_src_timestamp = float(timestamps[count - 1])
        for i in range(count):
            ts = float(timestamps[i])
            source_bucket.src_timestamp.append(ts)
            source_bucket.recon_timestamp.append(ts)
            source_bucket.session.append(1)
            var_bucket.value.append(float(values[i]))

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

        src_ts = list(source_bucket.src_timestamp)[:count]
        sessions = list(source_bucket.session)[:count]
        offset_src = source_bucket.offset_src or var_bucket.src
        timestamps = [
            src_t + self.offsets.get((offset_src, session_id), 0.0)
            for src_t, session_id in zip(src_ts, sessions)
        ]
        if series_time_ms is not None and series_time_ms >= 0:
            cutoff = timestamps[-1] - series_time_ms
            start_idx = bisect_left(timestamps, cutoff)
        else:
            start_idx = 0

        values = list(var_bucket.value)[start_idx:count]
        return timestamps[start_idx:count], values

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
            source_bucket.offset_src = None
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
