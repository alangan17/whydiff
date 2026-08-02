.PHONY: sync format lint typecheck test build

sync:
	uv sync --all-packages

format:
	uv run ruff format .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy packages/core/src packages/core/typecheck packages/cli/src packages/mcp/src evals

test:
	uv run pytest

build:
	uv build --all-packages
