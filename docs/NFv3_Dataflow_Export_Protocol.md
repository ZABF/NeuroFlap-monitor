# NFv3 Dataflow Export Protocol

This document describes the UDP protocol between NeuroFlap firmware and NeuroFlap Monitor.

Implementations:

- Firmware: `system_dataflow_export_task.cpp`, `udp_dataflow_exporter.cpp`
- Monitor: `nfv3_parser.py`, `data_receiver.py`

## Transport

- UDP, little-endian
- Magic: `0x464E` (`NF`)
- Version: `3`
- Default port: `28080`
- Maximum payload: 1200 bytes

## Endpoint kinds

| kind | endpoint |
|---|---|
| 1 | Task Input |
| 2 | Task Output |
| 3 | ComputedNode |

`endpoint_no` is valid only within its `schema_generation`.

## Packet types

| type | name |
|---|---|
| `0x01` | DATA |
| `0x10` | SCHEMA_REQ |
| `0x11` | SCHEMA_RESP |
| `0x20` | CONNECT_REQ |
| `0x21` | CONNECT_ACK |
| `0x22` | BUSY_ACK |
| `0x23` | LINK_PING |
| `0x24` | LINK_PONG |
| `0x25` | DISCONNECT_REQ |

## DATA

Header: `<HBBIIQQH` (30 bytes)

```text
magic, version, type, schema_generation, packet_seq,
build_us, send_us, item_count
```

Item: `<HBIIII` (19 bytes)

```text
endpoint_no, status, publish_age_us, capture_age_us,
endpoint_seq, raw
```

Timestamps are reconstructed as:

```text
publish_us = build_us - publish_age_us
capture_us = build_us - capture_age_us
```

Status values:

| value | status |
|---|---|
| 0 | Uninitialized |
| 1 | Valid |
| 2 | Stale |
| 3 | Error |
| 4 | Stopped |

## SCHEMA

Request: `<HBBI`

Response header: `<HBBIHHH` (14 bytes)

```text
magic, version, type, schema_generation,
chunk_index, chunk_total, entry_count
```

Entry prefix: `<HBBHBBB` (9 bytes)

```text
endpoint_no, endpoint_kind, scalar_type, task_id,
owner_len, name_len, unit_len
```

The prefix is followed by UTF-8 owner, name, and unit bytes.

Scalar types: `0 Unknown`, `1 Bool`, `2 U8`, `3 U16`, `4 U32`, `5 I32`, `6 F32`.

## Runtime rules

- Monitor parses DATA only when its generation matches the active schema.
- Unknown generations trigger a schema resync.
- The exporter samples latest frames at a fixed rate; intermediate frames may be dropped.
- Missing endpoints retain their previous Monitor value.
- A stopped task emits one Stopped update.
- Task input capture timestamps, task output publish timestamps, and ComputedNode publish timestamps share this protocol.
