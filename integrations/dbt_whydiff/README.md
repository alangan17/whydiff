# dbt WhyDiff

A thin, SQL-only dbt package for key coverage and aggregate measure parity.
It shares WhyDiff's classifications but does not call Python, MCP, an LLM, or
arbitrary user-supplied code at runtime.

Add this repository as a local or Git package and call:

```jinja
{{ whydiff.compare_key_coverage(ref('expected'), ref('actual'), ['id']) }}
```

Or configure the generic data test:

```yaml
data_tests:
  - whydiff.reconciliation:
      arguments:
        compare_model: ref('actual')
        unique_key: [id]
        measures:
          - name: amount
            expression: sum(amount)
```

The test emits normalized failing rows with `finding_code`, `finding_side`,
`key_values`, `measure_name`, `left_value`, `right_value`, and `difference`.

Intentional differences from Python: dbt runs inside the active adapter and
therefore relies on warehouse permissions/timeouts; it emits failing rows
instead of a `DiagnosisReport`; it does not return samples separately; and the
initial cross-database support is limited to SQL features used by DuckDB.
