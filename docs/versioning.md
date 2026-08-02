# Versioning policy

WhyDiff follows semantic versioning across `whydiff-core`, `whydiff-cli`, and
`whydiff-mcp`. They release together during 0.1.x.

- Patch: compatible fixes and documentation.
- Minor: additive models, findings, commands, or tools with safe defaults.
- Major: removed/renamed fields, changed enum or exit-code meaning, tightened
  accepted input, or incompatible CLI/MCP/dbt behavior.

During 0.x, intentional breaking changes still require a changelog entry,
migration notes, and synchronized package versions. dbt package compatibility
is declared by its `version` and `require-dbt-version` fields.
