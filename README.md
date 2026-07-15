# fastapi-grpc-gateway

Обычный FastAPI по HTTP и по **gRPC** (Rust). В Python **нет** `import grpc`.

```
HTTP  → granian | uvicorn | gunicorn+uvicorn  → FastAPI
gRPC  → fgg-worker (Rust) → HTTP → (тот же upstream) → FastAPI
```

**Как это работает:** [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)

---

## С чего начать

```bash
uv add fastapi-grpc-gateway
# опционально:
uv add fastapi-grpc-gateway --extra uvicorn
uv add fastapi-grpc-gateway --extra gunicorn
```

### Один вход

```bash
cargo build -p fgg-worker
export FGG_WORKER=./target/debug/fgg-worker

# по умолчанию — Granian embed
uv run fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen

# uvicorn
uv run fgg serve --app app:app --http-backend uvicorn --out ./gen

# gunicorn + UvicornWorker
uv run fgg serve --app app:app --http-backend gunicorn --gunicorn-workers 2 --out ./gen
```

---

## Кто за что отвечает

| Компонент | Роль |
|-----------|------|
| `fgg serve` | HTTP backend + spawn Rust `fgg-worker` |
| `--http-backend` | `granian` (default) / `uvicorn` / `gunicorn` |
| `fgg generate` | proto + bindings |
| `fgg-worker` / `fgg-core` | **весь** gRPC (Rust) |
| ваше `app.py` | FastAPI-роуты |

---

## Для контрибьюторов

```bash
uv sync --extra dev
cargo build -p fgg-worker
uv run pytest
bash scripts/test_rust_coverage.sh
bash scripts/test_go_client.sh
```

Coverage: Python **≥ 93%**, Rust workspace (`fgg-core` + `fgg-worker`) **≥ 93%**.

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | uv / pip / Releases |
| [docs/PLAN.md](docs/PLAN.md) | Скоуп |
