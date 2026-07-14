# План: FastAPI ↔ gRPC через Rust (Granian + PyO3/tonic)

## Цель

Добавить gRPC-gateway в FastAPI так, чтобы для приложения это было **бесшовно**:

- маршруты остаются обычными FastAPI routes (`APIRouter`, `Depends`, OpenAPI);
- тяжёлая работа (HTTP/2, protobuf, пул каналов, дедлайны) — в **Rust**;
- рантайм HTTP — **Granian** (Rust-сервер, замена uWSGI/uvicorn для ASGI).

Репозиторий сейчас пустой (`README` only). Это greenfield-план реализации `fastapi-grpc-gateway`.

---

## Контекст исследования

| Факт | Вывод |
|------|--------|
| «Rust uwsgi библиотека» в индустрии = **Granian** (явно позиционируется как замена uWSGI) | Берём Granian как ASGI-сервер |
| В коде Granian **нет** gRPC | gRPC — отдельный Rust-слой (tonic + PyO3), не фича Granian |
| Паттерн «FastAPI edge → gRPC stubs» — стандартный gateway | Публичный HTTP/JSON, внутри protobuf |
| У автора есть `vmcp` (Rust gateway + единый typed surface) | Аналогичный принцип: одно API снаружи, fan-out внутри |
| Pure-Python варианты (`grpcio`, `fastapi-grpc-bridge`, FastGRPC) | DX ок, но не «через Rust» и не целевой стек |

---

## Целевая архитектура

```
Клиент (HTTP/JSON)
        │
        ▼
┌──────────────────────────────────────────┐
│ Granian (Rust ASGI, HTTP/1+HTTP/2)       │
│                                          │
│  FastAPI (Python)                        │
│   ├─ обычные routes приложения           │
│   └─ gateway router (бесшовный DX)       │
│           │                              │
│           ▼                              │
│  fastapi_grpc_gateway (Python facade)    │
│           │ PyO3                         │
│           ▼                              │
│  fgg_core (Rust crate)                   │
│   ├─ tonic client / channel pool         │
│   ├─ proto ↔ JSON transcoding            │
│   └─ deadlines / metadata / errors       │
└──────────────────────────────────────────┘
        │ gRPC
        ▼
 Upstream gRPC services
```

**Бесшовность для приложения** значит:

1. Существующий `FastAPI()` не переписывается.
2. Подключение — `app.include_router(...)` или `Gateway.mount(app, ...)`.
3. Хендлеры выглядят как обычные FastAPI endpoints (Pydantic in/out).
4. Запуск: `granian --interface asgi main:app` вместо uvicorn/uwsgi.
5. OpenAPI остаётся источником правды для HTTP-клиента.

---

## Слои и ответственность

### 1. `crates/fgg-core` (Rust)

- `tonic` клиент к upstream gRPC.
- Пул `Channel` (lazy connect, reconnect).
- Transcoding: JSON/path/query → protobuf request; response → JSON bytes.
- Маппинг `tonic::Status` → HTTP status + тело ошибки (Google error model или свой контракт).
- Перенос deadline/metadata из HTTP (`X-Request-Id`, `Authorization`, timeout).
- PyO3 API: `call_unary(service, method, payload_json, metadata) -> bytes`.

### 2. `python/fastapi_grpc_gateway` (Python facade)

- `Gateway` / `GrpcRouter` — тонкая обёртка над Rust-модулем.
- Генерация или регистрация routes из `.proto` + `google.api.http` (если есть) либо из явного mapping YAML/TOML.
- Интеграция: `Depends`, lifespan (init/shutdown пула), middleware-совместимость.
- Типы: Pydantic-модели из proto (codegen) или `dict` + JSON Schema в OpenAPI.

### 3. Сервер: Granian

- Единственный рекомендованный entrypoint для prod.
- `--interface asgi`, workers/runtime-threads по нагрузке.
- HTTP/2 на edge — плюс Granian; gRPC к upstream — отдельно из Rust-ядра.

---

## Бесшовная интеграция в routes

### Вариант A (предпочтительный DX) — декларативный mount

```python
from fastapi import FastAPI
from fastapi_grpc_gateway import GrpcGateway

app = FastAPI()
gw = GrpcGateway.from_proto(
    "protos/users.proto",
    target="dns:///users.svc:50051",
)

# Routes появляются как обычные FastAPI path operations
app.include_router(gw.router, prefix="/api")
```

### Вариант B — явный handler (полный контроль)

