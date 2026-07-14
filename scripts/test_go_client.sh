#!/usr/bin/env bash
# End-to-end: Granian + fgg-worker + Go gRPC client
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/protoc/bin:$(go env GOPATH)/bin:${PATH}"
export PYTHONPATH="${ROOT}/examples:${PYTHONPATH:-}"

GEN="${ROOT}/gen"
HTTP_PORT="${HTTP_PORT:-18000}"
GRPC_PORT="${GRPC_PORT:-15051}"

mkdir -p "${GEN}"
python3 -m pip install -e "${ROOT}[dev]" -q
python3 -m fastapi_grpc_gateway.cli generate --app hello_app:app --out "${GEN}"

# regenerate Go stubs from current proto
mkdir -p "${ROOT}/clients/go/gen"
protoc -I "${GEN}" \
  --go_out="${ROOT}/clients/go/gen" --go_opt=paths=source_relative \
  --go-grpc_out="${ROOT}/clients/go/gen" --go-grpc_opt=paths=source_relative \
  "${GEN}/service.proto"

cargo build -p fgg-worker

# start Granian
python3 -m granian --interface asgi --host 127.0.0.1 --port "${HTTP_PORT}" hello_app:app \
  >/tmp/fgg-granian.log 2>&1 &
HTTP_PID=$!

# start worker
"${ROOT}/target/debug/fgg-worker" \
  --bind "127.0.0.1:${GRPC_PORT}" \
  --upstream "http://127.0.0.1:${HTTP_PORT}" \
  --bindings "${GEN}/bindings.toml" \
  >/tmp/fgg-worker.log 2>&1 &
WORKER_PID=$!

cleanup() {
  kill "${WORKER_PID}" "${HTTP_PID}" 2>/dev/null || true
  wait "${WORKER_PID}" "${HTTP_PID}" 2>/dev/null || true
}
trap cleanup EXIT

# wait for ports
for i in $(seq 1 50); do
  if (echo >/dev/tcp/127.0.0.1/"${HTTP_PORT}") 2>/dev/null \
    && (echo >/dev/tcp/127.0.0.1/"${GRPC_PORT}") 2>/dev/null; then
    break
  fi
  sleep 0.1
done

cd "${ROOT}/clients/go"
go mod tidy
FGG_GRPC_ADDR="127.0.0.1:${GRPC_PORT}" go test -v -count=1 .
