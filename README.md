# WhyDiff

WhyDiff explains *why* two data relations differ. It runs deterministic,
read-only reconciliation checks for schema, row counts, business-key coverage,
duplicate keys, and numeric measures, then returns evidence and the generated
SQL. The same core powers Python, a Typer CLI, dbt macros, and MCP tools; none of
those paths calls an LLM.

WhyDiff 0.1.0 supports local DuckDB diagnostics on Python 3.12 and 3.13.

## Quick start

Install the workspace and create the bundled DuckDB example:

```console
uv sync --all-packages
uv run python examples/duckdb/create_demo.py
```

An exact match exits 0:

```console
uv run whydiff diagnose --config examples/duckdb/exact.yml
```

A mismatch prints confirmed missing/additional keys and exits 1:

```console
uv run whydiff diagnose --config examples/duckdb/mismatch.yml
```

## Python API

```python
from whydiff import MeasureConfig, ReconcileRequest, Relation, WhyDiff

request = ReconcileRequest(
    left=Relation(name="expected"),
    right=Relation(name="actual"),
    unique_keys=["id"],
    measures=[MeasureConfig(name="amount", expression="sum(amount)")],
    sample_limit=20,
)

with WhyDiff.duckdb("examples/duckdb/whydiff_demo.duckdb") as engine:
    report = engine.diagnose(request)

print(report.status)
for finding in report.findings:
    print(finding.code, finding.evidence, finding.generated_sql)
```

Public contracts are Pydantic models in `whydiff`; diagnostic functions are
also available from `whydiff.diagnostics`. See [architecture](docs/architecture.md).

## CLI

The CLI provides `diagnose`, `compare-keys`, `compare-measures`,
`inspect-schema`, `detect-duplicates`, `detect-fanout`, `inspect-dates`, and
`inspect-scd2`. Each accepts direct flags or YAML and renders console, JSON, or Markdown:

```console
uv run whydiff compare-keys \
  --database examples/duckdb/whydiff_demo.duckdb \
  --left expected --right actual --key id --format json
```

Exit codes are stable: 0 matched, 1 differences, 2 invalid configuration,
3 execution error, and 4 rejected unsafe operation. See the full [CLI guide](docs/cli.md).

## dbt

`integrations/dbt_whydiff` is a SQL-only dbt package containing
`compare_key_coverage`, `compare_measures`, and the `whydiff.reconciliation`
generic data test. The integration project compiles and executes with
dbt-duckdb and stores normalized failing rows. See its [package guide](integrations/dbt_whydiff/README.md)
and [ownership decision](integrations/dbt_whydiff/docs/ownership.md).

## MCP

The `whydiff-mcp` stdio server exposes the five MVP tools plus
`detect_fanout`, `inspect_date_boundaries`, and `inspect_scd2_alignment` with typed schemas:

```console
uv run whydiff-mcp \
  --database examples/duckdb/whydiff_demo.duckdb \
  --allow-relation 'main.*' --max-sample-rows 100
```

The database is configured by the operator, not by tool callers. Relation
scope, read-only parsing, sample limits, timeouts, redaction, and sanitized
traces are enforced locally. See the [MCP guide](docs/mcp.md).

## Safety and limitations

WhyDiff validates a single read-only SQL statement, quotes relation/key
identifiers, bounds samples, and excludes SQL text, values, paths, and
credentials from adapter audit metadata. Existing DuckDB files open read-only
by default. Review [safety, limitations, and non-goals](docs/safety.md) before
using production data.

The 0.1.0 release is deliberately narrow: DuckDB is the Python runtime backend;
the dbt package targets dbt-duckdb first; aggregate expressions are trusted
configuration; findings explain observed evidence but cannot prove business
intent; and samples are illustrative rather than totals.

## Development and releases

```console
make sync
make lint
make typecheck
make test
make build
```

See [contributing](CONTRIBUTING.md), the [changelog](CHANGELOG.md),
[versioning policy](docs/versioning.md), [roadmap status](docs/roadmap-status.md),
and [release checklist](docs/release-checklist.md).

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
