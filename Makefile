PYTHON_VERSION := 3.11

.PHONY: dev build test test-rust test-py lint run docs docs-serve clean

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

# --no-sync keeps uv from reinstalling golit over the maturin editable build.
test-py:
	uv run --no-sync maturin develop --uv
	uv run --no-sync pytest

## Lint and type-check.
lint:
	uv run --no-sync ruff check python tests examples
	uv run --no-sync mypy

## Run the example app.
run:
	uv run --no-sync python -m golit run examples/sales_explorer/app.py

## Build the documentation site (MkDocs Material) into site/.
docs:
	uv run --group docs mkdocs build --strict

## Serve the docs locally with live reload.
docs-serve:
	uv run --group docs mkdocs serve

clean:
	rm -rf target .venv dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
