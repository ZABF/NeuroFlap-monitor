# External Device NFv2 Monitor Integration

This document describes the minimum UDP protocol an external device must implement
to show its variables in NeuroFlap Monitor.

The device acts as a signal data source. NeuroFlap Monitor connects to it, requests
its variable schema, then decodes incoming data packets according to that schema.

## Overview

Transport:

- UDP
- Little-endian binary fields
- Default monitor UDP port: `28080`
- Magic: `0x464E` (`"NF"`, bytes `4E 46`)
- Protocol version: `2`

Minimum device responsibilities:

1. Listen for UDP packets from NeuroFlap Monitor.
2. Reply to `CONNECT_REQ` with `CONNECT_ACK`.
3. Reply to `SCHEMA_REQ` with one or more `SCHEMA_RESP` packets.
4. Reply to `LINK_PING` with `LINK_PONG`.
5. Send `DATA` packets for the variables declared in the schema.

Monitor ignores `DATA` until the connection and schema sync are complete.

## Packet Types

| Type | Hex | Direction | Meaning |
|---|---:|---|---|
| `DATA` | `0x01` | device -> monitor | Runtime signal values |
| `SCHEMA_REQ` | `0x10` | monitor -> device | Request variable schema |
| `SCHEMA_RESP` | `0x11` | device -> monitor | Schema response chunk |
| `CONNECT_REQ` | `0x20` | monitor -> device | Start session |
| `CONNECT_ACK` | `0x21` | device -> monitor | Accept session |
| `BUSY_ACK` | `0x22` | device -> monitor | Optional: device is owned by another monitor |
| `LINK_PING` | `0x23` | monitor -> device | Keepalive ping |
| `LINK_PONG` | `0x24` | device -> monitor | Keepalive reply |
| `DISCONNECT_REQ` | `0x25` | monitor -> device | End session |

For a simple external device, implementing `CONNECT_ACK`, `SCHEMA_RESP`,
`LINK_PONG`, and `DATA` is enough.

## Scalar Types

| Type | Value | Raw encoding |
|---|---:|---|
| `Unknown` | `0` | Not initialized; monitor does not plot values |
| `Bool` | `1` | `0` or `1` in `u32` |
| `U8` | `2` | lower 8 bits of `u32` |
| `U16` | `3` | lower 16 bits of `u32` |
| `U32` | `4` | full `u32` |
| `I32` | `5` | `int32_t` bit pattern in `u32` |
| `F32` | `6` | IEEE754 `float` bit pattern in `u32` |

Example `float` to raw:

```cpp
uint32_t f32_to_raw(float value) {
  uint32_t raw = 0;
  static_assert(sizeof(raw) == sizeof(value));
  std::memcpy(&raw, &value, sizeof(raw));
  return raw;
}
```

## Control Packets

Control packets use this layout:

```text
<HBB
magic   : u16 = 0x464E
version : u8  = 2
type    : u8
```

Size: 4 bytes.

Examples:

```text
CONNECT_REQ from monitor: 4E 46 02 20
CONNECT_ACK from device : 4E 46 02 21
LINK_PING from monitor  : 4E 46 02 23
LINK_PONG from device   : 4E 46 02 24
```

`DISCONNECT_REQ` can be handled by stopping the session. A minimal device may
simply clear its active monitor endpoint when it receives it.

## Schema Request

Monitor sends:

```text
<HBBI
magic      : u16 = 0x464E
version    : u8  = 2
type       : u8  = 0x10
request_id : u32
```

Size: 8 bytes.

The device should respond to the sender address with `SCHEMA_RESP`.

## Schema Response

The schema declares what variables exist and how their raw values should be decoded.

Header:

```text
<HBBIIHHH
magic             : u16 = 0x464E
version           : u8  = 2
type              : u8  = 0x11
schema_generation : u32
section_mask      : u32
chunk_index       : u16
chunk_total       : u16
entry_count       : u16
```

Header size: 18 bytes.

Entry prefix:

```text
<IBBBB
gid         : u32
scalar_type : u8
name_len    : u8
unit_len    : u8
section_len : u8
name bytes
unit bytes
section bytes
```

Entry prefix size: 8 bytes plus string bytes.

Rules:

- `schema_generation` must stay constant while the schema is unchanged.
- Increment `schema_generation` when variable order, type, name, unit, or section changes.
- `section_mask` can be `0xFFFFFFFF` for external devices.
- `chunk_index` starts from `0`.
- `chunk_total` is the total number of schema response chunks.
- Keep UDP payloads below about `1200` bytes. Split schema into chunks if needed.
- `gid` must be stable and unique per variable.
- `signal_no` in `DATA` is not transmitted in schema. It is implicitly the entry order:
  first schema entry is `signal_no = 0`, second is `1`, and so on.
