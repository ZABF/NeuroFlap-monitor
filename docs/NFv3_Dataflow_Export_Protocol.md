# NFv3 TaskIO/Function Output Export Protocol

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
packet_time_us, task_frame_count, reserved_frame_count
```

All TaskFrames follow the header. Functions also use TaskFrames; there is no separate
FunctionOutputFrame wire type. `reserved_frame_count` must be zero.

### TaskFrame

Header `<HBII>` (11 bytes):

```text
task_id, flags, input_age_us, output_age_us
```

Flags:

- bit 0: executable enabled
- bit 1: inputs valid
- bit 2: outputs valid
- bits 3..7: snapshot contention count, saturated at 31

The contention count is the number of exporter reads that met an in-progress TaskFrame
publication since the previous emitted frame. The exporter retries contended tasks once
after one scheduler tick. A non-zero count is diagnostic only; it does not make the
TaskFrame invalid and does not change the frame size.

Input values, output values, task start/end times, and the frame generation come from one
atomic task publication. If the retry still cannot acquire that publication, the exporter
omits that task from the packet, so the Monitor retains its last received sample. The
firmware never combines fields from different task executions into one frame.

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

### Function output

A Function is represented by a Task entry with `category=function`:

- `input_count` is zero;
- `output_count` is the number of Function outputs;
- outputs are described by TaskPort entries;
- `input_age_us` is the invocation start age and `output_age_us` is the invocation
  finish age;
- all outputs use the task-level finish age, so outputs from one invocation share a
  timestamp;
- execution duration is `(packet_time_us - output_age_us) -
  (packet_time_us - input_age_us)`.

The outputs are read from one atomic execution snapshot. The Function persistence key
is not the wire entity ID; the exporter assigns a temporary ID within each schema
generation.

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
category u8
input_count u8
output_count u8
input_timestamp_group_count u8
output_timestamp_group_count u8
name_len u8
name bytes
```

Category values are `0 unknown`, `1 system`, `2 business`, `3 device`, and
`4 function`. A Monitor must use this field instead of inferring a category from the
numeric task ID. An old entry without this field may be treated as `unknown`.

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

Scalar types: `0 Unknown`, `1 Bool`, `2 U8`, `3 U16`, `4 U32`, `5 I32`, `6 F32`.

## Session flow

1. Send `CONNECT_REQ`; wait for `CONNECT_ACK` or handle `BUSY_ACK`.
2. Send `SCHEMA_REQ`; collect every chunk for one generation and validate `total_entries`.
3. Install Task and TaskPort schema.
4. Decode only DATA with the installed generation.
5. Send `LINK_PING` every 2 seconds; treat 6 seconds without a pong as disconnected.
6. Drop DATA with an unknown generation and request schema again.

Firmware uses an internal `run_seq` and seqlocks to capture one coherent task cycle. `run_seq` is intentionally absent from the wire format.
