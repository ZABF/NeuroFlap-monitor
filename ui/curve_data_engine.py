"""Bounded display helpers for full-history monitor data."""

import math


def min_max_downsample(timestamps, values, max_points):
    """Preserve endpoints and bucket extrema while bounding rendered points."""
    count = min(len(timestamps), len(values))
    max_points = max(4, int(max_points))
    if count <= max_points:
        return list(timestamps)[:count], list(values)[:count]

    interior_count = count - 2
    bucket_count = max(1, (max_points - 2) // 2)
    bucket_size = interior_count / float(bucket_count)
    selected = [0]

    for bucket in range(bucket_count):
        start = 1 + int(math.floor(bucket * bucket_size))
        end = 1 + int(math.floor((bucket + 1) * bucket_size))
        if bucket == bucket_count - 1:
            end = count - 1
        end = max(start + 1, min(end, count - 1))

        valid = []
        for index in range(start, end):
            try:
                value = float(values[index])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                valid.append((index, value))
        if not valid:
            continue

        min_index = min(valid, key=lambda item: item[1])[0]
        max_index = max(valid, key=lambda item: item[1])[0]
        selected.extend(sorted({min_index, max_index}))

    selected.append(count - 1)
    selected = sorted(set(selected))
    return (
        [timestamps[index] for index in selected],
        [values[index] for index in selected],
    )
