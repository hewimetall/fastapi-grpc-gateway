# fastapi-grpc-gateway

Minimal Python + Rust worker:

```
gRPC client → fgg-worker (Rust) → HTTP → Granian → FastAPI app
```

Python only walks routes and emits `service.proto` + `bindings.toml`.  
Runtime convert/dispatch is the Rust worker.

## Quick start

```bash
pip install -e ".[dev]"
export PATH="$HOME/.local/protoc/bin:$PATH"   # if needed
cargo build -p fgg-worker

# schema
PYTHONPATH=examples fgg generate --app hello_app:app --out ./gen

# HTTP (Granian)
cd examples && granian --interface asgi --host 127.0.0.1 --port 8000 hello_app:app

# gRPC worker (other terminal)
./target/debug/fgg-worker \
  --bind 127.0.0.1:50051 \
  --upstream http://127.0.0.1:8000 \
  --bindings ./gen/bindings.toml
```

Or: `bash scripts/run_example.sh`

## Tests

```bash
cargo build -p fgg-worker
pip install -e ".[dev]"
pytest
```

See [`docs/PLAN.md`](docs/PLAN.md).
