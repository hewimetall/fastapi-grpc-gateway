#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PYTHONPATH="${ROOT}/examples:${PYTHONPATH:-}"
export PATH="${HOME}/.local/protoc/bin:${PATH:-}"

GEN="${ROOT}/gen"
mkdir -p "${GEN}"

uv sync --extra dev --frozen
cargo build -p fgg-worker
export FGG_WORKER="${ROOT}/target/debug/fgg-worker"

uv run fgg serve \
  --app hello_app:app \
  --http-host 127.0.0.1 \
  --http-port 8000 \
  --grpc-bind 127.0.0.1:50051 \
  --out "${GEN}" \
  --worker "${FGG_WORKER}"
