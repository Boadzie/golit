PYTHON_VERSION := 3.11

.PHONY: dev build test test-rust test-py lint run bench bench-quick bench-http bench-streamlit bench-marimo docs docs-serve clean

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
	uv run --no-sync ruff check python tests examples bench
	uv run --no-sync mypy

## Run the example app.
run:
	uv run --no-sync python -m golit run examples/sales_explorer/app.py

## Run the full B1 benchmark (in-process + HTTP + Streamlit + Marimo rivals) and charts.
bench:
	uv run --no-sync python -m bench.run_b1
	uv run --no-sync python -m bench.http.run_b1_http
	uv run --no-sync python -m bench.run_b1_streamlit
	uv run --no-sync python -m bench.run_b1_marimo
	uv run --no-sync python -m bench.plot

## Cross-framework B1 only: Streamlit (AppTest) rival vs Golit. Needs the bench group.
bench-streamlit:
	uv run --no-sync python -m bench.run_b1_streamlit
	uv run --no-sync python -m bench.plot

## Cross-framework B1 only: Marimo (reactive) rival vs Golit. Needs the bench group.
bench-marimo:
	uv run --no-sync python -m bench.run_b1_marimo
	uv run --no-sync python -m bench.plot

## Fast in-process B1 sweep (fewer points/iterations) for a quick signal.
bench-quick:
	uv run --no-sync python -m bench.run_b1 --quick
	uv run --no-sync python -m bench.plot

## End-to-end HTTP B1 only (boots uvicorn per config; drives the real POST path).
bench-http:
	uv run --no-sync python -m bench.http.run_b1_http
	uv run --no-sync python -m bench.plot

## Build the documentation site (MkDocs Material) into site/.
docs:
	uv run --group docs mkdocs build --strict

## Serve the docs locally with live reload.
docs-serve:
	uv run --group docs mkdocs serve

clean:
	rm -rf target .venv dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
