# MCP server

`whydiff-mcp` is a stdio MCP server with eight domain tools. Tool schemas are
derived from typed inputs and results contain deterministic evidence and
generated SQL. There is no prompt, agent, or LLM inside the server.

The advanced tools are `detect_fanout`, `inspect_date_boundaries`, and
`inspect_scd2_alignment`. They use the same configured connection and hard
policy ceilings as the five MVP tools.

Configure one DuckDB connection when the process starts. Tool callers cannot
replace it. `--allow-relation` accepts repeatable shell-style patterns;
`--max-sample-rows`, `--timeout-seconds`, and repeatable `--redact-column`
provide hard ceilings. A relation outside scope is rejected before opening a
query. All SQL still passes the core read-only parser.

Traces contain operation name, UTC time, duration, a one-way connection ID,
sample limit, and a sanitization marker. They omit database paths, credentials,
arguments, samples, and SQL. Redacted column names are recursively masked in
tool output. Generated SQL remains part of evidence and may include configured
relation/column names, so scope those names appropriately.
