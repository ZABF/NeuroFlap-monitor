"""Read and write the self-describing NFMonitorCSV capture format."""

from dataclasses import dataclass, field
import csv
import math


FORMAT_TAG = "#NFMonitorCSV"
CURRENT_VERSION = 4
TIME_UNIT = "us"

VAR_FIELDS = (
    "name",
    "category",
    "section",
    "unit",
    "kind",
    "owner",
    "display_name",
    "task_id",
    "direction",
    "slot",
    "scalar_type",
    "hidden",
    "task_order",
    "group_order",
    "clock_domain",
)

LEGACY_DESCRIPTOR_FIELDS = (
    "name",
    "section",
    "unit",
    "category",
    "descriptor_kind",
    "task_id",
    "direction",
    "owner",
    "display_name",
    "task_order",
    "slot",
    "group_order",
    "hidden_control",
)

SCALAR_TYPE_NAMES = {
    0: "Unknown",
    1: "Bool",
    2: "U8",
    3: "U16",
    4: "U32",
    5: "I32",
    6: "F32",
}
SCALAR_TYPE_VALUES = {name.lower(): value for value, name in SCALAR_TYPE_NAMES.items()}

CLOCK_MODEL_FIELDS = (
    "domain",
    "session",
    "mode",
    "host_clock",
    "source_anchor_us",
    "target_anchor_unix_us",
    "offset_us",
    "drift_ppm",
    "uncertainty_us",
    "rating",
    "sample_count",
    "representative_count",
    "span_us",
    "residual_us",
    "drift_uncertainty_ppb",
)

CLOCK_OBSERVATION_FIELDS = (
    "domain",
    "session",
    "sequence",
    "t1_us",
    "t2_us",
    "t3_us",
    "t4_us",
    "t1_monotonic_us",
    "t4_monotonic_us",
    "source_us",
    "receive_us",
    "receive_monotonic_us",
)


@dataclass(frozen=True)
class MonitorCsvDocument:
    metadata: dict
    series: dict
    clock_models: tuple = field(default_factory=tuple)
    clock_observations: tuple = field(default_factory=tuple)


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value):
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _direction_text(value):
    if value in (0, "0", "input"):
        return "input"
    if value in (1, "1", "output"):
        return "output"
    return str(value).strip() if value is not None else ""


def _direction_value(value):
    text = str(value).strip().lower()
    if text == "input":
        return 0
    if text == "output":
        return 1
    return _optional_int(text)


def _scalar_type_text(value):
    if isinstance(value, int):
        return SCALAR_TYPE_NAMES.get(value, str(value))
    return str(value).strip() if value is not None else ""


def _scalar_type_value(value):
    text = str(value).strip()
    if not text:
        return None
    mapped = SCALAR_TYPE_VALUES.get(text.lower())
    return mapped if mapped is not None else _optional_int(text)


def _bool_text(value):
    if isinstance(value, str):
        return "1" if value.strip().lower() in ("1", "true", "yes", "on") else "0"
    return "1" if bool(value) else "0"


