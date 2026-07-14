# План: gRPC entry → FastAPI (unary JSON)

## Скоуп (зафиксировано)

Обычное приложение:

```python
app = FastAPI()
app.include_router(router, prefix="/api")
```

В lifespan: снимок routes → proto/method map → gRPC entry (Rust).

Поток:

```
grpc session → adapter → FastAPI (DI / route handler) → adapter → session
```

**Вне скоупа (не поддерживаем, не обсуждаем):**
cookies / SessionMiddleware, `RedirectResponse`, `FileResponse`, `StreamingResponse`, WebSocket.

**В скоупе:** JSON/Pydantic unary routes, `Depends`, path/query/body, metadata→headers, статус→grpc-status.

---

## Почему это уже можно

После выкидывания HTTP-only фич адаптер = тот же класс задач, что FastStream:

1. gRPC peer/metadata → ASGI `scope` (`client`, `headers`, `path`, `method`, body).
2. Вызов handler через FastAPI DI (`solve_dependencies` + `run_endpoint_function`) **или** полный ASGI на один route.
3. Response body (JSON/Pydantic) → protobuf/JSON payload; HTTP status → `grpc-status`.

`request.client.host` и auth header — заполняются в адаптере из session/peer/metadata. Это не блокер.

---

## Архитектура

```
gRPC client (unary)
        │
        ▼
Rust listener (отдельный порт; не uWSGI/Granian entry)
        │ method → (http_method, path, body mapping)
        ▼
Python adapter
        │ synthetic Request / ASGI call
        ▼
FastAPI app (существующие routes под /api/...)
        │
        ▼
adapter → gRPC response
```

HTTP docs/health по-прежнему через Granian ASGI.  
gRPC — соседний listener в том же процессе (lifespan start/stop).

---

## Lifespan

1. После монтирования всех router'ов обойти `app.routes` / `iter_route_contexts` / OpenAPI.
2. Оставить только поддерживаемые `APIRoute` (JSON in/out, без file/stream/redirect).
3. Построить method table + сгенерировать `.proto` (эвристика имён).
4. Старт Rust unary server с callback в Python adapter.
5. Shutdown — stop listener.

---

## Маппинг (минимальный контракт)

| FastAPI | gRPC |
|---------|------|
| `GET /api/users/{id}` | `Api.GetUsersId` + field `id` |
| query/body → message fields | по OpenAPI parameters |
| `200` + JSON | `OK` + message |
| `4xx/5xx` + `detail` | status + optional error payload |
| `Authorization` metadata | `Authorization` header в scope |

Имена RPC и package — конфиг/конвенция (не claim «идеальный proto»).

---

## Этапы

### Phase 0 — Spike
Один существующий `@app.get` JSON → unary gRPC через adapter; peer в `request.client`.

### Phase 1
Lifespan walk routes → method table; несколько routes + path params; status map.

### Phase 2
Export `.proto`; Rust listener + Granian в одном процессе; ошибки validation → `INVALID_ARGUMENT`.

### Phase 3
Deadline/cancel → `asyncio.Task` cancel (если нужно).

---

## Acceptance

1. `app = FastAPI(); include_router(...)` без смены DX handlers.
2. Unary gRPC вызывает тот же handler, что HTTP (JSON).
3. Нет cookies/redirect/file/stream в support matrix.
4. Неподдерживаемый route либо не попадает в proto, либо явный reject при старте.