- Current monitor data packets use `signal_no: u8`, so use at most 256 variables.

Recommended `gid` layout:

```text
gid = (section_id << 16) | signal_id
```

This is only a convention. The monitor only requires uniqueness and stability.

Example schema entries:

| signal_no | gid | type | name | unit | section |
|---:|---:|---:|---|---|---|
| 0 | `0x00010000` | `6` | `Pitch` | `deg` | `IMU` |
| 1 | `0x00010001` | `6` | `Roll` | `deg` | `IMU` |
| 2 | `0x00020000` | `6` | `Voltage` | `V` | `Power` |

These appear in the monitor as grouped plot variables under `IMU` and `Power`.

## Data Packet

Header:

```text
<HBBIIQQH
magic             : u16 = 0x464E
version           : u8  = 2
type              : u8  = 0x01
schema_generation : u32
packet_seq        : u32
build_us          : u64
send_us           : u64
item_count        : u16
```

Header size: 30 bytes.

Item:

```text
<BHI
signal_no : u8
dt_us     : u16
raw       : u32
```

Item size: 7 bytes.

Timestamp rules:

- `build_us` is the device monotonic time when the packet was built.
- `send_us` is the device monotonic time when the packet was sent.
- For simple devices, `build_us` and `send_us` can be the same value.
- `dt_us` is the age of this sample relative to `build_us`.
- Monitor reconstructs sample source time as `src_us = build_us - dt_us`.
- If all values are sampled at packet build time, set `dt_us = 0`.

Data rules:

- `schema_generation` must match the latest schema response.
- `packet_seq` should increment by 1 for each sent data packet.
- `signal_no` is the schema entry order index.
- You may send all variables every packet.
- You may also send only changed variables. Monitor carries forward the last value
  for variables absent from a delta packet.

## Minimal Session Flow

```text
Monitor                         Device
   | ---- CONNECT_REQ ---------> |
   | <--- CONNECT_ACK ---------- |
   | ---- SCHEMA_REQ ----------> |
   | <--- SCHEMA_RESP chunk 0 -- |
   | <--- SCHEMA_RESP chunk N -- |
   |                             |
   | <--- DATA ----------------- |
   | <--- DATA ----------------- |
   |                             |
   | ---- LINK_PING -----------> |
   | <--- LINK_PONG ----------- |
```

Monitor behavior:

- Sends `CONNECT_REQ` every 200 ms until accepted, for up to about 5 seconds.
- Sends `SCHEMA_REQ` after `CONNECT_ACK`.
- Retries schema request every 1 second until schema sync completes.
- Sends `LINK_PING` about every 2 seconds.
- Treats link as disconnected if no `LINK_PONG` for about 6 seconds.

Device behavior:

- Remember the monitor endpoint from `CONNECT_REQ`.
- Send control replies and data packets to that endpoint.
- Reply to every `LINK_PING`.
- Stop or pause data when the session expires or after `DISCONNECT_REQ`.

## Minimal C++ Data Structures

```cpp
enum ScalarType : uint8_t {
  TYPE_UNKNOWN = 0,
  TYPE_BOOL = 1,
  TYPE_U8 = 2,
  TYPE_U16 = 3,
  TYPE_U32 = 4,
  TYPE_I32 = 5,
  TYPE_F32 = 6,
};

struct SignalDesc {
  uint32_t gid;
  uint8_t type;
  const char* name;
  const char* unit;
  const char* section;
};

static const SignalDesc kSchema[] = {
  {0x00010000u, TYPE_F32, "Pitch", "deg", "IMU"},
  {0x00010001u, TYPE_F32, "Roll", "deg", "IMU"},
  {0x00020000u, TYPE_F32, "Voltage", "V", "Power"},
};
```

When sending data:

```cpp
// signal_no follows kSchema order:
// Pitch   -> 0
// Roll    -> 1
// Voltage -> 2
```

## Practical Checklist

For an external device to show variables in NeuroFlap Monitor:

1. Open UDP socket on the device.
2. Receive `CONNECT_REQ`.
3. Reply `CONNECT_ACK`.
4. Receive `SCHEMA_REQ`.
5. Reply `SCHEMA_RESP` with variable names, units, sections, and scalar types.
6. Start sending `DATA` packets using schema order `signal_no`.
7. Reply `LINK_PING` with `LINK_PONG`.

If variables do not appear:

- Confirm monitor is connected.
- Confirm `SCHEMA_RESP` uses version `2` and magic `0x464E`.
- Confirm `DATA.schema_generation` equals the synced schema generation.
- Confirm `signal_no` is less than schema entry count and less than 256.
- Confirm `scalar_type` is not `Unknown`.
- Confirm float values are sent as IEEE754 raw bits, not integer-cast floats.