def _bool_value(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _descriptor_value(item, field):
    if field == "kind":
        return item.get("kind", item.get("descriptor_kind", ""))
    if field == "hidden":
        return _bool_text(item.get("hidden", item.get("hidden_control", False)))
    if field == "direction":
        return _direction_text(item.get(field))
    if field == "scalar_type":
        return _scalar_type_text(item.get(field))
    value = item.get(field, "")
    return "" if value is None else value


def _validate_name(name):
    if not name:
        raise ValueError("CSV variable name must not be empty")
    if name.startswith("#"):
        raise ValueError(f"CSV variable name must not start with '#': {name!r}")
    if "\r" in name or "\n" in name:
        raise ValueError(f"CSV variable name contains a line break: {name!r}")


def write_monitor_csv(path, series, metadata=None, clock_data=None):
    """Write raw source-domain samples and reconstructable clock evidence."""
    prepared = []
    names = set()
    for item in series:
        name = str(item.get("name", "")).strip()
        _validate_name(name)
        if name in names:
            raise ValueError(f"Duplicate CSV variable name: {name}")
        names.add(name)

        timestamps = item.get("raw_timestamps", item.get("timestamps", ()))
        sessions = item.get("sessions", ())
        values = item.get("values", ())
        samples = []
        for index, (timestamp, value) in enumerate(zip(timestamps, values)):
            timestamp_ms = _finite_number(timestamp)
            number = _finite_number(value)
            if timestamp_ms is None or number is None:
                continue
            session = sessions[index] if index < len(sessions) else 1
            samples.append(
                (int(round(timestamp_ms * 1000.0)), int(session), number)
            )
        if samples:
            prepared.append((name, dict(item), samples))

    file_metadata = dict(metadata or {})
    clock_data = dict(clock_data or {})
    file_metadata.pop("format", None)
    file_metadata.pop("version", None)
    file_metadata["time_unit"] = TIME_UNIT
    file_metadata["value_space"] = "source"
    file_metadata["timestamp_space"] = "raw_source"
    file_metadata["active_alignment_mode"] = clock_data.get(
        "active_mode", "realtime"
    )
    for key in (
        "monitor_clock",
        "monitor_raw_anchor_us",
        "monitor_monotonic_anchor_us",
        "monitor_unix_anchor_us",
    ):
        value = clock_data.get(key)
        if value not in (None, ""):
            file_metadata[key] = value

    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow([FORMAT_TAG, CURRENT_VERSION])
        for key in (
            "time_unit",
            "value_space",
            "timestamp_space",
            "active_alignment_mode",
            "monitor_clock",
            "monitor_raw_anchor_us",
            "monitor_monotonic_anchor_us",
            "monitor_unix_anchor_us",
            "protocol",
            "schema_generation",
        ):
            value = file_metadata.pop(key, None)
            if value not in (None, ""):
                writer.writerow(["#meta", key, value])
        for key in sorted(file_metadata):
            value = file_metadata[key]
            if value not in (None, "") and not isinstance(value, (dict, list, tuple, set)):
                writer.writerow(["#meta", key, value])

        writer.writerow(["#var_fields", *VAR_FIELDS])
        for name, item, _samples in prepared:
            descriptor = {**item, "name": name}
            writer.writerow(["#var", *(_descriptor_value(descriptor, field) for field in VAR_FIELDS)])

        writer.writerow(["#clock_model_fields", *CLOCK_MODEL_FIELDS])
        for model in clock_data.get("models", ()):
            writer.writerow(
                ["#clock_model", *(model.get(field, "") for field in CLOCK_MODEL_FIELDS)]
            )
        writer.writerow(["#clock_observation_fields", *CLOCK_OBSERVATION_FIELDS])
        for observation in clock_data.get("observations", ()):
            writer.writerow(
                [
                    "#clock_observation",
                    *(observation.get(field, "") for field in CLOCK_OBSERVATION_FIELDS),
                ]
            )

        writer.writerow([])
        headers = []
        for name, _item, _samples in prepared:
            headers.extend(
                [
                    f"{name}_time_raw_us",
                    f"{name}_session",
                    f"{name}_value",
                ]
            )
        writer.writerow(headers)

        max_rows = max((len(samples) for _name, _item, samples in prepared), default=0)
        for row_index in range(max_rows):
            row = []
            for _name, _item, samples in prepared:
                if row_index >= len(samples):
                    row.extend(["", "", ""])
                    continue
                timestamp_us, session, value = samples[row_index]
                row.extend(
                    [str(timestamp_us), str(session), format(value, ".17g")]
                )
            writer.writerow(row)

    return len(prepared)


def _parse_v3_descriptor(fields, values):
    raw = {
        str(field).strip(): values[index].strip() if index < len(values) else ""
        for index, field in enumerate(fields)
        if str(field).strip()
    }
    name = raw.get("name", "")
    descriptor = {
        "section": raw.get("section") or "Ungrouped",
        "unit": raw.get("unit", ""),
    }
    text_fields = {
        "category": "category",
        "kind": "descriptor_kind",
        "owner": "owner",
        "display_name": "display_name",
        "clock_domain": "clock_domain",
    }
    for source, target in text_fields.items():
        if raw.get(source):
            descriptor[target] = raw[source]
    for field in ("task_id", "slot", "task_order", "group_order"):
        value = _optional_int(raw.get(field, ""))
        if value is not None:
            descriptor[field] = value
    direction = _direction_value(raw.get("direction", ""))
    if direction is not None:
        descriptor["direction"] = direction
    scalar_type = _scalar_type_value(raw.get("scalar_type", ""))
    if scalar_type is not None:
        descriptor["scalar_type"] = scalar_type
    if "hidden" in raw:
        descriptor["hidden_control"] = _bool_value(raw["hidden"])
    return name, descriptor


def _parse_legacy_descriptor(values):
    raw = {
        field: values[index].strip() if index < len(values) else ""
        for index, field in enumerate(LEGACY_DESCRIPTOR_FIELDS)
    }
    name = raw.pop("name", "")
    descriptor = {
        "section": raw.pop("section", "") or "Ungrouped",
        "unit": raw.pop("unit", ""),
    }
    for field in ("category", "descriptor_kind", "owner", "display_name"):
        value = raw.get(field, "")
        if value:
            descriptor[field] = value
    for field in ("task_id", "direction", "task_order", "slot", "group_order"):
        value = _optional_int(raw.get(field, ""))
        if value is not None:
            descriptor[field] = value
    if raw.get("hidden_control", ""):
        descriptor["hidden_control"] = _bool_value(raw["hidden_control"])
    return name, descriptor


def _column_pairs(headers, version, descriptors):
    if len(headers) != len(set(headers)):
        raise ValueError("CSV contains duplicate column names")
    column_index = {name: index for index, name in enumerate(headers)}
    pairs = []
    used_names = set()

    if version >= 4:
        for name in descriptors:
            time_name = f"{name}_time_raw_us"
            session_name = f"{name}_session"
            value_name = f"{name}_value"
            if all(
                column in column_index
                for column in (time_name, session_name, value_name)
            ):
                pairs.append(
                    (
                        name,
                        column_index[time_name],
                        column_index[session_name],
                        column_index[value_name],
                        "raw_us",
                    )
                )
                used_names.add(name)
        for index, header in enumerate(headers):
            if not header.endswith("_time_raw_us"):
                continue
            name = header[:-12]
            session_index = column_index.get(f"{name}_session")
            value_index = column_index.get(f"{name}_value")
            if (
                name
                and name not in used_names
                and session_index is not None
                and value_index is not None
            ):
                pairs.append(
                    (name, index, session_index, value_index, "raw_us")
                )
                used_names.add(name)
        return pairs

    if version >= 3:
        for name in descriptors:
            time_name = f"{name}_time_us"
            value_name = f"{name}_value"
            if time_name in column_index and value_name in column_index:
                pairs.append((name, column_index[time_name], None, column_index[value_name], "us"))
                used_names.add(name)
        for index, header in enumerate(headers):
            if not header.endswith("_time_us"):
                continue
            name = header[:-8]
            value_index = column_index.get(f"{name}_value")
            if name and name not in used_names and value_index is not None:
                pairs.append((name, index, None, value_index, "us"))
                used_names.add(name)
        return pairs

    for index, header in enumerate(headers):
        if header.endswith("_time_ms"):
            name = header[:-8]
            value_name = f"{name}_value"
            unit = "ms"
        elif header.endswith("_x"):
            name = header[:-2]
            value_name = f"{name}_y"
            unit = "ms"
        else:
            continue
        value_index = column_index.get(value_name)
        if name and not name.startswith("x000") and value_index is not None:
            pairs.append((name, index, None, value_index, unit))
    return pairs


def _parse_tagged_record(fields, values):
    return {
        field: values[index].strip() if index < len(values) else ""
        for index, field in enumerate(fields)
    }


def _clock_model_transform(model, raw_us):
    source_anchor = _finite_number(model.get("source_anchor_us"))
    target_anchor = _finite_number(model.get("target_anchor_unix_us"))
    drift_ppm = _finite_number(model.get("drift_ppm"))
    if source_anchor is None or target_anchor is None or drift_ppm is None:
        return float(raw_us)
    return target_anchor + (float(raw_us) - source_anchor) * (
        1.0 + drift_ppm * 1.0e-6
    )


def read_monitor_csv(path):
    metadata = {}
    descriptors = {}
    version = 0
    var_fields = VAR_FIELDS
    clock_model_fields = CLOCK_MODEL_FIELDS
    clock_observation_fields = CLOCK_OBSERVATION_FIELDS
    clock_models = []
    clock_observations = []

    with open(path, "r", newline="", encoding="utf-8-sig") as fp:
        reader = csv.reader(fp)
        headers = None
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            tag = row[0].strip()
            if not tag.startswith("#"):
                headers = [cell.strip() for cell in row]
                break
            if tag == FORMAT_TAG and len(row) >= 2:
                version = _optional_int(row[1]) or 0
            elif tag == "#meta" and len(row) >= 3:
                metadata[row[1].strip()] = row[2].strip()
            elif tag == "#var_fields":
                var_fields = tuple(cell.strip() for cell in row[1:] if cell.strip()) or VAR_FIELDS
            elif tag == "#var":
                if version >= 3:
                    name, descriptor = _parse_v3_descriptor(var_fields, row[1:])
                else:
                    name, descriptor = _parse_legacy_descriptor(row[1:])
                if name:
                    if name in descriptors:
                        raise ValueError(f"Duplicate CSV variable metadata: {name}")
                    descriptors[name] = descriptor
            elif tag == "#clock_model_fields":
                clock_model_fields = tuple(
                    cell.strip() for cell in row[1:] if cell.strip()
                ) or CLOCK_MODEL_FIELDS
            elif tag == "#clock_model":
                clock_models.append(
                    _parse_tagged_record(clock_model_fields, row[1:])
                )
            elif tag == "#clock_observation_fields":
                clock_observation_fields = tuple(
                    cell.strip() for cell in row[1:] if cell.strip()
                ) or CLOCK_OBSERVATION_FIELDS
            elif tag == "#clock_observation":
                clock_observations.append(
                    _parse_tagged_record(clock_observation_fields, row[1:])
                )
            elif tag == "#group" and len(row) >= 3:
                name = row[1].strip()
                if name:
                    descriptors[name] = {"section": row[2].strip() or "Ungrouped", "unit": ""}

        if headers is None:
            return MonitorCsvDocument(
                metadata=metadata,
                series={},
                clock_models=tuple(clock_models),
                clock_observations=tuple(clock_observations),
            )

        if version > CURRENT_VERSION:
            raise ValueError(f"Unsupported NFMonitorCSV version: {version}")
        if version >= 3 and metadata.get("time_unit", TIME_UNIT) != TIME_UNIT:
            raise ValueError(f"Unsupported NFMonitorCSV time unit: {metadata.get('time_unit')}")

        pairs = _column_pairs(headers, version, descriptors)
        if not pairs:
            metadata["format"] = "NFMonitorCSV"
            metadata["version"] = version
            return MonitorCsvDocument(
                metadata=metadata,
                series={},
                clock_models=tuple(clock_models),
                clock_observations=tuple(clock_observations),
            )

        origin_us = _optional_int(metadata.get("time_origin_unix_us", "")) or 0
        series = {
            name: {
                "timestamps": [],
                "raw_timestamps": [],
                "sessions": [],
                "values": [],
                **descriptors.get(name, {"section": "Ungrouped", "unit": ""}),
            }
            for name, _time_index, _session_index, _value_index, _unit in pairs
        }

        active_mode = metadata.get("active_alignment_mode", "realtime")
        primary_host_clock = metadata.get("monitor_clock", "monotonic")
        model_index = {
            (
                model.get("domain", ""),
                _optional_int(model.get("session", "")) or 1,
                model.get("mode", ""),
                model.get("host_clock", "") or primary_host_clock,
            ): model
            for model in clock_models
        }

        for row in reader:
            for name, time_index, session_index, value_index, unit in pairs:
                if time_index >= len(row) or value_index >= len(row):
                    continue
                timestamp = _finite_number(row[time_index])
                value = _finite_number(row[value_index])
                if timestamp is None or value is None:
                    continue
                session = (
                    _optional_int(row[session_index])
                    if session_index is not None and session_index < len(row)
                    else 1
                ) or 1
                if unit == "raw_us":
                    raw_us = int(round(timestamp))
                    domain = series[name].get("clock_domain", "monitor")
                    model = model_index.get(
                        (domain, session, active_mode, primary_host_clock)
                    )
                    if model is None and active_mode == "calibrated":
                        model = model_index.get(
                            (domain, session, "realtime", primary_host_clock)
                        )
                    aligned_us = (
                        _clock_model_transform(model, raw_us)
                        if model is not None
                        else float(raw_us)
                    )
                    timestamp_ms = aligned_us / 1000.0
                    series[name]["raw_timestamps"].append(raw_us / 1000.0)
                    series[name]["sessions"].append(session)
                elif unit == "us":
                    timestamp_ms = (origin_us + timestamp) / 1000.0
                else:
                    timestamp_ms = timestamp
                series[name]["timestamps"].append(timestamp_ms)
                series[name]["values"].append(value)

    valid_series = {
        name: data
        for name, data in series.items()
        if data["timestamps"] and len(data["timestamps"]) == len(data["values"])
    }
    metadata["format"] = "NFMonitorCSV"
    metadata["version"] = version
    return MonitorCsvDocument(
        metadata=metadata,
        series=valid_series,
        clock_models=tuple(clock_models),
        clock_observations=tuple(clock_observations),
    )
