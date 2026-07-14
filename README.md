# fastapi-grpc-gateway

Обычный FastAPI по HTTP (Granian) и по **gRPC** (Rust). В Python **нет** `import grpc`.

```
HTTP  → Granian (Python)  → FastAPI
gRPC  → fgg-worker (Rust) → HTTP → Granian → FastAPI
```

**Как это работает:** [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)

---

## С чего начать

```bash
uv add fastapi-grpc-gateway
# + бинарник fgg-worker с GitHub Release / `cargo build -p fgg-worker`
```

### Один вход

```bash
cargo build -p fgg-worker
export FGG_WORKER=./target/debug/fgg-worker
uv run fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen
```

---

## Кто за что отвечает

| Компонент | Роль |
|-----------|------|
| `fgg serve` | Granian HTTP + spawn Rust `fgg-worker` |
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

Coverage: Python **≥ 93%**, Rust `fgg-core` **≥ 93%**.

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | uv / pip / Releases |
| [docs/PLAN.md](docs/PLAN.md) | Скоуп |
