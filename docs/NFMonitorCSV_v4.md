# NFMonitorCSV v4

Version 4 stores sample timestamps in their original device clock domains. It
does not overwrite source timestamps with Monitor-aligned timestamps.

Each variable descriptor includes `clock_domain`. Its data columns are:

```text
<name>_time_raw_us,<name>_session,<name>_value
```

Clock models are identified by `(domain, session, mode, host_clock)` and contain
source and Unix target anchors plus drift in ppm. Linux captures use
`monotonic_raw`; Windows captures use the QueryPerformanceCounter-backed Python
performance counter. Consumers reconstruct aligned time with:

```text
aligned_unix_us = target_anchor_unix_us
                + (raw_source_us - source_anchor_us)
                * (1 + drift_ppm / 1e6)
```

`#clock_observation` rows retain the evidence required to recompute a model:

- NeuroFlap: NFv4 `t1/t2/t3/t4` exchanges.
- FT: sensor source time and stable host-clock receive time.

The file metadata records the selected stable host clock plus its alignment/Unix
anchor. Readers must fit each session independently and must not combine samples
across timestamp rollback or reconnect boundaries.

Monitor 3.5 reads v3 and older captures. Older Monitor versions are not
required to read v4 files.
