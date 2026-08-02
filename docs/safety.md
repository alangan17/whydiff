# Safety, limitations, and non-goals

## Enforced boundaries

- One parsed read-only statement per adapter execution.
- No DDL/DML, attach, extension loading, external file/network scans, dynamic
  SQL, or multiple statements.
- Identifiers are validated and quoted component by component.
- Existing DuckDB files open read-only unless the Python caller explicitly
  opts out.
- MCP callers are restricted to the configured connection, relation patterns,
  sample ceiling, timeout, and redacted columns.
- Samples and materialized query results are bounded.

Aggregate measure expressions are SQL by design and are trusted configuration,
not untrusted end-user input. Review expressions as code. Database permissions
remain the final containment layer.

## Limitations

WhyDiff diagnoses evidence it can observe. Matching checks do not prove upstream
business correctness; equal aggregates can conceal offsetting errors; samples
do not establish totals; timeouts depend on driver interruption; identifiers in
generated SQL are visible to report recipients; and 0.1.0 does not provide
cross-database federation or production credential management.

## Non-goals

WhyDiff does not modify or repair data, generate arbitrary SQL, infer credentials,
replace data-quality monitoring, prove causal history, or use an LLM to decide
findings. The agent skill only selects deterministic tools and must label
insufficient evidence as unknown.
