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
4. Start Monitor, open the **NeuroFlap** tab, set ESP32 IP/port (default IP `192.168.4.1`, NFv3 UDP port `28080`).
5. Click **Connect** (connection retry: 200ms, timeout: 5s).
6. After `CONNECT_ACK`, monitor auto-requests schema and starts decoding data.
7. Keepalive runs automatically (`PING` every 2s, retry every 1s if waiting `PONG`, link timeout 6s).
8. Click **Disconnect** to release firmware session.

Notes:

- Plot `Start/Pause/Clear` is decoupled from NFv3 connection lifecycle.
- Firmware is single-session: if occupied, monitor shows busy owner IP/port.

## Protocol

Dataflow export protocol reference:

- [`docs/NFv3_Dataflow_Export_Protocol.md`](docs/NFv3_Dataflow_Export_Protocol.md)

## Troubleshooting

- No endpoint list/data:
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
