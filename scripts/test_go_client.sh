#!/usr/bin/env bash
# End-to-end: Granian + Rust fgg-worker + Go gRPC client (no Python gRPC)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/protoc/bin:$(go env GOPATH)/bin:${PATH}"
export PYTHONPATH="${ROOT}/examples:${PYTHONPATH:-}"

GEN="${ROOT}/gen"
HTTP_PORT="${HTTP_PORT:-18000}"
GRPC_PORT="${GRPC_PORT:-15051}"

mkdir -p "${GEN}"
uv sync --extra dev --frozen
cargo build -p fgg-worker
WORKER="${ROOT}/target/debug/fgg-worker"

uv run fgg generate --app hello_app:app --out "${GEN}"

mkdir -p "${ROOT}/clients/go/gen"
protoc -I "${GEN}" \
  --go_out="${ROOT}/clients/go/gen" --go_opt=paths=source_relative \
  --go-grpc_out="${ROOT}/clients/go/gen" --go-grpc_opt=paths=source_relative \
  "${GEN}/service.proto"

uv run fgg serve \
  --app hello_app:app \
  --http-host 127.0.0.1 \
  --http-port "${HTTP_PORT}" \
  --grpc-bind "127.0.0.1:${GRPC_PORT}" \
  --out "${GEN}" \
  --worker "${WORKER}" \
  >/tmp/fgg-serve.log 2>&1 &
SERVE_PID=$!

cleanup() {
  kill "${SERVE_PID}" 2>/dev/null || true
  wait "${SERVE_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 80); do
  if (echo >/dev/tcp/127.0.0.1/"${HTTP_PORT}") 2>/dev/null \
    && (echo >/dev/tcp/127.0.0.1/"${GRPC_PORT}") 2>/dev/null; then
    break
  fi
  sleep 0.1
done

cd "${ROOT}/clients/go"
go mod tidy
FGG_GRPC_ADDR="127.0.0.1:${GRPC_PORT}" go test -v -count=1 .
