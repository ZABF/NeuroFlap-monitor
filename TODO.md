# Monitor TODO

## Done

- Added a reset button on the selected plot scale row.
  - It resets the selected plot's phase, scale, and offset.

- Added CSV import support.
  - New exports use NFMonitorCSV v3 metadata followed by independent `<var>_time_us,<var>_value` column pairs.
  - Variable names directly identify data columns; `#var` records restore TaskIO/Dataflow groups, units, types, and hidden latency curves.
  - Import also accepts v2 `<var>_x,<var>_y`, `<var>_time_ms,<var>_value`, and metadata-free legacy files.
  - Variables without metadata are placed in the `Ungrouped` section.
  - Imported variables are loaded into `DataModel` and reuse the normal plot controls.
  - Imported variables are unchecked by default.
  - Export writes source/raw data, not view-transformed data.

- Added selected-plot visibility and derived expression controls.
  - `Visible` mirrors the curve visibility checkbox and also works for derived curves.
  - `Derived...` creates expression curves such as `d(/AttRoll)`, `smooth(/AttRoll, 100)`, `clip(/AttRoll, 20)`, and `/A - /B`.
  - Derived curves expose `Edit` and `Delete`; delete lists dependent derived curves and can force-delete them together.
  - Derived curves are collected in the `Derived` group and can be transformed again.
  - Binary curve operations align to the left operand timestamp and linearly interpolate the right operand.
  - Derived curves are display-only and are skipped by CSV export.
