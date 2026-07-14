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

```bash
pip install fastapi-grpc-gateway
```

Если на PyPI ещё нет — с GitHub Release:

```bash
pip install \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.2.0/fastapi_grpc_gateway-0.2.0-py3-none-any.whl
```

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
fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen
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

```bash
pip install -e ".[dev]"
pytest
bash scripts/test_go_client.sh
```

`pytest` гоняет unit/e2e и **требует coverage ≥ 93%** (`--cov-fail-under=93`).  
Порог задан в `pyproject.toml` (`tool.coverage.report.fail_under`). Сгенерированный `wire_pb2.py` из покрытия исключён.

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | pip / PyPI / Releases |
| [docs/PLAN.md](docs/PLAN.md) | Скоуп |
