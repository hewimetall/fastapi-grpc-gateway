# Как поставить пакет и как публиковать

## В свой проект (uv)

```bash
uv add fastapi-grpc-gateway
# fgg-worker — бинарник с Release или: cargo build -p fgg-worker
```

### Дальше

```bash
export FGG_WORKER=./fgg-worker   # или target/debug/fgg-worker
uv run fgg serve --app app:app --http-backend granian --out ./gen
uv run fgg serve --app app:app --http-backend uvicorn --out ./gen
uv run fgg serve --app app:app --http-backend gunicorn --gunicorn-workers 2 --out ./gen
```

Extras: `uv add fastapi-grpc-gateway --extra uvicorn` / `--extra gunicorn`.

gRPC **только** в Rust. В Python-пакете нет `grpcio`.

### Разработка этого репозитория

```bash
uv sync --extra dev
cargo build -p fgg-worker
uv run pytest
bash scripts/test_rust_coverage.sh
bash scripts/test_go_client.sh
```

---

## Как выложить релиз

1. Версия в `pyproject.toml` + `crates/*/Cargo.toml`.
2. `uv lock` при смене Python-зависимостей.
3. Тег `v0.2.0` → workflow Release: wheel + `fgg-worker` binary + PyPI.

### Dry-run

Actions → **Release** → `dry_run: true`.
