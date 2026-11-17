# NeuroFlap Monitor

NeuroFlap Monitor is a Python desktop ground station for NeuroFlap firmware.
It visualizes exported runtime signals and can also ingest optional external streams (for example FT and MoCap, depending on your local setup).

## Related Firmware

- Firmware repo: https://github.com/NEAR-the-future/NeuroFlap-Esp32s3

## Requirements

- Python 3.10+ (recommended)
- OS: Windows/Linux/macOS
- Dependencies listed in [`requirements.txt`](requirements.txt)

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux/macOS:

```bash
source .venv/bin/activate
```

## Run

```bash
python run.py
```

## Typical Usage

1. Flash and start the NeuroFlap firmware on ESP32-S3.
2. Ensure `SysDataflowExportTask` is running on firmware.
3. Connect PC and ESP32 to the same network (or ESP32 SoftAP).
4. Start Monitor, open the **NeuroFlap** tab, set ESP32 IP/port (default IP `192.168.4.1`, UDP port `28080`).
5. Click **Connect** (connection retry: 200ms, timeout: 5s).
6. Monitor negotiates NFv4 first and falls back to released NFv3 when needed.
7. After session acceptance, Monitor requests schema and starts decoding data.
8. NFv4 clock sync also maintains liveness; NFv3 fallback uses `PING/PONG`.
9. Click **Disconnect** to release firmware session.

Notes:

- Plot `Start/Pause/Clear` is decoupled from the firmware connection lifecycle.
- Firmware is single-session: if occupied, monitor shows busy owner IP/port.

## Continuous Angle Curves

Use **Derived...** to create `unwrap([MadgwickTask.output.yaw])`, or select an angle
curve and use the `unwrap()` button in the derived-curve editor. The default period
is 360 degrees; `unwrap([yaw_rad], 6.283185307179586)` uses radians instead.

For example, `170, 179, -179, -170` becomes `170, 179, 181, 190`. Each change larger
than half the period is corrected by a whole number of periods. The first angle
is retained; unwrap does not set a new zero. Consecutive true motion must be less
than half a turn, since wrapped samples cannot reveal skipped turns.

The cumulative angle is anchored to the recording rather than the visible
window, so panning, zooming and replay seeking preserve the turn count. Raw-source
unwrap resets across clock sessions, invalid samples, clears and source changes.
Direct source inputs process appended samples incrementally; composite inputs
are recalculated when dependencies change. Use `d(unwrap([yaw]))` for angular
velocity without spikes at the wrap boundary. Original samples and CSV exports
retain the source angle.

## Protocol

Dataflow export protocol reference:

- [`docs/NFv4_Dataflow_Export_Protocol.md`](docs/NFv4_Dataflow_Export_Protocol.md)
- [`docs/NFv3_Dataflow_Export_Protocol.md`](docs/NFv3_Dataflow_Export_Protocol.md)

Monitor capture format:

- [`docs/NFMonitorCSV_v3.md`](docs/NFMonitorCSV_v3.md)

## Troubleshooting

- No TaskIO/DataNode variable list or data:
  - Check firmware `SysDataflowExportTask` is started.
  - Check ESP32 IP/port in NeuroFlap tab.
  - Verify monitor status is `Connected` (not `Disconnected`/`Busy`).
  - Confirm firewall allows UDP on the configured port.
- Schema never syncs:
  - Verify network route from monitor to ESP32.
  - Check firmware log for schema response counters.
- Busy state:
  - Another monitor endpoint is currently connected.
  - Wait for timeout or disconnect from the owner monitor.
