# План: gRPC methods для FastAPI (DX как fastapi-jsonrpc)

## Уточнённая цель

**Не** HTTP→gRPC gateway / не транскодинг REST в protobuf.

**Да** — тот же паттерн, что у [`fastapi-jsonrpc`](https://github.com/smagafurov/fastapi-jsonrpc):

- пишешь обычные Python-функции (Pydantic, `Body`, `Depends`);
- регистрируешь их декоратором как RPC-методы;
- транспорт и диспатч — в Rust (аналог «uwsgi»-слоя → **Granian-подобный** runtime);
- для приложения бесшовно: тот же стиль, что JSON-RPC entrypoint.

Полная поддержка gRPC **не нужна** (без streaming, reflection, grpc-gateway annotations, dual-stack magic).

---

## Референс: fastapi-jsonrpc

```python
import fastapi_jsonrpc as jsonrpc
from fastapi import Body

app = jsonrpc.API()
api_v1 = jsonrpc.Entrypoint('/api/v1/jsonrpc')

@api_v1.method()
def echo(data: str = Body(..., examples=['hello'])) -> str:
    return data

app.bind_entrypoint(api_v1)
```

Суть модели:

| JSON-RPC | Наш gRPC-аналог |
|----------|-----------------|
| `API()` | `API()` / mount в существующий FastAPI |
| `Entrypoint('/path')` | `Service('package.Service')` |
| `@entrypoint.method()` | `@service.method()` |
| `POST /jsonrpc` + JSON body | gRPC unary на отдельном порту (Rust) |
| OpenAPI/OpenRPC | опционально proto/descriptor для клиентов |
| `Depends` / `Body` / ошибки | то же |

Метод — это **Python handler**, а не proxy на чужой gRPC upstream.

---

## Целевой DX

```python
import fastapi_grpc as grpc
from fastapi import Body, Depends
from pydantic import BaseModel

app = grpc.API()          # совместим с обычным FastAPI-поверхностью
svc = grpc.Service("demo.Greeter")

class HelloReply(BaseModel):
    message: str

@svc.method()
async def say_hello(name: str = Body(...)) -> HelloReply:
    return HelloReply(message=f"Hello, {name}")

app.bind_service(svc)

# HTTP (docs / health) — Granian ASGI
# gRPC unary     — Rust listener, вызывает зарегистрированные Python methods
```

Бесшовность:

1. Те же `Body` / `Depends` / Pydantic / async, что в FastAPI и fastapi-jsonrpc.
2. Обычные HTTP routes приложения не ломаются.
3. Запуск: Granian для ASGI + Rust gRPC port из того же процесса (или рядом через embed API).

---

## Архитектура (минимальная)

```
gRPC client                    HTTP client
    │                              │
    ▼                              ▼
┌────────────────┐         ┌─────────────────┐
│ Rust gRPC      │         │ Granian ASGI    │
│ unary server   │         │ (HTTP docs etc) │
│ (tonic)        │         └────────┬────────┘
└───────┬────────┘                  │
        │ PyO3 callback             │
        ▼                           ▼
   Method registry  ←── FastAPI / grpc.API (Python)
   (@svc.method handlers)
```

**Rust делает только:**

- слушает gRPC (HTTP/2 + protobuf framing);
- маппит `service/method` → зарегистрированный Python callable;
- сериализует request/response (простой JSON↔proto или protobuf с автоген из сигнатур — см. ниже);
- возвращает unary status/errors.

**Rust НЕ делает:** streaming, full codegen gateway, Envoy, google.api.http.

---

## Сериализация (осознанно простая)

Для MVP достаточно одного из двух (выбрать на Phase 0 spike):

1. **Proto-lite / JSON payload в bytes** — метод принимает/отдаёт Pydantic; на wire — protobuf-обёртка `{json: bytes}` или raw JSON encoding (как многие внутренние RPC). Минимум tooling.
2. **Авто-proto из Pydantic** — при `bind_service` строить descriptor (имя сервиса + message из моделей). Клиентам нужен `.proto` export.

Рекомендация MVP: **вариант 1** (быстрее), экспорт `.proto` — Phase 2.

---

## Объём MVP (что входит / что нет)

### Входит

- `API`, `Service`, `@method()`, `bind_service`
- Unary call only
- Pydantic in/out + `Body` / `Depends`
- Typed errors → gRPC status (+ optional details)
- Rust unary server + PyO3 dispatch
- Granian для HTTP-части приложения
- Example + тесты (grpcurl или tonic client)

### Не входит

- Client streaming / server streaming / bidi
- gRPC reflection (можно позже одной галкой)
- HTTP/JSON transcoding, grpc-gateway annotations
- Конвертация существующих `@app.get` HTTP handlers в gRPC
- Полная совместимость с произвольными `.proto` от третьих сторон (сначала «наши» методы)

---

## Этапы

### Phase 0 — Spike (1 тонкий вертикальный срез)

1. Разобрать регистрацию методов в fastapi-jsonrpc (`Entrypoint.method`, dependency solving).
2. Rust: minimal tonic unary + callback в Python (PyO3).
3. Один `@svc.method()` echo end-to-end через grpcurl.

### Phase 1 — Python facade как jsonrpc

1. Портировать DX: `API` / `Service` / `@method` / `bind_service`.
2. Dependency injection через FastAPI/Starlette solve (переиспользовать подход jsonrpc).
3. Error model: `BaseError` → gRPC status code.
4. Документация: «если умеешь fastapi-jsonrpc — умеешь это».

### Phase 2 — DX + wire polish

1. Export `.proto` / FileDescriptor для клиентов.
2. Metadata → `Header`-подобные Depends.
3. Опционально reflection для dev.

### Phase 3 — Runtime

1. Один процесс: Granian ASGI + Rust gRPC listener (embed).
2. Lifecycle: start/stop вместе с app lifespan.
3. Базовые метрики/логи method name + latency.

---

## Структура репо

```
fastapi-grpc-gateway/
├── crates/fgg-runtime/     # tonic unary + PyO3 dispatch
├── python/fastapi_grpc/    # API, Service, @method (зеркало jsonrpc)
├── examples/echo/
├── tests/
├── docs/PLAN.md
└── pyproject.toml          # maturin
```

Имя пакета Python: `fastapi_grpc` (зеркало `fastapi_jsonrpc`).  
Имя репо можно оставить; в README явно: **server-side methods**, не gateway-proxy.

---

## Acceptance

1. Пример из README копипастится и отвечает на unary gRPC call.
2. Handler пишется как jsonrpc-method (не как REST route и не как grpcio stub).
3. Нет зависимости приложения от ручных `*_pb2.py` в MVP.
4. HTTP routes FastAPI продолжают работать через Granian.
5. Нет streaming / transcoding в scope.

---

## Следующий шаг

Phase 0 spike: echo unary Rust→Python + скелет `Service.method` по образцу fastapi-jsonrpc.
