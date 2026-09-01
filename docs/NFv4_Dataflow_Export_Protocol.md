# NFv4 TaskIO/DataNode Export Protocol

Updated: 2026-07-30

NFv4 keeps the released NFv3 Schema and Data payload layouts while adding an explicit
session, always-on four-timestamp clock synchronization, and optional diagnostics.

## Transport

For UDP data port `base`:

| Endpoint | Lifetime | Purpose |
|---|---|---|
| UDP `base` | always | Session, Schema, Data |
| UDP `base + 1` | always | Clock sync; optional diagnostic control and probes |
| TCP `base + 2` | diagnostics only | TCP capacity tests |

Disabling firmware network diagnostics does not disable clock sync.

All integer fields are little-endian. The common header is `<HBB>` with magic
`0x464E`, version `4`, and the packet type.

## Packet Types

| Type | Name | Direction |
|---|---|---|
| `0x01` | DATA | firmware to Monitor |
| `0x10` | SCHEMA_REQ | Monitor to firmware |
| `0x11` | SCHEMA_RESP | firmware to Monitor |
| `0x20` | SESSION_OPEN | Monitor to firmware |
| `0x21` | SESSION_ACCEPT | firmware to Monitor |
| `0x22` | SESSION_BUSY | firmware to Monitor |
| `0x23` | SESSION_CLOSE | Monitor to firmware |
| `0x24` | SYNC_REQUEST | Monitor to firmware |
| `0x25` | SYNC_RESPONSE | firmware to Monitor |
| `0x30` | DIAG_COMMAND | firmware to Monitor |
| `0x31` | DIAG_PROBE | bidirectional |
| `0x32` | DIAG_REPORT | Monitor to firmware |

NFv4 has no Ping/Pong, Echo, ClockSample, or ClockModel packet types. A valid matching
SYNC_RESPONSE is the NFv4 liveness proof.

## Session

`SESSION_OPEN` is `<HBBIIHH>`: client nonce, requested features, maximum UDP payload,
and preferred TCP frame size.

`SESSION_ACCEPT` is `<HBBIIIHHI>`: client nonce, session ID, accepted features,
auxiliary UDP port, diagnostic TCP port, and timeout.

Feature bits are Clock Sync, Diagnostics, and TCP Diagnostics. Clock Sync is required
for an NFv4 session.

## Schema and Data

NFv4 uses the released NFv3 Schema/Data payloads with only the version byte changed to
`4`. See [NFv3_Dataflow_Export_Protocol.md](NFv3_Dataflow_Export_Protocol.md) for those
payload definitions.

Session and diagnostic parsing remains version-specific. Only confirmed NFv4 Data and
Schema packets are normalized and delegated to the NFv3 payload parser.

## Clock Sync

`SYNC_REQUEST` is `<HBBIIIBBH>`:

```text
session_id, sequence, context, stage, flags, reserved
```

Monitor records `T1` near send. Firmware records `T2` at the raw lwIP receive callback
entry and `T3` immediately before sending the response.

`SYNC_RESPONSE` is `<HBBIIQQIBBH>`:

```text
session_id, sequence, T2, T3, context, stage, flags, reserved
```

Monitor records `T4` on receipt.

```text
RTT = (T4 - T1) - (T3 - T2)
monitor-minus-ESP midpoint offset = ((T1 - T2) + (T4 - T3)) / 2
```

The estimator publishes an affine transform:

```text
monitor_us = target_anchor_us
           + (esp_us - source_anchor_us) * (1 + drift_ppb / 1e9)
```

Monitor sends baseline `context=0` requests at a fixed 10 Hz in every alignment state.
Loaded diagnostic requests use a separate 20 Hz scheduler and never replace baseline
requests. Requests expire after six seconds; late responses cannot update the clock
model or refresh baseline liveness.

At least four valid samples provide a provisional zero-drift transform. Full lock
requires at least eight representatives, 15 seconds of span, and three consecutive
healthy fits. The estimator keeps a 120-second RTT window, derives a recent delay
floor, rejects high-delay samples from clock fitting, and robustly fits an affine
model from 2-second low-delay representatives. A rejected fit enters holdover without
publishing zero drift or moving the last good transform. Loaded diagnostic samples
never move the baseline model.

RTT remains available before clock lock. One-way `device_to_monitor` (upload) and
`monitor_to_device` (download) estimates are reported only while a usable model has
bounded uncertainty; the Monitor does not synthesize pre-lock values by splitting RTT
in half.

## Diagnostics

Diagnostics are optional and session-scoped:

- `DIAG_COMMAND`: fixed 28-byte firmware command.
- `DIAG_PROBE`: 32-byte header plus probe payload.
- `DIAG_REPORT`: one report envelope for Capabilities (24 bytes), Feedback
  (48 bytes), and Path (104 bytes).

Capabilities are sent once after session acceptance. Idle feedback is 1 Hz and active
feedback is 4 Hz. Path/model publication is revision-limited to at most 1 Hz.

## Compatibility

- New Monitor and new firmware use NFv4.
- New Monitor falls back to released NFv3 when NFv4 negotiation fails.
- New firmware still accepts released NFv3 Monitor sessions.
- NFv3 fallback uses LINK_PING/PONG and has no NFv4 clock model.
