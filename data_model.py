from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from network_clock import ClockTransform


def _double_array():
    return array("d")


def _session_array():
    return array("I")


@dataclass
class SourceBucket:
    src: str
    offset_src: Optional[str] = None
    src_timestamp: array = field(default_factory=_double_array)
    recon_timestamp: array = field(default_factory=_double_array)
    session: array = field(default_factory=_session_array)
    last_src_timestamp: Optional[float] = None
    current_session: int = 1
    reconstruction_dirty: bool = False
    timestamp_revision: int = 0
    reconstruction_revision: int = 0


@dataclass
class VarBucket:
    var: str
    src: str
    value: array = field(default_factory=_double_array)
    value_revision: int = 0


class DataModel:
    def __init__(self, variable_names):
        self.JUMP_THRESHOLD_MS = 200
        self.sources: Dict[str, SourceBucket] = {}
        self.vars: Dict[str, VarBucket] = {}
        self.offsets: Dict[Tuple[str, int], float] = {}
        self.clock_transforms: Dict[str, ClockTransform] = {}
        self.clock_transform_history: Dict[
            Tuple[str, int], ClockTransform
        ] = {}
        self.revision = 0
        self.epoch = 0
        for var_name in variable_names:
            self.vars.setdefault(var_name, None)
        self.vars = {k: v for k, v in self.vars.items() if v is not None}

    def _next_revision(self) -> int:
        self.revision += 1
        return self.revision

    def _mark_reconstruction_changed(self, source_bucket: SourceBucket) -> None:
        source_bucket.reconstruction_dirty = True
        source_bucket.reconstruction_revision = self._next_revision()

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
        bucket.timestamp_revision = self._next_revision()
        assert len(bucket.src_timestamp) == len(bucket.recon_timestamp) == len(bucket.session)

    def add_value(self, var: str, src: str, value: float) -> None:
        var_bucket = self.ensure_var(var, src)
        self.ensure_source(var_bucket.src)
        var_bucket.value.append(float(value))
        var_bucket.value_revision = self._next_revision()

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
        if source_bucket.offset_src != clock_src:
            source_bucket.offset_src = clock_src
            self._mark_reconstruction_changed(source_bucket)

        if (
            clock_bucket.last_src_timestamp is not None
            and clock_timestamp
            < clock_bucket.last_src_timestamp - self.JUMP_THRESHOLD_MS
        ):
            clock_bucket.current_session += 1
        clock_bucket.last_src_timestamp = clock_timestamp
        if clock_bucket is not source_bucket:
            source_bucket.last_src_timestamp = src_timestamp

        offset_key = (clock_src, clock_bucket.current_session)
        transform = self.clock_transforms.get(clock_src)
        if (
            transform is not None
            and transform.epoch == clock_bucket.current_session
            and (transform.usable or transform.locked)
        ):
            recon_timestamp = transform.map_ms(src_timestamp)
        else:
            current_offset = unix_timestamp - clock_timestamp
            last_offset = self.offsets.get(offset_key)
            if last_offset is None or current_offset < last_offset:
                self.offsets[offset_key] = current_offset
                for bucket in self.sources.values():
                    if (bucket.offset_src or bucket.src) == clock_src:
                        self._mark_reconstruction_changed(bucket)
            recon_timestamp = src_timestamp + self.offsets[offset_key]
        self.add_timestamp(src, src_timestamp, recon_timestamp, clock_bucket.current_session)

    def set_clock_transform(
        self, src: str, transform: Optional[ClockTransform]
    ) -> None:
        previous = self.clock_transforms.get(src)
        if transform is None:
            self.clock_transforms.pop(src, None)
        else:
            self.clock_transforms[src] = transform
            self.clock_transform_history[(src, transform.epoch)] = transform
        if previous == transform:
            return
        for bucket in self.sources.values():
            if (bucket.offset_src or bucket.src) == src:
                self._mark_reconstruction_changed(bucket)

    def begin_clock_epoch(self, src: str, epoch: int) -> None:
        epoch = max(1, int(epoch))
        clock_bucket = self.ensure_source(src)
        previous_epoch = clock_bucket.current_session
        clock_bucket.current_session = epoch
        clock_bucket.last_src_timestamp = None
        self.clock_transforms.pop(src, None)
        if previous_epoch == epoch:
            return
        for bucket in self.sources.values():
            if (bucket.offset_src or bucket.src) == src:
                self._mark_reconstruction_changed(bucket)

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
        source_bucket.reconstruction_dirty = False
        for i in range(count):
            ts = float(timestamps[i])
            source_bucket.src_timestamp.append(ts)
            source_bucket.recon_timestamp.append(ts)
            source_bucket.session.append(1)
            var_bucket.value.append(float(values[i]))
        revision = self._next_revision()
        source_bucket.timestamp_revision = revision
        source_bucket.reconstruction_revision = revision
        var_bucket.value_revision = revision

    def _series_storage(self, var: str):
        var_bucket = self.vars.get(var)
        if not var_bucket or not var_bucket.src:
            return None

        source_bucket = self.sources.get(var_bucket.src)
        if not source_bucket or not source_bucket.src_timestamp:
            return None

        self._ensure_reconstructed(source_bucket)
        count = min(
            len(var_bucket.value),
            len(source_bucket.recon_timestamp),
            len(source_bucket.session),
        )
        if count == 0:
            return None
        return var_bucket, source_bucket, count

    def _ensure_reconstructed(self, source_bucket: SourceBucket) -> None:
        count = min(len(source_bucket.src_timestamp), len(source_bucket.session))
        if (
            not source_bucket.reconstruction_dirty
            and len(source_bucket.recon_timestamp) == count
        ):
            return

        offset_src = source_bucket.offset_src or source_bucket.src
        reconstructed = array("d")
        for index in range(count):
            session = int(source_bucket.session[index])
            transform = self.clock_transform_history.get((offset_src, session))
            if transform is not None and (transform.usable or transform.locked):
                reconstructed.append(
                    transform.map_ms(source_bucket.src_timestamp[index])
                )
            else:
                reconstructed.append(
                    source_bucket.src_timestamp[index]
                    + self.offsets.get((offset_src, session), 0.0)
                )
        source_bucket.recon_timestamp = reconstructed
        source_bucket.reconstruction_dirty = False

    @staticmethod
    def _series_slice(var_bucket, source_bucket, start_idx, end_idx):
        return (
            source_bucket.recon_timestamp[start_idx:end_idx].tolist(),
            var_bucket.value[start_idx:end_idx].tolist(),
        )

    def get_series(self, var: str, series_time_ms: float = None):
        storage = self._series_storage(var)
        if storage is None:
            return [], []
        var_bucket, source_bucket, count = storage

        if series_time_ms is not None and series_time_ms >= 0:
            cutoff = source_bucket.recon_timestamp[count - 1] - series_time_ms
            start_idx = bisect_left(source_bucket.recon_timestamp, cutoff, 0, count)
        else:
            start_idx = 0
        return self._series_slice(var_bucket, source_bucket, start_idx, count)

    def get_series_between(
        self,
        var: str,
        start_ms=None,
        end_ms=None,
        *,
        before_samples: int = 0,
        after_samples: int = 0,
    ):
        """Return a time slice without materializing the complete history."""
        storage = self._series_storage(var)
        if storage is None:
            return [], []
        var_bucket, source_bucket, count = storage

        start_idx = 0
        end_idx = count
        if start_ms is not None:
            start_idx = bisect_left(
                source_bucket.recon_timestamp,
                float(start_ms),
                0,
                count,
            )
        if end_ms is not None:
            end_idx = bisect_right(
                source_bucket.recon_timestamp,
                float(end_ms),
                start_idx,
                count,
            )
        start_idx = max(0, start_idx - max(0, int(before_samples)))
        end_idx = min(count, end_idx + max(0, int(after_samples)))
        return self._series_slice(var_bucket, source_bucket, start_idx, end_idx)

    def get_series_revision(self, var: str):
        """Return a stable cache key for one variable's value and time axes."""
        var_bucket = self.vars.get(var)
        if var_bucket is None:
            return self.epoch, 0, 0, 0
        source_bucket = self.sources.get(var_bucket.src)
        if source_bucket is None:
            return self.epoch, var_bucket.value_revision, 0, 0
        return (
            self.epoch,
            var_bucket.value_revision,
            source_bucket.timestamp_revision,
            source_bucket.reconstruction_revision,
        )

    def get_nearest_sample(self, var: str, timestamp_ms: float):
        storage = self._series_storage(var)
        if storage is None:
            return None
        var_bucket, source_bucket, count = storage
        idx = bisect_left(source_bucket.recon_timestamp, float(timestamp_ms), 0, count)
        candidates = []
        if idx < count:
            candidates.append(idx)
        if idx > 0:
            candidates.append(idx - 1)
        if not candidates:
            return None
        best_idx = min(
            candidates,
            key=lambda item: abs(source_bucket.recon_timestamp[item] - float(timestamp_ms)),
        )
        return (
            float(source_bucket.recon_timestamp[best_idx]),
            float(var_bucket.value[best_idx]),
        )

    def get_series_tail(self, var: str, max_samples: int):
        """Return at most the newest max_samples without copying older history."""
        storage = self._series_storage(var)
        if storage is None or max_samples <= 0:
            return [], []
        var_bucket, source_bucket, count = storage
        start_idx = max(0, count - int(max_samples))
        return self._series_slice(var_bucket, source_bucket, start_idx, count)

    def get_series_fast(self, var: str, series_time_ms: float):
        del series_time_ms
        storage = self._series_storage(var)
        if storage is None:
            return [], []
        var_bucket, source_bucket, count = storage
        return self._series_slice(var_bucket, source_bucket, 0, count)

    def clear(self) -> None:
        self.sources.clear()
        self.vars.clear()
        self.offsets.clear()
        self.clock_transforms.clear()
        self.clock_transform_history.clear()
        self.epoch += 1
        self._next_revision()

    def clear_source(self, src: str, *, clear_offsets: bool = True) -> None:
        source_bucket = self.sources.get(src)
        if source_bucket is not None:
            source_bucket.src_timestamp.clear()
            source_bucket.recon_timestamp.clear()
            source_bucket.session.clear()
            source_bucket.offset_src = None
            source_bucket.last_src_timestamp = None
            source_bucket.current_session = 1
            source_bucket.reconstruction_dirty = False
            revision = self._next_revision()
            source_bucket.timestamp_revision = revision
            source_bucket.reconstruction_revision = revision

        if clear_offsets:
            to_delete = [key for key in self.offsets if key[0] == src]
            for key in to_delete:
                del self.offsets[key]
            transform_keys = [
                key for key in self.clock_transform_history if key[0] == src
            ]
            for key in transform_keys:
                del self.clock_transform_history[key]
            self.clock_transforms.pop(src, None)

        for var_bucket in self.vars.values():
            if var_bucket.src == src:
                var_bucket.value.clear()
                var_bucket.value_revision = self._next_revision()

    def clear_sources_with_prefix(self, prefix: str, *, clear_offsets: bool = True) -> None:
        for src in list(self.sources.keys()):
            if src.startswith(prefix):
                self.clear_source(src, clear_offsets=clear_offsets)

    def clear_var(self, var: str) -> None:
        var_bucket = self.vars.get(var)
        if var_bucket is not None:
            var_bucket.value.clear()
            var_bucket.value_revision = self._next_revision()
