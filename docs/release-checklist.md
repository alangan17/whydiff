# 0.1.0 release checklist

- [ ] All workspace tests pass on Python 3.10 through 3.13 with required coverage.
- [ ] Formatting, lint, strict typing, and pre-commit checks pass.
- [ ] dbt package dependencies install; seeds load; macros compile; normalized
      generic-test failures execute under the supported dbt-duckdb versions.
- [ ] CLI exact-match and mismatch examples reproduce from a clean checkout.
- [ ] MCP schemas match snapshots; every tool lists and invokes without an LLM.
- [ ] Safety rejection, scope, limits, timeout, redaction, and trace tests pass.
- [ ] README/API/CLI/dbt/MCP examples match public interfaces.
- [ ] `CHANGELOG.md` and migration notes are complete.
- [ ] Core, CLI, MCP, and dbt versions all equal 0.1.0.
- [ ] Source distributions and wheels build and their contents are inspected.
- [ ] Built wheels install into a clean environment and entry points answer help.
- [ ] Git tag is signed; artifacts and checksums are published from CI.
