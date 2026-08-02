# CLI guide

All commands use the same connection, comparison, output, and sample settings.
Direct flags override YAML values.

```yaml
connection:
  database: warehouse.duckdb
  timeout_seconds: 30
comparison:
  left: expected_orders
  right: actual_orders
  unique_keys: [order_id]
  null_equals_zero: false
measures:
  - name: revenue
    expression: sum(net_revenue)
    absolute_tolerance: 0.01
    relative_tolerance: 0.001
output:
  format: json
  path: report.json
sample_limit: 50
```

Commands:

- `diagnose` runs the complete ordered workflow.
- `compare-keys` reports matched, left-only, and right-only distinct keys.
- `compare-measures` compares configured aggregates on shared keys.
- `inspect-schema` inspects one relation or compares `--left` and `--right`.
- `detect-duplicates` checks a declared business key in one relation.
- `detect-fanout` compares grain and measures across `--before` and `--after`.
- `inspect-dates` checks bounded distributions around a timestamp column.
- `inspect-scd2` checks fact events against dimension validity ranges.

Repeat `--key` and `--measure`; a measure flag is
`name=aggregate_expression`. Output formats are `console`, `json`, and
`markdown`. Configuration errors never include a Python traceback.

Exit status is 0 for a match, 1 for a difference or warning, 2 for invalid
configuration, 3 for database/execution errors, and 4 when SQL safety rejects
an operation.
