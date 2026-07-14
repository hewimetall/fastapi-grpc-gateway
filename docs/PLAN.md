# План: gRPC → convert → `app` (ASGI)

## Модель

```python
app = FastAPI()
app.include_router(router, prefix="/api")
```

Адаптер **не** выбирает handler и **не** держит `methods.json`.  
Он только конвертит gRPC ↔ HTTP и **прокидывает в `app`**; дальше обычный спуск Starlette/FastAPI (routing, Depends, validation).

```
gRPC unary
    │
    ▼
convert → ASGI scope + receive  (method, path, headers, body)
    │
    ▼
app(scope, receive, send)       # сам роутит и исполняет
    │
    ▼
convert ← ASGI response         → gRPC status + message
```

---

## Скоуп

**Да:** JSON/Pydantic unary routes, path/query/body, metadata→headers, peer→`scope["client"]`, status→grpc-status, генерация `.proto` (+ descriptor для runtime server).

**Нет:** cookies, redirects, FileResponse, StreamingResponse, WebSocket, отдельная method-table для диспатча.

---

## Схемы

Генератор из `app.routes` / OpenAPI:

| Артефакт | Зачем |
|----------|--------|
| `.proto` | клиенты, grpcurl, codegen |
| `FileDescriptorSet` | Rust gRPC server (сообщения/сервисы на wire) |

В proto (или options) фиксируется, **как request message раскладывается в HTTP** (path/query/body), чтобы convert был чистой функцией:  
`RPC + message → (http_method, path, headers, body)` без внешнего JSON-маппинга.

Runtime: listener читает descriptor, принимает unary, convert → `app`, convert назад.

CLI:

```bash
fgg generate --app main:app --out ./gen
# gen/service.proto, gen/descriptor.pb
```

---

## Convert (единственная зона ответственности адаптера)

**Вход → ASGI**

- `scope["type"] = "http"`
- `method` / `path` / `query_string` из RPC + message (+ http-binding из descriptor)
- `headers` из gRPC metadata (+ `authorization` и т.п.)
- `client` из `peer()`
- `receive` отдаёт body bytes (JSON из message / уже JSON-поле)

**ASGI → выход**

- status + body из `send`
- JSON body → response message
- HTTP status → `grpc-status` (таблица 2xx→OK, 404→NOT_FOUND, 422→INVALID_ARGUMENT, …)

Диспатч по path — **только** внутри `app`.

---

## Lifespan

1. Routes уже смонтированы.
2. Load prebuilt descriptor **или** сгенерировать из app.
3. Старт Rust unary listener; на каждый call — convert → `await app(...)` → convert.
4. Stop listener.

---

## Этапы

### Phase 0
Один route: руками convert → `app` → ответ; без method table.

### Phase 1
Генерация `.proto` + descriptor; convert читает binding из descriptor.

### Phase 2
Lifespan + Granian (HTTP) + gRPC listener; status map; CLI = runtime gen.

### Phase 3
Cancel/deadline → отмена ASGI task (по желанию).

---

## Acceptance

1. Handlers пишутся как обычный FastAPI; `include_router` без изменений.
2. gRPC call доходит до того же route через **полный** спуск `app`.
3. Адаптер не содержит списка routes / `methods.json`.
4. Есть генерация `.proto` (+ descriptor) из app.
