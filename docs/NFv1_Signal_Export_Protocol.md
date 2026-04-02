# NFv1 Signal Export Protocol (Monitor-Side Reference)

This document describes the UDP NFv1 protocol used between NeuroFlap firmware and NeuroFlap Monitor.

Implementation references:

- `nfv1_parser.py`
- `data_receiver.py`

## Transport

- Protocol: UDP
- Endianness: little-endian
- Magic: `0x464E` (`"NF"`)
- Version: `1`
- Typical port: `28080` (configurable)

## Packet Types

- `0x01`: `DATA` (firmware -> monitor)
- `0x10`: `SCHEMA_REQ` (monitor -> firmware)
- `0x11`: `SCHEMA_RESP` (firmware -> monitor)

## Binary Layouts

Python struct formats used by monitor parser:

- `DATA_HEADER_FMT = "<HBBIQQH"`
- `DATA_ITEM_FMT = "<BHI"`
- `SCHEMA_REQ_FMT = "<HBBI"`
- `SCHEMA_RESP_HEADER_FMT = "<HBBHHH"`

### DATA Packet (`type=0x01`)

Header (`<HBBIQQH`):

- `magic: u16`
- `version: u8`
- `type: u8`
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
2. Firmware replies with one or more `SCHEMA_RESP` chunks.
3. Monitor collects chunks by `chunk_index/chunk_total`.
4. After all chunks arrive, monitor builds:
   - global schema map (`gid -> descriptor`)
   - fast runtime map (`signal_no -> descriptor`, data domain only)

`SCHEMA_RESP` entries are variable-length and include:

- `gid: u32`
- `scalar_type: u8`
- `name_len: u8`
- `unit_len: u8`
- `reserved: u8`
- `name: bytes`
- `unit: bytes`

## Scalar Type Mapping

- `1`: Bool
- `2`: U8
- `3`: U16
- `4`: U32
- `5`: I32
- `6`: F32

`raw (u32)` is decoded based on `scalar_type`.

## Runtime Data Semantics

Monitor supports delta-style packet streams:

- If a signal is present in current `DATA` packet, decode and publish it.
- If a signal is absent but has a cached last value, monitor carries that last value forward for continuity.

This allows efficient transport while preserving stable plotting behavior.

## Reliability Notes

- Monitor retries schema request periodically until schema sync succeeds.
- Packet sequence gaps are counted for diagnostics.
- UDP is connectionless; packet loss/reordering can occur in noisy links.
