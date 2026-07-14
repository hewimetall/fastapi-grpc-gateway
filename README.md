# fastapi-grpc-gateway

Обычный FastAPI — ещё и по **gRPC**, в одном процессе с Granian.

```
HTTP  → Granian embed ─┐
                       ├─► FastAPI (один ASGI app)
gRPC  → ASGI adapter ──┘   (без localhost HTTP hop)
```

**Как это работает:** [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)

---

## С чего начать

С [uv](https://docs.astral.sh/uv/):

```bash
uv add fastapi-grpc-gateway
# или пока только с Release:
uv add 'fastapi-grpc-gateway @ https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.2.0/fastapi_grpc_gateway-0.2.0-py3-none-any.whl'
```

Через pip тоже можно: `pip install fastapi-grpc-gateway`.

### Приложение

```python
# app.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"message": "hello"}
```

### Один процесс

```bash
uv run fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen
```

- HTTP: `curl http://127.0.0.1:8000/api/hello`
- gRPC: порт `50051`, контракт в `./gen/service.proto`

Подробнее: [docs/PUBLISHING.md](docs/PUBLISHING.md)

---

## Кто за что отвечает

| Компонент | Роль |
|-----------|------|
| `fgg serve` | Granian (HTTP) + gRPC→ASGI in-process |
| `fgg generate` | только proto + bindings |
| ваше `app.py` | обычные FastAPI-роуты |

---

## Для контрибьюторов

Нужен [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync --extra dev
uv run pytest
bash scripts/test_go_client.sh
```

`uv.lock` и `.python-version` зафиксированы в репо.

`pytest` требует coverage **≥ 93%** (`--cov-fail-under=93`).  
`wire_pb2.py` из покрытия исключён.

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | uv / pip / PyPI / Releases |
| [docs/PLAN.md](docs/PLAN.md) | Скоуп |
