# Diagnosis-agent evaluations

These evaluations score already-recorded tool calls and reports. They do not
invoke an LLM and can run separately from core tests:

```bash
python evals/evaluator.py evals/cases/exact_match.json transcript.json
```

Targets are encoded in `evaluator.TARGETS`: at least 90% root-cause accuracy,
0% forbidden calls, 0 unsupported confirmed claims, and 100% schema-valid
reports. A confirmed claim without evidence always fails.
