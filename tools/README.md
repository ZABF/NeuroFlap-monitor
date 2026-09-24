# Data processing tools

`clean_ch3_segments.py` extracts flight intervals from NFMonitorCSV captures and
adds filtered, zero-referenced UWB X/Y and barometer-height series.

Preview qualifying intervals without writing files:

```bash
python3 tools/clean_ch3_segments.py /path/to/captures \
  --min-high-seconds 9 --ch3-max-gap-ms 250 --analyze-only
```

Generate Monitor-compatible and metadata-free outputs:

```bash
python3 tools/clean_ch3_segments.py /path/to/captures \
  --min-high-seconds 9 \
  --ch3-max-gap-ms 250 \
  --sample-rate-hz 50 \
  --cutoff-hz 3 \
  --filter-order 2 \
  --filter-mode causal \
  --deduplicate
```

CH3 sample gaps longer than `--ch3-max-gap-ms` terminate the active segment;
missing RC data is never counted as high time. The default causal Butterworth filter can be reproduced on an MCU as one
biquad per signal. Samples with repeated source timestamps are collapsed, short
gaps use a zero-order hold, and gaps longer than `--max-gap-ms` reset filter
state. `--filter-mode zero-phase` is available only for offline comparison.

Install the additional data-processing dependencies with:

```bash
python3 -m pip install -r tools/requirements.txt
```
