# Как это работает (просто)

## Одна картинка

У вас обычное FastAPI-приложение. Клиенты могут ходить на него **двумя способами**:

1. **HTTP** — как обычно (браузер, curl, фронт)
2. **gRPC** — через отдельный Rust-процесс

```
                    ┌─────────────────────┐
   HTTP клиент ───► │ Granian :8000       │──► FastAPI (ваши @app.get / @app.post)
                    └─────────────────────┘
                              ▲
                              │ обычный HTTP
                              │
                    ┌─────────────────────┐
   gRPC клиент ───► │ fgg-worker :50051   │  (Rust)
                    │  gRPC → HTTP        │
                    └─────────────────────┘
```

**Важно:** FastAPI ничего не знает про gRPC.  
Worker просто **переводит** gRPC-вызов в обычный HTTP-запрос и шлёт его на Granian.

---

## Три части проекта

| Часть | Язык | Что делает |
|-------|------|------------|
| Ваше приложение | Python / FastAPI | Пишете роуты как обычно |
| `fgg generate` | Python (маленький) | Смотрит на роуты и пишет файлы-схемы |
| `fgg-worker` | Rust | Слушает gRPC и проксирует в HTTP |
| Granian | Rust-сервер для Python | Поднимает FastAPI по HTTP |

Python **не** крутит gRPC. Он только генерирует описание API.

---

## Шаг за шагом: что происходит при вызове

Пример: Go-клиент вызывает `GetUser` с `user_id = 7`.

### 1. Клиент шлёт gRPC

```
RPC:  fastapi_grpc.API / GetUser
тело: RpcRequest { path: { "user_id": "7" } }
```

Попадает в **fgg-worker** на порт `50051`.

### 2. Worker смотрит в `bindings.toml`

Там заранее записано:

```toml
[[route]]
rpc = "GetUser"
http_method = "GET"
path = "/api/users/{user_id}"
```

Значит: это `GET /api/users/7`.

### 3. Worker делает обычный HTTP

```
GET http://127.0.0.1:8000/api/users/7
```

Запрос принимает **Granian**, дальше отрабатывает ваш FastAPI-хендлер:

```python
@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id, "name": f"user-{user_id}"}
```

### 4. Ответ обратно в gRPC

HTTP `200` + JSON `{"user_id": 7, "name": "user-7"}`  
упаковывается в:

```
JsonResponse {
  status_code: 200,
  body: <байты JSON>
}
```

и уходит gRPC-клиенту.

---

## Откуда берутся схемы

Команда:

```bash
PYTHONPATH=examples fgg generate --app hello_app:app --out ./gen
```

Читает FastAPI-приложение и создаёт два файла:

### `gen/service.proto`

Контракт для клиентов (Go, Python, grpcurl…).  
Каждый HTTP-роут → один gRPC method.

Пример:

```protobuf
service API {
  rpc GetHello (RpcRequest) returns (JsonResponse);
  rpc GetUser (RpcRequest) returns (JsonResponse);
  rpc PostCreateItem (RpcRequest) returns (JsonResponse);
}
```

Общие сообщения:

- `RpcRequest` — path-параметры, query, JSON-body
- `JsonResponse` — HTTP status + тело ответа + headers

### `gen/bindings.toml`

Шпаргалка **только для Rust-worker**: какой RPC = какой HTTP.

```toml
[[route]]
rpc = "GetUser"
http_method = "GET"
path = "/api/users/{user_id}"
```

Без этого файла worker не знает, куда проксировать.

---

## Как запустить локально

Нужны **два процесса** (как nginx + приложение).

### Терминал A — FastAPI через Granian

```bash
pip install -e ".[dev]"
cd examples
granian --interface asgi --host 127.0.0.1 --port 8000 hello_app:app
```

Проверка: `curl http://127.0.0.1:8000/api/hello`

### Терминал B — схемы + Rust worker

```bash
# один раз
cargo build -p fgg-worker
PYTHONPATH=examples fgg generate --app hello_app:app --out ./gen

# старт worker
./target/debug/fgg-worker \
  --bind 127.0.0.1:50051 \
  --upstream http://127.0.0.1:8000 \
  --bindings ./gen/bindings.toml
```

### Клиент

- HTTP: `curl http://127.0.0.1:8000/api/hello`
- gRPC (Go-тест): `bash scripts/test_go_client.sh`

Или всё сразу: `bash scripts/run_example.sh`

---

## Что писать в приложении

Ничего особенного. Обычный FastAPI:

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

После изменения роутов снова запустите `fgg generate` и перезапустите worker.

---

## Как вызывать из Go

```go
conn, _ := grpc.Dial("127.0.0.1:50051",
    grpc.WithTransportCredentials(insecure.NewCredentials()))
client := pb.NewAPIClient(conn)

// GET /api/hello
resp, _ := client.GetHello(ctx, &pb.RpcRequest{})

// GET /api/users/7
resp, _ := client.GetUser(ctx, &pb.RpcRequest{
    Path: map[string]string{"user_id": "7"},
})

// POST /api/items
body, _ := json.Marshal(map[string]any{"name": "x", "price": 1.5})
resp, _ := client.PostCreateItem(ctx, &pb.RpcRequest{Body: body})

fmt.Println(resp.StatusCode, string(resp.Body))
```

Готовый тест: `clients/go/client_test.go`.

---

## Чего нет (намеренно)

- Cookies / сессии
- Redirect / File / Streaming ответы
- Worker **не** исполняет Python внутри себя — только HTTP-прокси
- Нет «магии» внутри FastAPI: gRPC снаружи, HTTP внутри

---

## Файлы в репозитории

```
fastapi_grpc_gateway/   # Python: generate schema
crates/fgg-worker/      # Rust: gRPC → HTTP
examples/hello_app.py   # демо FastAPI
clients/go/             # Go-клиент + тесты
scripts/
  run_example.sh        # поднять всё
  test_go_client.sh     # e2e с Go
docs/
  HOW_IT_WORKS.md       # этот файл
```

---

## Коротко

1. Пишете FastAPI.  
2. `fgg generate` делает `.proto` и `bindings.toml`.  
3. Granian отдаёт HTTP.  
4. `fgg-worker` принимает gRPC и дергает тот же HTTP.  
5. Клиенты (Go и др.) ходят по сгенерированному proto.
