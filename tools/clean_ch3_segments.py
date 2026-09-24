#!/usr/bin/env python3
"""Split NFMonitorCSV captures by CH3 and add causal filtered trajectories."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
from scipy import signal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from monitor_csv import read_monitor_csv, write_monitor_csv  # noqa: E402


DEFAULT_CH3_SIGNAL = "RcTask.output.ch3_out"
FILTER_TARGETS = (
    (
        "UwbTask.output.pos_x",
        "Processed.UWB.pos_x_lowpass_zero",
        "UWB X low-pass zero",
    ),
    (
        "UwbTask.output.pos_y",
        "Processed.UWB.pos_y_lowpass_zero",
        "UWB Y low-pass zero",
    ),
    (
        "SensorTask.output.height",
        "Processed.Baro.height_lowpass_zero",
        "Barometer height low-pass zero",
    ),
)


@dataclass(frozen=True)
class Segment:
    source_path: Path
    source_index: int
    start_us: int
    end_us: int
    source_span_us: int

    @property
    def duration_seconds(self) -> float:
        return (self.end_us - self.start_us) / 1_000_000.0

    @property
    def key(self) -> tuple[str, int]:
        return (str(self.source_path), self.source_index)


@dataclass(frozen=True)
class FilterConfig:
    sample_rate_hz: float = 50.0
    cutoff_hz: float = 3.0
    order: int = 2
    mode: str = "causal"
    max_gap_ms: float = 250.0

    def validate(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample rate must be positive")
        if not 0 < self.cutoff_hz < self.sample_rate_hz / 2:
            raise ValueError("cutoff must be between zero and the Nyquist frequency")
        if self.order < 1:
            raise ValueError("filter order must be positive")
        if self.mode not in ("causal", "zero-phase"):
            raise ValueError("filter mode must be causal or zero-phase")
        if self.max_gap_ms <= 0:
            raise ValueError("maximum gap must be positive")


def _series_points_us(item: dict) -> list[tuple[int, float]]:
    points = []
    for timestamp_ms, value in zip(item.get("timestamps", ()), item.get("values", ())):
        try:
            timestamp_us = int(round(float(timestamp_ms) * 1000.0))
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            points.append((timestamp_us, number))
    return points


def _normalized_points_us(item: dict) -> list[tuple[int, float]]:
    """Return sorted finite samples with the last value for each timestamp."""
    by_timestamp = {}
    for timestamp_us, value in _series_points_us(item):
        by_timestamp[timestamp_us] = value
    return sorted(by_timestamp.items())


def find_high_segments(
    points: Iterable[tuple[int, float]],
    threshold: float,
    minimum_seconds: float,
    maximum_gap_ms: float = 250.0,
) -> list[tuple[int, int]]:
    samples = list(points)
    if not samples:
        return []
    positive_deltas = [
        current[0] - previous[0]
        for previous, current in zip(samples, samples[1:])
        if current[0] > previous[0]
    ]
    terminal_period_us = int(np.median(positive_deltas)) if positive_deltas else 0
    minimum_us = int(round(minimum_seconds * 1_000_000.0))
    maximum_gap_us = int(round(maximum_gap_ms * 1000.0))
    intervals = []
    start_us = None
    previous_us = None
    for timestamp_us, value in samples:
        if (
            previous_us is not None
            and timestamp_us - previous_us > maximum_gap_us
            and start_us is not None
        ):
            end_us = previous_us + terminal_period_us
            if end_us - start_us >= minimum_us:
                intervals.append((start_us, end_us))
            start_us = None
        if value > threshold and start_us is None:
            start_us = timestamp_us
        elif value <= threshold and start_us is not None:
            if timestamp_us - start_us >= minimum_us:
                intervals.append((start_us, timestamp_us))
            start_us = None
        previous_us = timestamp_us
    if start_us is not None:
        end_us = samples[-1][0] + terminal_period_us
        if end_us - start_us >= minimum_us:
            intervals.append((start_us, end_us))
    return intervals


def discover_segments(
    input_dir: Path,
    pattern: str,
    ch3_signal: str,
    threshold: float,
    minimum_seconds: float,
    maximum_gap_ms: float = 250.0,
) -> list[Segment]:
    segments = []
    for source_path in sorted(input_dir.glob(pattern)):
        if not source_path.is_file():
            continue
        document = read_monitor_csv(source_path)
        ch3 = document.series.get(ch3_signal)
        if ch3 is None:
            raise ValueError(f"{source_path.name}: missing CH3 signal {ch3_signal}")
        points = _normalized_points_us(ch3)
        if not points:
            raise ValueError(f"{source_path.name}: CH3 signal has no finite samples")
        intervals = find_high_segments(
            points, threshold, minimum_seconds, maximum_gap_ms
        )
        source_span_us = points[-1][0] - points[0][0]
        for source_index, (start_us, end_us) in enumerate(intervals, 1):
            segments.append(
                Segment(source_path, source_index, start_us, end_us, source_span_us)
            )
    return segments


def _same_recording(left: Segment, right: Segment, tolerance_us: int) -> bool:
    return (
        abs(left.start_us - right.start_us) <= tolerance_us
        and abs(left.end_us - right.end_us) <= tolerance_us
    )


def deduplicate_segments(
    segments: Iterable[Segment], tolerance_ms: float = 100.0
) -> tuple[list[Segment], dict[tuple[str, int], Segment]]:
    tolerance_us = int(round(tolerance_ms * 1000.0))
    groups: list[list[Segment]] = []
    for candidate in sorted(segments, key=lambda item: (item.start_us, item.end_us)):
        group = next(
            (
                existing
                for existing in groups
                if any(_same_recording(candidate, member, tolerance_us) for member in existing)
            ),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    kept = []
    duplicates = {}
    for group in groups:
        winner = max(
            group,
            key=lambda item: (item.source_span_us, item.source_path.name, item.source_index),
        )
        kept.append(winner)
        for candidate in group:
            if candidate != winner:
                duplicates[candidate.key] = winner
    kept.sort(key=lambda item: (item.source_path.name, item.source_index))
    return kept, duplicates


def _split_at_gaps(
    points: list[tuple[int, float]], max_gap_us: int
) -> list[list[tuple[int, float]]]:
    if not points:
        return []
    blocks = [[points[0]]]
    for point in points[1:]:
        if point[0] - blocks[-1][-1][0] > max_gap_us:
            blocks.append([point])
        else:
            blocks[-1].append(point)
    return blocks


def _filter_regular_block(
    points: list[tuple[int, float]], config: FilterConfig, sos: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    step_us = int(round(1_000_000.0 / config.sample_rate_hz))
    timestamps = np.asarray([item[0] for item in points], dtype=np.int64)
    values = np.asarray([item[1] for item in points], dtype=np.float64)
    grid = np.arange(timestamps[0], timestamps[-1] + 1, step_us, dtype=np.int64)
    source_indices = np.searchsorted(timestamps, grid, side="right") - 1
    held_values = values[np.maximum(source_indices, 0)]

    if config.mode == "causal":
        initial_state = signal.sosfilt_zi(sos) * held_values[0]
        filtered, _state = signal.sosfilt(sos, held_values, zi=initial_state)
    elif len(held_values) >= 3:
        default_pad = 3 * (2 * len(sos) + 1)
        filtered = signal.sosfiltfilt(
            sos, held_values, padlen=min(default_pad, len(held_values) - 1)
        )
    else:
        filtered = held_values.copy()
    return grid, filtered


def filtered_zeroed_series(
    item: dict, start_us: int, end_us: int, config: FilterConfig
) -> tuple[list[float], list[float], int]:
    points = [
        point
        for point in _normalized_points_us(item)
        if start_us <= point[0] < end_us
    ]
    if not points:
        return [], [], 0

    max_gap_us = int(round(config.max_gap_ms * 1000.0))
    blocks = _split_at_gaps(points, max_gap_us)
    sos = signal.butter(
        config.order,
        config.cutoff_hz,
        btype="lowpass",
        fs=config.sample_rate_hz,
        output="sos",
    )
    timestamps_us = []
    values = []
    for block in blocks:
        grid, filtered = _filter_regular_block(block, config, sos)
        timestamps_us.extend(int(value) for value in grid)
        values.extend(float(value) for value in filtered)

    zero = values[0]
    values = [value - zero for value in values]
    return [value / 1000.0 for value in timestamps_us], values, len(blocks) - 1


def _cropped_series(document, segment: Segment, config: FilterConfig):
    result = []
    for name, item in document.series.items():
        timestamps = []
        values = []
        for timestamp_ms, value in zip(item["timestamps"], item["values"]):
            timestamp_us = int(round(float(timestamp_ms) * 1000.0))
            if segment.start_us <= timestamp_us < segment.end_us:
                timestamps.append(float(timestamp_ms))
                values.append(value)
        if timestamps:
            result.append({"name": name, **item, "timestamps": timestamps, "values": values})

    reset_counts = {}
    for source_name, output_name, display_name in FILTER_TARGETS:
        source = document.series.get(source_name)
        if source is None:
            raise ValueError(f"{segment.source_path.name}: missing filter source {source_name}")
        timestamps, values, reset_count = filtered_zeroed_series(
            source, segment.start_us, segment.end_us, config
        )
        if not timestamps:
            raise ValueError(
                f"{segment.source_path.name}: no {source_name} samples inside segment"
            )
        reset_counts[output_name] = reset_count
        result.append(
            {
                "name": output_name,
                "timestamps": timestamps,
                "values": values,
                "category": "processed",
                "section": "Processed/Trajectory",
                "unit": "m",
                "descriptor_kind": "processed_signal",
                "owner": "clean_ch3_segments",
                "display_name": display_name,
                "scalar_type": 6,
            }
        )
    return result, reset_counts


def _write_plain_csv(path: Path, series: list[dict], segment_start_us: int) -> None:
    prepared = []
    for item in series:
        samples = []
        for timestamp_ms, value in zip(item["timestamps"], item["values"]):
            timestamp_us = int(round(float(timestamp_ms) * 1000.0))
            samples.append((timestamp_us - segment_start_us, float(value)))
        if samples:
            prepared.append((item["name"], samples))

    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        headers = []
        for name, _samples in prepared:
            headers.extend((f"{name}_time_us", f"{name}_value"))
        writer.writerow(headers)
        row_count = max((len(samples) for _name, samples in prepared), default=0)
        for index in range(row_count):
            row = []
            for _name, samples in prepared:
                if index >= len(samples):
                    row.extend(("", ""))
                else:
                    timestamp_us, value = samples[index]
                    row.extend((str(timestamp_us), format(value, ".17g")))
            writer.writerow(row)


def _filter_coefficients(config: FilterConfig) -> tuple[np.ndarray, np.ndarray]:
    return signal.butter(
        config.order,
        config.cutoff_hz,
        btype="lowpass",
        fs=config.sample_rate_hz,
        output="ba",
    )


def _coefficient_text(values: np.ndarray) -> str:
    return ";".join(format(float(value), ".17g") for value in values)


def _write_filter_reference(path: Path, config: FilterConfig) -> None:
    sample_count = int(round(config.sample_rate_hz * 2.0))
    inputs = np.zeros(sample_count, dtype=np.float64)
    inputs[sample_count // 4 :] = 1.0
    sos = signal.butter(
        config.order,
        config.cutoff_hz,
        btype="lowpass",
        fs=config.sample_rate_hz,
        output="sos",
    )
    initial_state = signal.sosfilt_zi(sos) * inputs[0]
    outputs, _state = signal.sosfilt(sos, inputs, zi=initial_state)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(("sample", "time_s", "input", "causal_output"))
        for index, (input_value, output_value) in enumerate(zip(inputs, outputs)):
            writer.writerow(
                (
                    index,
                    format(index / config.sample_rate_hz, ".9g"),
                    format(float(input_value), ".17g"),
                    format(float(output_value), ".17g"),
                )
            )


def process_directory(
    input_dir: Path,
    output_dir: Path,
    pattern: str = "*.csv",
    ch3_signal: str = DEFAULT_CH3_SIGNAL,
    threshold: float = 2.5,
    minimum_seconds: float = 9.0,
    ch3_max_gap_ms: float = 250.0,
    config: FilterConfig = FilterConfig(),
    deduplicate: bool = True,
    duplicate_tolerance_ms: float = 100.0,
) -> dict:
    config.validate()
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    if input_dir == output_dir:
        raise ValueError("output directory must differ from input directory")

    discovered = discover_segments(
        input_dir,
        pattern,
        ch3_signal,
        threshold,
        minimum_seconds,
        ch3_max_gap_ms,
    )
    if deduplicate:
        kept, duplicates = deduplicate_segments(discovered, duplicate_tolerance_ms)
    else:
        kept, duplicates = list(discovered), {}

    monitor_dir = output_dir / "nfmonitor"
    plain_dir = output_dir / "plain"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    plain_dir.mkdir(parents=True, exist_ok=True)

    coefficients_b, coefficients_a = _filter_coefficients(config)
    rows = []
    processed_keys = set()
    for segment in kept:
        document = read_monitor_csv(segment.source_path)
        series, reset_counts = _cropped_series(document, segment, config)
        filename = f"{segment.source_path.stem}_segment_{segment.source_index:03d}.csv"
        monitor_path = monitor_dir / filename
        plain_path = plain_dir / filename
        metadata = {
            **document.metadata,
            "processing_tool": "clean_ch3_segments",
            "processing_version": "1",
            "source_file": segment.source_path.name,
            "source_segment": segment.source_index,
            "segment_start_unix_us": segment.start_us,
            "segment_end_unix_us": segment.end_us,
            "segment_duration_s": format(segment.duration_seconds, ".9g"),
            "segment_signal": ch3_signal,
            "segment_high_threshold": format(threshold, ".9g"),
            "segment_minimum_s": format(minimum_seconds, ".9g"),
            "segment_ch3_max_gap_ms": format(ch3_max_gap_ms, ".9g"),
            "filter_mode": config.mode,
            "filter_type": "Butterworth IIR",
            "filter_sample_rate_hz": format(config.sample_rate_hz, ".9g"),
            "filter_cutoff_hz": format(config.cutoff_hz, ".9g"),
            "filter_order": config.order,
            "filter_max_gap_ms": format(config.max_gap_ms, ".9g"),
            "filter_b": _coefficient_text(coefficients_b),
            "filter_a": _coefficient_text(coefficients_a),
            "processed_zero_reference": "first filtered sample in segment",
        }
        write_monitor_csv(monitor_path, series, metadata)
        _write_plain_csv(plain_path, series, segment.start_us)
        warning = ";".join(
            f"{name}:gap_resets={count}"
            for name, count in reset_counts.items()
            if count
        )
        rows.append(
            {
                "source_file": segment.source_path.name,
                "source_segment": segment.source_index,
                "start_unix_us": segment.start_us,
                "end_unix_us": segment.end_us,
                "duration_s": format(segment.duration_seconds, ".6f"),
                "status": "processed",
                "duplicate_of": "",
                "nfmonitor_file": str(monitor_path.relative_to(output_dir)),
                "plain_file": str(plain_path.relative_to(output_dir)),
                "warning": warning,
            }
        )
        processed_keys.add(segment.key)

    for segment in discovered:
        if segment.key in processed_keys:
            continue
        winner = duplicates.get(segment.key)
        rows.append(
            {
                "source_file": segment.source_path.name,
                "source_segment": segment.source_index,
                "start_unix_us": segment.start_us,
                "end_unix_us": segment.end_us,
                "duration_s": format(segment.duration_seconds, ".6f"),
                "status": "duplicate" if winner else "skipped",
                "duplicate_of": (
                    f"{winner.source_path.name}#segment-{winner.source_index:03d}"
                    if winner
                    else ""
                ),
                "nfmonitor_file": "",
                "plain_file": "",
                "warning": "",
            }
        )

    manifest_fields = (
        "source_file",
        "source_segment",
        "start_unix_us",
        "end_unix_us",
        "duration_s",
        "status",
        "duplicate_of",
        "nfmonitor_file",
        "plain_file",
        "warning",
    )
    rows.sort(key=lambda row: (row["source_file"], int(row["source_segment"])))
    with (output_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=manifest_fields)
        writer.writeheader()
        writer.writerows(rows)
    _write_filter_reference(output_dir / "filter_reference.csv", config)
    return {
        "discovered": len(discovered),
        "processed": len(kept),
        "duplicates": len(duplicates),
        "output_dir": output_dir,
    }


def print_analysis(segments: list[Segment], deduplicate: bool, tolerance_ms: float) -> None:
    if deduplicate:
        kept, duplicates = deduplicate_segments(segments, tolerance_ms)
    else:
        kept, duplicates = segments, {}
    kept_keys = {segment.key for segment in kept}
    for segment in sorted(segments, key=lambda item: (item.source_path.name, item.source_index)):
        status = "keep" if segment.key in kept_keys else "duplicate"
        duplicate = duplicates.get(segment.key)
        suffix = f" -> {duplicate.source_path.name}" if duplicate else ""
        print(
            f"{segment.source_path.name} segment={segment.source_index:03d} "
            f"duration={segment.duration_seconds:.3f}s status={status}{suffix}"
        )
    print(
        f"segments discovered={len(segments)} "
        f"kept={len(kept)} duplicates={len(duplicates)}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--pattern", default="*.csv")
    parser.add_argument("--ch3-signal", default=DEFAULT_CH3_SIGNAL)
    parser.add_argument("--high-threshold", type=float, default=2.5)
    parser.add_argument("--min-high-seconds", type=float, default=9.0)
    parser.add_argument(
        "--ch3-max-gap-ms",
        type=float,
        default=250.0,
        help="end a high segment when CH3 has no fresh sample for this long",
    )
    parser.add_argument("--sample-rate-hz", type=float, default=50.0)
    parser.add_argument("--cutoff-hz", type=float, default=3.0)
    parser.add_argument("--filter-order", type=int, default=2)
    parser.add_argument(
        "--filter-mode", choices=("causal", "zero-phase"), default="causal"
    )
    parser.add_argument("--max-gap-ms", type=float, default=250.0)
    parser.add_argument("--duplicate-tolerance-ms", type=float, default=100.0)
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="print qualifying segment durations without writing output files",
    )
    duplicates = parser.add_mutually_exclusive_group()
    duplicates.add_argument("--deduplicate", dest="deduplicate", action="store_true")
    duplicates.add_argument(
        "--keep-duplicates", dest="deduplicate", action="store_false"
    )
    parser.set_defaults(deduplicate=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    input_dir = args.input_dir.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else input_dir / "processed_ch3_segments"
    )
    config = FilterConfig(
        sample_rate_hz=args.sample_rate_hz,
        cutoff_hz=args.cutoff_hz,
        order=args.filter_order,
        mode=args.filter_mode,
        max_gap_ms=args.max_gap_ms,
    )
    if args.analyze_only:
        segments = discover_segments(
            input_dir,
            args.pattern,
            args.ch3_signal,
            args.high_threshold,
            args.min_high_seconds,
            args.ch3_max_gap_ms,
        )
        print_analysis(segments, args.deduplicate, args.duplicate_tolerance_ms)
        return 0
    result = process_directory(
        input_dir=input_dir,
        output_dir=output_dir,
        pattern=args.pattern,
        ch3_signal=args.ch3_signal,
        threshold=args.high_threshold,
        minimum_seconds=args.min_high_seconds,
        ch3_max_gap_ms=args.ch3_max_gap_ms,
        config=config,
        deduplicate=args.deduplicate,
        duplicate_tolerance_ms=args.duplicate_tolerance_ms,
    )
    print(
        "segments "
        f"discovered={result['discovered']} "
        f"processed={result['processed']} "
        f"duplicates={result['duplicates']}"
    )
    print(f"output={result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
