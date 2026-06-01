PYTHON_VERSION := 3.11

.PHONY: dev build test test-rust test-py lint run clean

## Create the uv venv, install deps, and build the Rust extension (editable).
dev:
	uv venv --python $(PYTHON_VERSION)
	uv sync --no-install-project
	uv run maturin develop --uv

## Build a release wheel.
build:
	uv run maturin build --release

## Run the full test suite (Rust kernel + Python).
test: test-rust test-py

test-rust:
	PYO3_PYTHON="$(CURDIR)/.venv/bin/python" cargo test

test-py:
	uv run maturin develop --uv
	uv run pytest

## Lint and type-check.
lint:
	uv run ruff check python tests examples
	uv run mypy

## Run the example app.
run:
	uv run python -m golit run examples/sales_explorer/app.py

clean:
	rm -rf target .venv dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
