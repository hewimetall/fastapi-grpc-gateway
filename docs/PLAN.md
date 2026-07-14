# План (реверс): обход FastAPI → gRPC entry

## Желаемая модель

```python
app = FastAPI()
app.include_router(router, prefix="/api")
# lifespan: обойти дерево routes → собрать proto → поднять gRPC entry (как uwsgi)
```

Поток:

```
grpc session → call → (adapter) → FastAPI → (adapter) → session
```

То есть приложение остаётся обычным FastAPI; gRPC — внешняя точка входа, которая прогоняет вызов через тот же app.

---

## ОТВЕТ: почему ЭТО нельзя (нативно)

### 1. У uWSGI / Granian нет gRPC entrypoint

uWSGI говорит **WSGI**. Granian говорит **ASGI/WSGI/RSGI + HTTP/1|/2**.  
Оба принимают HTTP(S)-запросы в модель request/response приложения.

**gRPC session** — это HTTP/2 + protobuf framing + gRPC status/trailers + path вида `/package.Service/Method`.  
Ни uWSGI, ни Granian не предоставляют «grpc session → application» как native plugin.  
Значит «точка входа как делает uwsgi» для gRPC **не существует** в этих серверах: её пришлось бы писать с нуля (отдельный listener), это уже не uwsgi/Granian.

### 2. У FastAPI нет объекта gRPC session

Контракт FastAPI/Starlette:

- `scope["type"] == "http"` (или `websocket`)
- method / path / headers / body
- `Request` / `Response`

Нет:

- gRPC metadata как first-class session
- stream handles / half-close
- trailers / `grpc-status`

Поэтому цепочка никогда не бывает:

```
grpc session → FastAPI → session
```

Она всегда:

```
grpc bytes → (адаптер синтезирует ASGI HTTP) → FastAPI → (адаптер обратно в grpc)
```

Адаптер **обязан** врать FastAPI, что это HTTP. Это не интеграция session, а **перевод протокола**. Без потери семантики это не «прокинуть session».

### 3. ASGI ломает часть gRPC (особенно streaming)

ASGI HTTP **не моделирует HTTP/2 trailers**.  
gRPC status часто уходит в trailers; для streaming это критично.  
Даже unary «натянуть» можно через fake HTTP; streaming через FastAPI ASGI — тупик или кастомный non-ASGI путь (то есть снова мимо FastAPI).

### 4. Дерево FastAPI ≠ дерево proto

Обойти `app.routes` / `iter_route_contexts` / `get_openapi(routes=...)` в lifespan — **можно**.  
Сделать из этого корректный gRPC service — **нельзя без потерь**:

| FastAPI | gRPC |
|---------|------|
| `GET /api/users/{id}` | `Service.Method` + message fields |
| path + query + body + headers | одно request message |
| несколько methods на один path | разные RPC |
| `StreamingResponse`, `File`, `Form`, WebSocket | нет unary-эквивалента |
| HTTP 422 validation | `INVALID_ARGUMENT` (маппинг эвристический) |
| middleware CORS/GZip/Session | на synthetic request бессмысленны или вредны |

OpenAPI→protobuf (генераторы) — lossy/beta.  
`include_router(..., prefix="/api")` даёт HTTP-пути; имена RPC из них — эвристика (`ApiUsersIdGet`), не контракт.

### 5. «Создать proto клиент» в lifespan — путаница роли

Если цель — **принять** gRPC снаружи и вызвать FastAPI, нужен **gRPC server** (servicer), не client.

- Client = исходящие вызовы к чужому gRPC.
- Обход дерева FastAPI даёт **описание нашего HTTP API**, не stub к upstream.

«Proto client из дерева FastAPI» не закрывает задачу entrypoint.  
Нужен server + descriptor (для клиентов снаружи) — это другая сущность.

### 6. Итог одной фразой

**Нельзя**, потому что FastAPI живёт в ASGI/HTTP, а gRPC session — в другом протоколе; uWSGI/Granian не дают gRPC entry; маршрутное дерево HTTP неизоморфно proto; session через FastAPI всегда только через лживый HTTP-адаптер с потерей семантики (trailers/streaming/metadata/status).

Что *можно* (и это уже не «нативно»): отдельный Rust gRPC listener → синтетический ASGI call в `app` → ответ обратно. Это **эмуляция**, не uwsgi-style session passthrough.

---

## Что из желаемого всё же реализуемо (с оговорками)

| Шаг | Статус |
|-----|--------|
| `app = FastAPI(); include_router(...)` без смены DX | да |
| lifespan: walk `app.routes` / OpenAPI | да |
| сгенерировать *эвристический* `.proto` / method map | да, lossy |
| поднять отдельный gRPC unary server (Rust) | да |
| adapter: gRPC unary → fake ASGI Request → `app` → Response → gRPC | да, только unary + JSON/Pydantic routes |
| «как uwsgi» один entry для grpc session | **нет** |
| полный gRPC (stream, trailers, native session) через FastAPI | **нет** |

---

## Реверс-архитектура (если всё же делать эмулятор)

```
[gRPC client]
     │ unary
     ▼
Rust listener (НЕ Granian/uWSGI entry)
     │ map Method → path+HTTP verb (из снимка routes)
     ▼
adapter: protobuf/JSON → ASGI scope + body
     ▼
FastAPI app (тот же, с /api/...)
     ▼
adapter: Response → protobuf + grpc-status
```

Lifespan:

1. Дождаться полного дерева routes (после всех `include_router`).
2. Снять OpenAPI / `APIRoute` list.
3. Построить method table + optional `.proto` dump.
4. Старт Rust unary server с callback «вызови ASGI app».
5. Shutdown — остановить listener.

Ограничить support matrix явно:

- только `APIRoute` с JSON body / Pydantic;
- только unary;
- без WebSocket / File / StreamingResponse;
- middleware, завязанный на реальный HTTP client, не гарантируется.

---

## Вывод для продукта

Целевой DX «обычный FastAPI + в lifespan сам станет gRPC» **нельзя сделать честно** на стеке uWSGI/Granian/ASGI.

Честные варианты:

1. **Эмулятор** (адаптер выше) — «похоже», но не session passthrough.
2. **Отдельные gRPC handlers** (стиль jsonrpc) — честный RPC, другой DX.
3. **Не FastAPI на hot path** — Rust/tonic servicer, FastAPI только HTTP.

Рекомендация: не продавать (1) как «точку входа как uwsgi»; если нужен именно обход дерева FastAPI — делать (1) с жёстким unary-only и документированными потерями.
