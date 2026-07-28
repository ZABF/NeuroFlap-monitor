"""Read and write the self-describing NFMonitorCSV capture format."""

from dataclasses import dataclass
import csv
import math


FORMAT_TAG = "#NFMonitorCSV"
CURRENT_VERSION = 3
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


@dataclass(frozen=True)
class MonitorCsvDocument:
    metadata: dict
    series: dict


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


def write_monitor_csv(path, series, metadata=None):
    """Write source series whose timestamps use Monitor's millisecond timeline."""
    prepared = []
    names = set()
    for item in series:
        name = str(item.get("name", "")).strip()
        _validate_name(name)
        if name in names:
            raise ValueError(f"Duplicate CSV variable name: {name}")
        names.add(name)

        timestamps = item.get("timestamps", ())
        values = item.get("values", ())
        samples = []
        for timestamp, value in zip(timestamps, values):
            timestamp_ms = _finite_number(timestamp)
            number = _finite_number(value)
            if timestamp_ms is None or number is None:
                continue
            samples.append((int(round(timestamp_ms * 1000.0)), number))
        if samples:
            prepared.append((name, dict(item), samples))

    all_timestamps = [timestamp_us for _name, _item, samples in prepared for timestamp_us, _value in samples]
    time_origin_us = min(all_timestamps, default=0)
    file_metadata = dict(metadata or {})
    file_metadata.pop("format", None)
    file_metadata.pop("version", None)
    file_metadata["time_unit"] = TIME_UNIT
    file_metadata["time_origin_unix_us"] = str(time_origin_us)
    file_metadata["value_space"] = "source"

    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow([FORMAT_TAG, CURRENT_VERSION])
        for key in ("time_unit", "time_origin_unix_us", "value_space", "protocol", "schema_generation"):
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

        writer.writerow([])
        headers = []
        for name, _item, _samples in prepared:
            headers.extend([f"{name}_time_us", f"{name}_value"])
        writer.writerow(headers)

        max_rows = max((len(samples) for _name, _item, samples in prepared), default=0)
        for row_index in range(max_rows):
            row = []
            for _name, _item, samples in prepared:
                if row_index >= len(samples):
                    row.extend(["", ""])
                    continue
                timestamp_us, value = samples[row_index]
                row.extend([str(timestamp_us - time_origin_us), format(value, ".17g")])
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

    if version >= 3:
        for name in descriptors:
            time_name = f"{name}_time_us"
            value_name = f"{name}_value"
            if time_name in column_index and value_name in column_index:
                pairs.append((name, column_index[time_name], column_index[value_name], "us"))
                used_names.add(name)
        for index, header in enumerate(headers):
            if not header.endswith("_time_us"):
                continue
            name = header[:-8]
            value_index = column_index.get(f"{name}_value")
            if name and name not in used_names and value_index is not None:
                pairs.append((name, index, value_index, "us"))
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
            pairs.append((name, index, value_index, unit))
    return pairs


def read_monitor_csv(path):
    metadata = {}
    descriptors = {}
    version = 0
    var_fields = VAR_FIELDS

    with open(path, "r", newline="", encoding="utf-8-sig") as fp:
        reader = csv.reader(fp)
        headers = None
        for row in reader:
            if not row:
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
            elif tag == "#group" and len(row) >= 3:
                name = row[1].strip()
                if name:
                    descriptors[name] = {"section": row[2].strip() or "Ungrouped", "unit": ""}

        if headers is None:
            return MonitorCsvDocument(metadata=metadata, series={})

        if version > CURRENT_VERSION:
            raise ValueError(f"Unsupported NFMonitorCSV version: {version}")
        if version >= 3 and metadata.get("time_unit", TIME_UNIT) != TIME_UNIT:
            raise ValueError(f"Unsupported NFMonitorCSV time unit: {metadata.get('time_unit')}")

        pairs = _column_pairs(headers, version, descriptors)
        if not pairs:
            return MonitorCsvDocument(metadata=metadata, series={})

        origin_us = _optional_int(metadata.get("time_origin_unix_us", "")) or 0
        series = {
            name: {
                "timestamps": [],
                "values": [],
                **descriptors.get(name, {"section": "Ungrouped", "unit": ""}),
            }
            for name, _time_index, _value_index, _unit in pairs
        }

        for row in reader:
            for name, time_index, value_index, unit in pairs:
                if time_index >= len(row) or value_index >= len(row):
                    continue
                timestamp = _finite_number(row[time_index])
                value = _finite_number(row[value_index])
                if timestamp is None or value is None:
                    continue
                if unit == "us":
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
    return MonitorCsvDocument(metadata=metadata, series=valid_series)