```python
@app.get("/users/{user_id}")
async def get_user(user_id: str, grpc=Depends(gw.stub("users.Users/GetUser"))):
    return await grpc({"id": user_id})
```

### Вариант C — гибрид

- codegen из proto → готовые handlers;
- приложение может переопределить любой route без смены транспорта.

**Инвариант:** Python-код приложения не импортирует `grpcio` / stub-файлы напрямую; только facade.

---

## Этапы реализации

### Phase 0 — Каркас репозитория

- Monorepo: `crates/fgg-core`, `python/fastapi_grpc_gateway`, `examples/`, `protos/`, `docs/`.
- `maturin` / `pyproject.toml` для сборки wheel.
- CI: Rust test + Python test + wheel build (manylinux).
- Пример `examples/hello`: FastAPI + Granian + один unary RPC.

### Phase 1 — Минимальный unary path (MVP)

1. Rust: tonic client + `call_unary` через PyO3.
2. Python: lifespan-managed gateway, один `APIRouter` endpoint.
3. Ошибки: `Status` → HTTP 4xx/5xx + JSON.
4. Запуск demo через Granian.
5. Тесты: mock upstream gRPC + TestClient.

**Критерий готовности MVP:** `@app.get` возвращает JSON из реального gRPC unary без `grpcio` в app-коде.

### Phase 2 — Proto → routes codegen

1. Читать `FileDescriptorSet` / `.proto`.
2. Поддержать `google.api.http` annotations (как в tonic-rest / grpc-gateway).
3. Генерировать:
   - Pydantic models;
   - FastAPI route handlers;
   - фрагмент OpenAPI.
4. CLI: `fgg generate --proto ... --out ...`.

### Phase 3 — Production concerns

- Connection pool, keepalive, TLS/mTLS.
- Deadlines из HTTP timeout / `Prefer: wait=`.
- Streaming: server-stream → SSE (HTTP), client-stream — later.
- Observability: tracing span HTTP→gRPC, metrics (latency, status codes).
- Hot reload mapping без рестарта процесса (по аналогии с drift в vmcp) — optional.

### Phase 4 — DX polish

- Документация + cookiecutter example.
- Сравнение latency: grpcio-python stub vs Rust core.
- Optional: reflection-based discovery для dev.

---

## Что сознательно НЕ делаем в MVP

- Не форкаем Granian под gRPC (у него нет gRPC и не нужно).
- Не делаем dual-stack «один порт HTTP+gRPC» в первой версии (сложно с ASGI).
- Не тянем Envoy как обязательную зависимость (можно позже как sidecar).
- Не обещаем full grpc-gateway feature parity сразу (`additional_bindings`, partial body — после MVP).

---

## Структура репозитория (целевая)

```
fastapi-grpc-gateway/
├── Cargo.toml                 # workspace
├── crates/
│   └── fgg-core/              # tonic + PyO3
├── python/
│   └── fastapi_grpc_gateway/  # facade + codegen CLI
├── protos/                    # demo + fixtures
├── examples/
│   └── hello/
│       ├── main.py            # FastAPI app
│       └── run.sh             # granian --interface asgi main:app
├── tests/
├── docs/
│   └── PLAN.md                # этот документ
├── pyproject.toml
└── README.md
```

---

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Async bridge PyO3 ↔ Tokio сложен | Начать с `pyo3-asyncio` / mature pattern; unary first |
| GIL / latency | I/O и protobuf в Rust, GIL отпускать на network |
| Drift proto ↔ routes | Codegen в CI; fail build при рассинхроне |
| Granian workers × shared state | Channel pool per-worker или external pool process |
| Слишком широкий scope | Жёсткий MVP: 1 unary + 1 route + Granian |

---

## Определение «бесшовно» (acceptance)

Приложение считается интегрированным бесшовно, если:

1. Существующие FastAPI routes не ломаются.
2. Новый gRPC-backed endpoint добавляется через `include_router` / `Depends`, без смены фреймворка.
3. Prod-команда запуска — Granian ASGI, без uvicorn/uwsgi.
4. В `requirements` приложения нет прямого `grpcio` (только `fastapi-grpc-gateway` wheel с Rust).
5. OpenAPI показывает те же path/models, что и HTTP-клиент использует.

---

## Следующий шаг после утверждения плана

Реализовать **Phase 0 + Phase 1 MVP**: каркас monorepo, `fgg-core` unary, Python facade с одним route, example под Granian, тесты.
