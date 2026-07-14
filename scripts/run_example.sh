#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/examples:${PYTHONPATH:-}"

GEN="${ROOT}/gen"
mkdir -p "${GEN}"

python3 -m pip install -e "${ROOT}[dev]" -q

# One process: Granian HTTP + in-process gRPC→ASGI
python3 -m fastapi_grpc_gateway.cli serve \
  --app hello_app:app \
  --http-host 127.0.0.1 \
  --http-port 8000 \
  --grpc-bind 127.0.0.1:50051 \
  --out "${GEN}"
