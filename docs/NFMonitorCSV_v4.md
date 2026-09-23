# NFMonitorCSV v4

Version 4 stores sample timestamps in their original device clock domains. It
does not overwrite source timestamps with Monitor-aligned timestamps.

Each variable descriptor includes `clock_domain`. Its data columns are:

```text
<name>_time_raw_us,<name>_session,<name>_value
```

Clock models are identified by `(domain, session, mode)` and contain source and
Unix target anchors plus drift in ppm. Consumers reconstruct aligned time with:

```text
aligned_unix_us = target_anchor_unix_us
                + (raw_source_us - source_anchor_us)
                * (1 + drift_ppm / 1e6)
```

`#clock_observation` rows retain the evidence required to recompute a model:

- NeuroFlap: NFv4 `t1/t2/t3/t4` exchanges.
- FT: sensor source time and Monitor monotonic receive time.

The file metadata records the Monitor monotonic/Unix anchor used by those
observations. Readers must fit each session independently and must not combine
samples across timestamp rollback or reconnect boundaries.

Monitor 3.5 reads v3 and older captures. Older Monitor versions are not
required to read v4 files.
