# Как это работает (просто)

## Одна картинка

Обычное FastAPI-приложение. HTTP — любой ASGI-сервер, gRPC — **только Rust** (`fgg-worker`):

```
                 ┌──────────────────────────────────────┐
 HTTP клиент ───►│ granian / uvicorn / gunicorn+uvicorn │──► FastAPI
                 └──────────────────────────────────────┘
                                    ▲
                                    │ HTTP
                 ┌──────────────────────────────────────┐
 gRPC клиент ───►│ fgg-worker (Rust)                    │
                 └──────────────────────────────────────┘
```

**В Python нет `import grpc`.** gRPC-стек целиком вне Python.

`fgg serve --http-backend …` поднимает HTTP и спавнит Rust `fgg-worker`.

---

## Части

| Часть | Язык | Что делает |
|-------|------|------------|
| Ваше приложение | Python / FastAPI | Обычные роуты |
| `fgg generate` / schema | Python | `service.proto` + `bindings.toml` |
| HTTP backend | Granian / uvicorn / gunicorn | ASGI HTTP |
| `fgg-worker` | **Rust** | gRPC → HTTP → upstream |
| `fgg-core` | **Rust** | bindings / frames / mapping |

---

## Шаг за шагом: вызов gRPC

1. Клиент шлёт gRPC на `fgg-worker`.
2. Worker читает `bindings.toml`, собирает HTTP-запрос.
3. Worker дергает HTTP upstream (`GET /api/users/7` и т.п.).
4. Ответ упаковывается в `JsonResponse` и уходит по gRPC.

---

## Как запустить

```bash
uv sync --extra dev
cargo build -p fgg-worker
export FGG_WORKER=./target/debug/fgg-worker

uv run fgg serve --app app:app --http-backend granian --out ./gen
uv run fgg serve --app app:app --http-backend uvicorn --out ./gen
uv run fgg serve --app app:app --http-backend gunicorn --gunicorn-workers 2 --out ./gen
```

Только схемы:

```bash
uv run fgg generate --app app:app --out ./gen
```

---

## Что писать в приложении

Обычный FastAPI — без gRPC-кода.

---

## Как вызывать из Go

См. `clients/go` / `bash scripts/test_go_client.sh`.  
Python gRPC-клиент в этом репозитории **не** используется.

---

## Чего нет (намеренно)

- `import grpc` / `grpcio` в Python-пакете
- Cookies / redirects / File / Streaming

---

## Файлы

```
fastapi_grpc_gateway/   # schema + HTTP orchestrator (без gRPC)
crates/fgg-core/        # Rust protocol core
crates/fgg-worker/      # Rust gRPC server
examples/hello_app.py
clients/go/
tests/
scripts/
```

---

## Тесты и coverage

```bash
uv sync --extra dev
cargo build -p fgg-worker
uv run pytest
bash scripts/test_rust_coverage.sh   # Rust workspace ≥ 93%
bash scripts/test_go_client.sh       # gRPC e2e через Go
```

Пороги:
- Python: **≥ 93%**
- Rust (`fgg-core` + `fgg-worker` libs): **≥ 93%**

---

## Коротко

1. Пишете FastAPI.  
2. `fgg serve` = HTTP backend + Rust worker.  
3. gRPC только в Rust.  
4. Клиенты ходят по сгенерированному proto (Go и др.).
