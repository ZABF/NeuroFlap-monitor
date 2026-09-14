from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from network_clock import ClockTransform


def _double_array():
    return array("d")


def _session_array():
    return array("I")


@dataclass
class SessionSpan:
    session: int
    start: int
    end: int


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
    session_spans: List[SessionSpan] = field(default_factory=list)


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

    def _mark_alignment_changed(self, source_bucket: SourceBucket) -> None:
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
        index = len(bucket.src_timestamp)
        bucket.src_timestamp.append(float(src_timestamp))
        bucket.recon_timestamp.append(float(recon_timestamp))
        bucket.session.append(int(session))
        if not bucket.session_spans or bucket.session_spans[-1].session != int(session):
            bucket.session_spans.append(SessionSpan(int(session), index, index + 1))
        else:
            bucket.session_spans[-1].end = index + 1
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
            self._mark_alignment_changed(source_bucket)

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
                        self._mark_alignment_changed(bucket)
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
                self._mark_alignment_changed(bucket)

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
                self._mark_alignment_changed(bucket)

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
        source_bucket.session_spans = [SessionSpan(1, 0, count)]
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

        count = min(
            len(var_bucket.value),
            len(source_bucket.recon_timestamp),
            len(source_bucket.session),
        )
        if count == 0:
            return None
        return var_bucket, source_bucket, count

    def _alignment_parameters(self, source_bucket: SourceBucket, session: int):
        offset_src = source_bucket.offset_src or source_bucket.src
        transform = self.clock_transform_history.get((offset_src, int(session)))
        if transform is not None and (transform.usable or transform.locked):
            return (
                transform.source_anchor_us / 1000.0,
                transform.target_anchor_us / 1000.0,
                1.0 + transform.drift_ppb * 1.0e-9,
            )
        return 0.0, self.offsets.get((offset_src, int(session)), 0.0), 1.0

    def _map_timestamp(
        self,
        source_bucket: SourceBucket,
        session: int,
        source_timestamp: float,
    ) -> float:
        source_anchor, target_anchor, scale = self._alignment_parameters(
            source_bucket, session
        )
        return target_anchor + (float(source_timestamp) - source_anchor) * scale

    def _unmap_timestamp(
        self,
        source_bucket: SourceBucket,
        session: int,
        target_timestamp: float,
    ) -> float:
        source_anchor, target_anchor, scale = self._alignment_parameters(
            source_bucket, session
        )
        if abs(scale) < 1.0e-12:
            return source_anchor
        return source_anchor + (float(target_timestamp) - target_anchor) / scale

    @staticmethod
    def _session_spans(source_bucket: SourceBucket, count: int):
        if source_bucket.session_spans:
            return source_bucket.session_spans
        if count <= 0:
            return ()

        spans = []
        start = 0
        session = int(source_bucket.session[0])
        for index in range(1, count):
            current = int(source_bucket.session[index])
            if current == session:
                continue
            spans.append(SessionSpan(session, start, index))
            start = index
            session = current
        spans.append(SessionSpan(session, start, count))
        source_bucket.session_spans = spans
        return spans

    def _aligned_insertion_index(
        self,
        source_bucket: SourceBucket,
        count: int,
        target_timestamp: float,
        *,
        right: bool,
    ) -> int:
        target = float(target_timestamp)
        for span in self._session_spans(source_bucket, count):
            start = min(count, max(0, span.start))
            end = min(count, max(start, span.end))
            if start >= end:
                continue
            first = self._map_timestamp(
                source_bucket,
                span.session,
                source_bucket.src_timestamp[start],
            )
            last = self._map_timestamp(
                source_bucket,
                span.session,
                source_bucket.src_timestamp[end - 1],
            )
            if target < first or (not right and target == first):
                return start
            if target <= last:
                raw_target = self._unmap_timestamp(
                    source_bucket, span.session, target
                )
                search = bisect_right if right else bisect_left
                return search(
                    source_bucket.src_timestamp,
                    raw_target,
                    start,
                    end,
                )
        return count

    def _query_range(
        self,
        source_bucket: SourceBucket,
        count: int,
        start_ms,
        end_ms,
        *,
        before_samples: int = 0,
        after_samples: int = 0,
        align_history: bool,
    ):
        timestamps = (
            source_bucket.src_timestamp
            if align_history
            else source_bucket.recon_timestamp
        )
        if start_ms is None:
            start_idx = 0
        elif align_history:
            start_idx = self._aligned_insertion_index(
                source_bucket, count, start_ms, right=False
            )
        else:
            start_idx = bisect_left(timestamps, float(start_ms), 0, count)

        if end_ms is None:
            end_idx = count
        elif align_history:
            end_idx = self._aligned_insertion_index(
                source_bucket, count, end_ms, right=True
            )
        else:
            end_idx = bisect_right(
                timestamps, float(end_ms), start_idx, count
            )

        start_idx = max(0, start_idx - max(0, int(before_samples)))
        end_idx = min(count, end_idx + max(0, int(after_samples)))
        return start_idx, max(start_idx, end_idx)

    def _series_slice(
        self,
        var_bucket,
        source_bucket,
        start_idx,
        end_idx,
        *,
        align_history,
    ):
        if align_history:
            timestamps = [
                self._map_timestamp(
                    source_bucket,
                    int(source_bucket.session[index]),
                    source_bucket.src_timestamp[index],
                )
                for index in range(start_idx, end_idx)
            ]
        else:
            timestamps = source_bucket.recon_timestamp[start_idx:end_idx].tolist()
        return timestamps, var_bucket.value[start_idx:end_idx].tolist()

    def get_series(
        self,
        var: str,
        series_time_ms: float = None,
        *,
        align_history: bool = True,
    ):
        storage = self._series_storage(var)
        if storage is None:
            return [], []
        var_bucket, source_bucket, count = storage

        if series_time_ms is not None and series_time_ms >= 0:
            latest = (
                self._map_timestamp(
                    source_bucket,
                    int(source_bucket.session[count - 1]),
                    source_bucket.src_timestamp[count - 1],
                )
                if align_history
                else source_bucket.recon_timestamp[count - 1]
            )
            start_idx, _end_idx = self._query_range(
                source_bucket,
                count,
                latest - float(series_time_ms),
                None,
                align_history=align_history,
            )
        else:
            start_idx = 0
        return self._series_slice(
            var_bucket,
            source_bucket,
            start_idx,
            count,
            align_history=align_history,
        )

    def get_series_between(
        self,
        var: str,
        start_ms=None,
        end_ms=None,
        *,
        before_samples: int = 0,
        after_samples: int = 0,
        align_history: bool = True,
    ):
        """Return a time slice without materializing the complete history."""
        storage = self._series_storage(var)
        if storage is None:
            return [], []
        var_bucket, source_bucket, count = storage

        start_idx, end_idx = self._query_range(
            source_bucket,
            count,
            start_ms,
            end_ms,
            before_samples=before_samples,
            after_samples=after_samples,
            align_history=align_history,
        )
        return self._series_slice(
            var_bucket,
            source_bucket,
            start_idx,
            end_idx,
            align_history=align_history,
        )

    def get_series_revision(self, var: str, *, align_history: bool = True):
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
            source_bucket.reconstruction_revision if align_history else 0,
        )

    def get_nearest_sample(
        self, var: str, timestamp_ms: float, *, align_history: bool = True
    ):
        previous, following = self.get_bracketing_samples(
            var, timestamp_ms, align_history=align_history
        )
        candidates = [sample for sample in (previous, following) if sample is not None]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda sample: abs(sample[0] - float(timestamp_ms)),
        )

    def get_bracketing_samples(
        self, var: str, timestamp_ms: float, *, align_history: bool = True
    ):
        """Return the samples immediately before/at and after a timestamp."""
        storage = self._series_storage(var)
        if storage is None:
            return None, None
        var_bucket, source_bucket, count = storage
        target = float(timestamp_ms)
        next_idx = (
            self._aligned_insertion_index(
                source_bucket, count, target, right=True
            )
            if align_history
            else bisect_right(
                source_bucket.recon_timestamp, target, 0, count
            )
        )

        def sample_at(index):
            timestamp = (
                self._map_timestamp(
                    source_bucket,
                    int(source_bucket.session[index]),
                    source_bucket.src_timestamp[index],
                )
                if align_history
                else float(source_bucket.recon_timestamp[index])
            )
            return timestamp, float(var_bucket.value[index])

        previous = None
        following = None
        if next_idx > 0:
            previous = sample_at(next_idx - 1)
        if next_idx < count:
            following = sample_at(next_idx)
        return previous, following

    def get_series_window_ending_at(
        self,
        var: str,
        end_ms: float,
        max_samples: int,
        *,
        align_history: bool = True,
    ):
        """Return at most max_samples whose timestamps do not exceed end_ms."""
        storage = self._series_storage(var)
        if storage is None or max_samples <= 0:
            return [], []
        var_bucket, source_bucket, count = storage
        _start_idx, end_idx = self._query_range(
            source_bucket,
            count,
            None,
            end_ms,
            align_history=align_history,
        )
        start_idx = max(0, end_idx - int(max_samples))
        return self._series_slice(
            var_bucket,
            source_bucket,
            start_idx,
            end_idx,
            align_history=align_history,
        )

    def get_time_bounds(self, variable_names=None, *, align_history: bool = True):
        """Return the earliest and latest timestamps across available variables."""
        names = self.vars.keys() if variable_names is None else variable_names
        earliest = None
        latest = None
        seen_sources = set()
        for name in names:
            var_bucket = self.vars.get(name)
            if var_bucket is None or var_bucket.src in seen_sources:
                continue
            source_bucket = self.sources.get(var_bucket.src)
            if source_bucket is None:
                continue
            count = min(
                len(var_bucket.value),
                len(source_bucket.recon_timestamp),
                len(source_bucket.session),
            )
            if count <= 0:
                continue
            seen_sources.add(var_bucket.src)
            if align_history:
                first = self._map_timestamp(
                    source_bucket,
                    int(source_bucket.session[0]),
                    source_bucket.src_timestamp[0],
                )
                last = self._map_timestamp(
                    source_bucket,
                    int(source_bucket.session[count - 1]),
                    source_bucket.src_timestamp[count - 1],
                )
            else:
                first = float(source_bucket.recon_timestamp[0])
                last = float(source_bucket.recon_timestamp[count - 1])
            earliest = first if earliest is None else min(earliest, first)
            latest = last if latest is None else max(latest, last)
        return earliest, latest

    def get_series_tail(
        self, var: str, max_samples: int, *, align_history: bool = True
    ):
        """Return at most the newest max_samples without copying older history."""
        storage = self._series_storage(var)
        if storage is None or max_samples <= 0:
            return [], []
        var_bucket, source_bucket, count = storage
        start_idx = max(0, count - int(max_samples))
        return self._series_slice(
            var_bucket,
            source_bucket,
            start_idx,
            count,
            align_history=align_history,
        )

    def get_series_fast(
        self,
        var: str,
        series_time_ms: float,
        *,
        align_history: bool = True,
    ):
        del series_time_ms
        return self.get_series(var, align_history=align_history)

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
            source_bucket.session_spans.clear()
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
