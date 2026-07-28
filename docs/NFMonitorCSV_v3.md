# NFMonitorCSV v3

NFMonitorCSV v3 is a single self-describing CSV file. Comment records at the top preserve Monitor metadata; the rectangular table below stores decoded source values on independent time axes.

```csv
#NFMonitorCSV,3
#meta,time_unit,us
#meta,time_origin_unix_us,1784700000000000
#meta,value_space,source
#meta,protocol,NFv3
#meta,schema_generation,12
#var_fields,name,category,section,unit,kind,owner,display_name,task_id,direction,slot,scalar_type,hidden,task_order,group_order
#var,MadgwickTask.input.pitch,task,Task/5,deg,task_port,MadgwickTask,pitch,5,input,0,F32,0,5,
#var,MadgwickTask.latency_us,task,Task/5,us,task_latency,MadgwickTask,latency_us,5,,,U32,1,5,

MadgwickTask.input.pitch_time_us,MadgwickTask.input.pitch_value,MadgwickTask.latency_us_time_us,MadgwickTask.latency_us_value
0,1.25,0,86
10000,1.30,10000,82
```

## Data rules

- A variable name is unique within one file, must not start with `#`, and directly prefixes its `<name>_time_us` and `<name>_value` columns.
- `time_us` is an integer offset from `time_origin_unix_us`.
- Each variable owns an independent time axis. Cells on the same row are storage-aligned samples, not necessarily simultaneous events.
- Empty cells pad shorter series.
- Values are decoded source values. Derived curves and phase/scale/offset view transforms are not exported.
- `hidden=1` restores internal curves such as task latency without adding a regular variable checkbox.
- Unknown metadata fields are ignored so the format can grow without invalidating older readers.

Python can read the rectangular data table with:

```python
data = pandas.read_csv("capture.csv", comment="#")
```

MATLAB can read it with:

```matlab
opts = detectImportOptions("capture.csv", CommentStyle="#");
data = readtable("capture.csv", opts);
```

Monitor writes v3 and continues to import v2 `<name>_x,<name>_y`, `<name>_time_ms,<name>_value`, and metadata-free legacy CSV files.
