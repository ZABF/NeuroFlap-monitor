# NFv3 TaskIO/DataNode Export Protocol

NFv3 is the little-endian UDP protocol between NeuroFlap firmware and Monitor. The current compact NFv3 layout is incompatible with the former flat `endpoint_no` NFv3 layout.

## Transport

- Magic `0x464E` (`NF`), version `3`
- Default UDP port `28080`
- Maximum packet size `1200` bytes
- One active Monitor session; keepalive timeout is 6 seconds
- DATA carries latest snapshots and may skip intermediate task executions

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

Header `<HBBIIQHH>` (24 bytes):

```text
magic, version, type, schema_generation, packet_seq,
packet_time_us, task_frame_count, node_frame_count
```

All TaskFrames follow the header, then all DataNodeFrames.

### TaskFrame

Header `<HBII>` (11 bytes):

```text
task_id, flags, input_age_us, output_age_us
```

Flags: bit 0 business enabled, bit 1 inputs valid, bit 2 outputs valid.

The remaining layout is determined by the Task and TaskPort schema:

```text
input_raw[input_count]                 u32 each
output_raw[output_count]               u32 each
input_custom_age[input_group_count]    u32 each
output_custom_age[output_group_count]  u32 each
```

Frame size:

```text
11 + 4 * (input_count + output_count + input_group_count + output_group_count)
```

A port with `timestamp_group == 0xFF` uses the task-level input/output age. Other values index the corresponding custom-age array.

### DataNodeFrame

`<HBII>` (11 bytes):

```text
node_no, status, publish_age_us, raw
```

Status values: `0 Uninitialized`, `1 Valid`, `2 Stale`, `3 Error`, `4 Stopped`.

For every valid age:

```text
event_us = packet_time_us - event_age_us
```

`0xFFFFFFFF` means the timestamp is unavailable.

## SCHEMA

Request: `<HBBI>` containing `magic, version, type, request_id`.

Response header `<HBBIHHHH>` (16 bytes):

```text
magic, version, type, schema_generation,
chunk_index, chunk_total, entry_count, total_entries
```

Each entry starts with `<BH>`: `entry_kind, payload_len`.

### Task entry, kind 1

```text
task_id u16
input_count u8
output_count u8
input_timestamp_group_count u8
output_timestamp_group_count u8
name_len u8
name bytes
```

### TaskPort entry, kind 2

```text
task_id u16
direction u8       # 0 input, 1 output
slot u8
scalar_type u8
timestamp_group u8 # 0xFF uses task-level age
name_len u8
unit_len u8
name bytes
unit bytes
```

The runtime TaskPort key is `(task_id, direction, slot)`.

### DataNode entry, kind 3

```text
node_no u16
node_id u16
scalar_type u8
group_len u8
name_len u8
unit_len u8
group bytes
name bytes
unit bytes
```

`node_no` is compact and generation-local. `node_id` is the logical stable ID.

Scalar types: `0 Unknown`, `1 Bool`, `2 U8`, `3 U16`, `4 U32`, `5 I32`, `6 F32`.

## Session flow

1. Send `CONNECT_REQ`; wait for `CONNECT_ACK` or handle `BUSY_ACK`.
2. Send `SCHEMA_REQ`; collect every chunk for one generation and validate `total_entries`.
3. Install Task, TaskPort, and DataNode schema.
4. Decode only DATA with the installed generation.
5. Send `LINK_PING` every 2 seconds; treat 6 seconds without a pong as disconnected.
6. Drop DATA with an unknown generation and request schema again.

Firmware uses an internal `run_seq` and seqlocks to capture one coherent task cycle. `run_seq` is intentionally absent from the wire format.
