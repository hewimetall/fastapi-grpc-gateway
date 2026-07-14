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

**В скоупе:** JSON/Pydantic unary routes, `Depends`, path/query/body, metadata→headers, статус→grpc-status, **генерация схем**.

---

## Генерация схем

Источник правды — дерево FastAPI (`app.routes` / OpenAPI). Схемы нужны клиентам и Rust listener’у.

### Что генерируем

| Артефакт | Зачем |
|----------|--------|
| `.proto` (services + messages) | grpcurl, codegen клиентов (Go/TS/Python) |
| `FileDescriptorSet` (`.pb` / bytes) | runtime reflection-lite / динамический servicer в Rust |
| method map JSON (`operationId` → path, method, params) | адаптер без парсинга proto |
| (опц.) OpenAPI slice только gRPC-exposed routes | единый HTTP+gRPC каталог в docs |

### Когда

1. **Offline CLI** (CI / pre-commit):
   ```bash
   fgg generate --app main:app --out ./gen
   # → gen/service.proto, gen/descriptor.pb, gen/methods.json
   ```
2. **Lifespan runtime**: тот же генератор при старте (если нет prebuilt), либо загрузка `descriptor.pb` с диска.
3. **HTTP endpoint** (опц.): `GET /grpc/schema.proto` / `GET /grpc/descriptor.pb` для клиентов.

### Правила генерации (JSON-only)

- Один `APIRoute` → один unary RPC.
- Path/query/body params → request message fields (Pydantic / OpenAPI schema).
- `response_model` / 200 schema → response message.
- Имя RPC: `generate_unique_id` / `operationId` / конвенция `MethodPath` (конфиг).
- Package/service: из settings (`package=app.api`, `service=Api`).
- Route вне support matrix — skip + warning (или `--strict` fail).

### DX

```python
from fastapi_grpc_gateway import GrpcGateway

gw = GrpcGateway(app)          # или mount в lifespan
gw.export_proto("gen/api.proto")
gw.export_descriptor("gen/api.pb")
```

CLI и runtime API должны давать **бит-идентичный** результат на одном и том же `app`.

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
3. Прогнать schema generator → method table + `.proto` / descriptor (или загрузить prebuilt из CLI).
4. Старт Rust unary server с callback в Python adapter (+ отдать descriptor клиентам при необходимости).
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
Один `@app.get` JSON → unary gRPC; peer в `request.client`; ручной proto ок.

### Phase 1 — Schema gen
CLI + API: `app` → `.proto` + `methods.json` + descriptor; несколько routes / path params; skip unsupported.

### Phase 2 — Runtime
Lifespan грузит/генерит схемы; Rust listener + Granian; validation → `INVALID_ARGUMENT`; опц. `GET /grpc/schema.proto`.

### Phase 3
Deadline/cancel; стабильные имена RPC (snapshot tests на gen/).

---

## Acceptance

1. `app = FastAPI(); include_router(...)` без смены DX handlers.
2. Unary gRPC вызывает тот же handler, что HTTP (JSON).
3. `fgg generate` / `gw.export_proto` даёт `.proto` (+ descriptor) из routes.
4. CLI и lifespan-gen совпадают на одном app.
5. Нет cookies/redirect/file/stream в support matrix; unsupported → skip или `--strict` fail.
