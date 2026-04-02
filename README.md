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
2. Ensure `SysSignalExportTask` is running on firmware.
3. Connect PC and ESP32 to the same network (or ESP32 SoftAP).
4. Start Monitor and configure UDP target/listen settings (default flow uses UDP port `28080`).
5. Monitor sends schema request, receives schema/data packets, then updates plots in real time.

## Protocol

Signal export protocol reference:

- [`docs/NFv1_Signal_Export_Protocol.md`](docs/NFv1_Signal_Export_Protocol.md)

## Troubleshooting

- No signal list/data:
  - Check firmware `SysSignalExportTask` is started.
  - Check ESP32 IP/port in monitor settings.
  - Confirm firewall allows UDP on the configured port.
- Schema never syncs:
  - Verify network route from monitor to ESP32.
  - Check firmware log for schema response counters.
