# Contributing to WhyDiff

WhyDiff supports Python 3.12 and 3.13 and uses `uv` for a reproducible workspace.

## Set up

1. Install `uv`.
2. Run `make sync` from the repository root.
3. Optionally install local hooks with `uv run pre-commit install`.

## Development workflow

Changes to behavior follow a red-green test loop at a public seam: first add one failing
test that describes caller-visible behavior, then add the smallest implementation that
makes it pass. Avoid tests of private helpers and internal call sequences.

Before opening a pull request, run:

```console
make lint
make typecheck
make test
make build
```

Public Pydantic field names, enum values, serialized output, adapter methods, and exception
types are compatibility contracts. Prefer additive changes with defaults. Renaming,
removing, or changing the meaning of an existing contract requires a major release and a
migration note.

Database work must remain read-only through the adapter boundary. Never interpolate data
values into SQL, bypass SQL validation, or include SQL text, credentials, parameters, or
database paths in audit metadata.
