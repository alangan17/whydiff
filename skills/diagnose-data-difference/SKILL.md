---
name: diagnose-data-difference
description: Diagnose why two read-only relations differ using deterministic WhyDiff evidence.
---

# Diagnose a data difference

Required inputs: scoped connection, left and right relations, unique keys,
measure expressions/tolerances when relevant, and an allowed sample limit.

1. Call `inspect_relations` when columns, types, or relation identity are unknown.
2. Call `compare_key_coverage` before comparing measures.
3. If keys are not unique, call `detect_duplicate_keys` for the affected side.
4. Call `compare_measures` only for keys shared by both sides.
5. Use `diagnose_difference` for the ordered aggregate report and fanout precursor evidence.
6. Call `detect_fanout` when a join/transformation may multiply rows or measures.
7. Call `inspect_date_boundaries` for cutoff/window evidence, and
   `inspect_scd2_alignment` only when fact/dimension validity fields are known.

Stop when the report passes, a deterministic finding explains the difference,
required inputs are missing, or policy rejects access. Report unknown—not a
guess—when evidence is insufficient.

Every confirmed claim must cite a tool result and finding. Keep generated SQL,
counts, tolerances, truncation, and sampled rows distinct from conclusions.
Samples illustrate evidence; they never prove totals.

Never run arbitrary SQL, modify data, expand connection/relation scope, exceed
sample or timeout limits, reveal redacted values, invoke an LLM as evidence, or
invent counts, SQL, tool results, causes, or confidence.
