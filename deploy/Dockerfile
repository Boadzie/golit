# syntax=docker/dockerfile:1
#
# Two stages: compile the Rust kernel into an abi3 wheel, then install that wheel
# into a slim runtime. The same image serves any replica — horizontal scale is
# N of these behind a sticky load balancer (see deploy/nginx.conf), all sharing
# one Redis for SSE fan-out. Build context is the repo root:
#
#   podman build -f deploy/Dockerfile -t golit:latest .

# --- build stage: Rust + maturin → abi3 wheel ------------------------------
FROM python:3.11-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --no-cache-dir "maturin>=1.7,<2"

WORKDIR /src
# Source needed to build the wheel (readme is referenced by pyproject).
COPY pyproject.toml Cargo.toml Cargo.lock README.md ./
COPY src ./src
COPY python ./python
RUN maturin build --release --out /dist

# --- runtime stage: slim Python + the wheel --------------------------------
FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=build /dist /dist
# Pull golit (local wheel) + the redis extra; runtime deps resolve from PyPI.
RUN pip install --no-cache-dir --find-links /dist "golit[redis]" \
    && rm -rf /dist
COPY examples ./examples

EXPOSE 8000
# One worker per container — affinity is the load balancer's job, not uvicorn's.
CMD ["golit", "run", "examples/sales_explorer/app.py", "--host", "0.0.0.0", "--port", "8000"]
