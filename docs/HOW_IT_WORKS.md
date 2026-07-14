# Как это работает (просто)

## Одна картинка

Обычное FastAPI-приложение. Один процесс (`fgg serve`) принимает и HTTP, и gRPC:

```
                 ┌──────────────────────────────────────┐
 HTTP клиент ───►│ Granian embed (HTTP)                 │
                 │                                      ├──► FastAPI (ASGI)
 gRPC клиент ───►│ gRPC adapter → ASGI (in-process)     │
                 └──────────────────────────────────────┘
```

**Важно:** gRPC **не** ходит на localhost HTTP.  
Адаптер прямо вызывает тот же ASGI `app(scope, receive, send)`.

---

## Три части

| Часть | Что делает |
|-------|------------|
| Ваше приложение | Обычные FastAPI-роуты |
| `fgg generate` | Смотрит роуты → `service.proto` + `bindings.toml` |
| `fgg serve` | Granian (HTTP) + gRPC→ASGI в одном процессе |

---

## Шаг за шагом: вызов gRPC

Пример: Go-клиент вызывает `GetUser` с `user_id = 7`.

### 1. Клиент шлёт gRPC

```
RPC:  fastapi_grpc.API / GetUser
тело: RpcRequest { path: { "user_id": "7" } }
```

### 2. Сервер смотрит bindings

```toml
[[route]]
rpc = "GetUser"
http_method = "GET"
path = "/api/users/{user_id}"
```

### 3. In-process ASGI

Собирается ASGI scope для `GET /api/users/7` и вызывается ваш хендлер — **без** HTTP-прокси.

### 4. Ответ в gRPC

```
JsonResponse { status_code: 200, body: <JSON> }
```

---

## Как запустить

```bash
uv add fastapi-grpc-gateway
uv run fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen
```

Один процесс:

- HTTP: `http://127.0.0.1:8000`
- gRPC: `127.0.0.1:50051`
- схемы: `./gen/service.proto`, `./gen/bindings.toml`

Только схемы (без сервера):

```bash
fgg generate --app app:app --out ./gen
```

---

## Что писать в приложении

Ничего особенного — обычный FastAPI:

```python
from fastapi import FastAPI, Body
from pydantic import BaseModel

app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"message": "hello"}

@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id}

class Item(BaseModel):
    name: str
    price: float = 0

@app.post("/api/items")
async def create_item(item: Item = Body(...)):
    return item
```

---

## Как вызывать из Go

```go
conn, _ := grpc.Dial("127.0.0.1:50051",
    grpc.WithTransportCredentials(insecure.NewCredentials()))
client := pb.NewAPIClient(conn)

resp, _ := client.GetHello(ctx, &pb.RpcRequest{})
resp, _ := client.GetUser(ctx, &pb.RpcRequest{
    Path: map[string]string{"user_id": "7"},
})
```

Готовый тест: `clients/go/client_test.go` / `bash scripts/test_go_client.sh`.

---

## Чего нет (намеренно)

- Cookies / сессии
- Redirect / File / Streaming ответы
- Отдельный Rust HTTP-прокси на Granian (убрали: был внешний hop)

---

## Файлы

```
fastapi_grpc_gateway/   # generate + serve (Granian embed + gRPC→ASGI)
crates/fgg-core/        # Rust protocol core (bindings / frames / mapping)
examples/hello_app.py
clients/go/
tests/                  # Python unit + e2e; coverage ≥ 93%
scripts/
docs/HOW_IT_WORKS.md
```

---

## Тесты и coverage

```bash
uv sync --extra dev
uv run pytest
bash scripts/test_rust_coverage.sh
```

Пороги:
- Python `fastapi_grpc_gateway`: **≥ 93%** (без `wire_pb2.py`)
- Rust `crates/fgg-core`: **≥ 93%** lines (`cargo llvm-cov --fail-under-lines 93`)

`fgg-core` — protocol core (bindings, gRPC frames, path → HTTP target), без сетевого hop.

Go e2e: `bash scripts/test_go_client.sh`.

---

## Коротко

1. Пишете FastAPI.  
2. `fgg serve` поднимает HTTP (Granian) и gRPC.  
3. gRPC вызывает ASGI **в том же процессе**.  
4. Клиенты ходят по сгенерированному proto.
