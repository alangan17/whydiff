# Roadmap status

This records implementation state in the 0.1.0 working tree; it does not replace
GitHub issue state or release approval.

| Roadmap issue | Working-tree status |
| --- | --- |
| #1–#3 foundation, contracts, secure DuckDB adapter | Implemented and tested |
| #4–#8 deterministic diagnostics, engine, reports | Implemented and tested |
| #9 CLI | Implemented with direct/YAML inputs, three formats, and exit codes |
| #10 dbt | Implemented; dbt-duckdb compilation/execution verified |
| #11 MCP | Eight typed, scoped tools implemented and invoked without an LLM |
| #12 skill/evals | Skill plus seven deterministic cases and encoded targets implemented |
| #13 fanout | Core, CLI, MCP, and eval integration implemented |
| #14 date/time | Core, CLI, MCP, and eval integration implemented |
| #15 SCD2 | Core, CLI, MCP, and eval integration implemented |
| #16 release 0.1.0 | Artifacts build; final CI/tag/publication checklist remains |

The scope-control rules from #17 remain: DuckDB first, no arbitrary-SQL agent
tool, no LLM dependency in dbt or deterministic findings, and no release until
the checklist and supported Python matrix pass in CI.
