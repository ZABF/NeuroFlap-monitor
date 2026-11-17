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

Export checks model coverage against the domain/session pairs of the samples,
including sessions with no synchronization observations. Missing or invalid
models produce `clock_fit_status=partial` (or `unavailable` when none exist) and
an entry in `clock_fit_errors`; a successful fit of other sessions is insufficient
to declare the capture complete.

When a device session has no usable matching model, the reader retains its raw
timestamps, session IDs, and values, and marks its reconstructed timestamps as
unavailable. Such samples are excluded from aligned curves and timeline bounds;
the import UI reports their number. Re-export preserves those source samples.
Readers must not treat device uptime as Unix time or silently borrow a model
from another session. The `monitor` domain can use its native Unix timestamps
without a device clock model.

For live NFv4 capture, the data path synchronizes its epoch with the active clock
estimator before recording each packet. Clearing data does not reset the active
connection's clock epoch or require waiting for another synchronization reply.

Monitor 3.5 reads v3 and older captures. Older Monitor versions are not
required to read v4 files.
