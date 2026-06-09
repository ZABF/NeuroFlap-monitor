# NFv2 Signal Export Protocol (Monitor-Side Reference)

This document describes the UDP NFv2 protocol used between NeuroFlap firmware and NeuroFlap Monitor.

Implementation references:

- `nfv1_parser.py`
- `data_receiver.py`

Note: some monitor-side module/class names still contain `nfv1` for compatibility,
but the wire protocol version described here is NFv2.

## Transport

- Protocol: UDP
- Endianness: little-endian
- Magic: `0x464E` (`"NF"`)
- Version: `2`
- Typical port: `28080` (configurable)

## Packet Types

- `0x01`: `DATA` (firmware -> monitor)
- `0x10`: `SCHEMA_REQ` (monitor -> firmware)
- `0x11`: `SCHEMA_RESP` (firmware -> monitor)
- `0x20`: `CONNECT_REQ` (monitor -> firmware)
- `0x21`: `CONNECT_ACK` (firmware -> monitor)
- `0x22`: `BUSY_ACK` (firmware -> monitor)
- `0x23`: `LINK_PING` (monitor -> firmware)
- `0x24`: `LINK_PONG` (firmware -> monitor)
- `0x25`: `DISCONNECT_REQ` (monitor -> firmware)

## Binary Layouts

Python struct formats used by monitor parser:

- `DATA_HEADER_FMT = "<HBBIIQQH"`
- `DATA_ITEM_FMT = "<BHI"`
- `SCHEMA_REQ_FMT = "<HBBI"`
- `SCHEMA_RESP_HEADER_FMT = "<HBBIIHHH"`
- `CTRL_HEADER_FMT = "<HBB"`
- `BUSY_ACK_FMT = "<4sH"`

### DATA Packet (`type=0x01`)

Header (`<HBBIIQQH`):

- `magic: u16`
- `version: u8`
- `type: u8`
- `schema_generation: u32`
- `packet_seq: u32`
- `build_us: u64`
- `send_us: u64`
- `item_count: u16`

Items (`item_count` times, `<BHI` each):

- `signal_no: u8`
- `dt_us: u16`
- `raw: u32`

Monitor reconstructs sample source timestamp as:

- `src_us = build_us - dt_us`

## Schema Handshake

1. Monitor sends `SCHEMA_REQ` (`type=0x10`, with `request_id`).
2. Firmware replies with one or more `SCHEMA_RESP` chunks for the current `schema_generation`.
3. Monitor collects chunks by `schema_generation + chunk_index/chunk_total`.
4. After all chunks arrive, monitor builds:
   - global schema map (`gid -> descriptor`)
   - fast runtime map (`signal_no -> descriptor`, schema-order indexed)

`SCHEMA_RESP` header includes:

- `schema_generation: u32`
- `section_mask: u32`
- `chunk_index: u16`
- `chunk_total: u16`
- `entry_count: u16`

`SCHEMA_RESP` entries are variable-length and include:

- `gid: u32`
- `scalar_type: u8`
- `name_len: u8`
- `unit_len: u8`
- `section_len: u8`
- `name: bytes`
- `unit: bytes`
- `section: bytes` (e.g. `Actuator`, `Control`, `RC`, `Sensor`, `Nav`, `Other`)

## Session Handshake And Keepalive

Monitor side:

1. Send `CONNECT_REQ` every 200ms (max 5s) until `CONNECT_ACK`.
2. `CONNECT_ACK` is a control ACK only (no schema payload).
3. On `CONNECT_ACK`, request schema via `SCHEMA_REQ`.
4. During session, send `LINK_PING` every 2s.
5. If waiting for `LINK_PONG`, retry ping every 1s.
6. If no `LINK_PONG` for 6s, treat as disconnected.
7. On manual disconnect, send `DISCONNECT_REQ`.

Firmware side:

1. Single-session mode (one active monitor endpoint).
2. New `CONNECT_REQ` from another endpoint returns `BUSY_ACK`:
   - `owner_ip[4]`
   - `owner_port(u16)`
3. Session expires after 6s without ping/connect refresh.
4. `DATA` is sent only when a session is alive.

## Scalar Type Mapping

- `0`: Unknown
- `1`: Bool
- `2`: U8
- `3`: U16
- `4`: U32
- `5`: I32
- `6`: F32

`raw (u32)` is decoded based on `scalar_type`. `scalar_type=0` means the signal exists in the static schema but has no initialized runtime type yet.

## Runtime Data Semantics

Monitor supports delta-style packet streams:

- Monitor only decodes a `DATA` packet when its `schema_generation` matches the active schema.
- If a `DATA` packet references an unknown generation, monitor drops it and requests schema again.
- If a signal is present in current `DATA` packet, decode and publish it.
- If a signal is absent but has a cached last value, monitor carries that last value forward for continuity.

This allows efficient transport while preserving stable plotting behavior.

## Reliability Notes

- Monitor retries schema request periodically until schema sync succeeds.
- Packet sequence gaps are counted for diagnostics.
- UDP is connectionless; packet loss/reordering can occur in noisy links.
