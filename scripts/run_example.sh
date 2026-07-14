#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/protoc/bin:${PATH}"
export PYTHONPATH="${ROOT}/examples:${PYTHONPATH:-}"

GEN="${ROOT}/gen"
mkdir -p "${GEN}"

python3 -m pip install -e "${ROOT}[dev]" -q
python3 -m fastapi_grpc_gateway.cli generate --app hello_app:app --out "${GEN}"

cargo build -p fgg-worker

# Granian HTTP
python3 -m granian --interface asgi --host 127.0.0.1 --port 8000 hello_app:app &
HTTP_PID=$!

# Rust gRPC worker
"${ROOT}/target/debug/fgg-worker" \
  --bind 127.0.0.1:50051 \
  --upstream http://127.0.0.1:8000 \
  --bindings "${GEN}/bindings.toml" &
WORKER_PID=$!

cleanup() {
  kill "${WORKER_PID}" "${HTTP_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "Granian http://127.0.0.1:8000"
echo "fgg-worker grpc://127.0.0.1:50051"
echo "Ctrl+C to stop"
wait
