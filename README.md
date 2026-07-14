# fastapi-grpc-gateway

Делает так, чтобы к обычному FastAPI можно было ходить ещё и по **gRPC**.

```
HTTP  → Granian → FastAPI
gRPC  → Rust worker → (тот же) Granian → FastAPI
```

FastAPI остаётся обычным. Worker только переводит gRPC в HTTP.

**Как это работает:** [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)

---

## С чего начать (без локальной сборки)

Ставите готовые пакеты из релиза / PyPI — **не нужно** `cargo build` и `pip install -e .`.

### 1. Python-пакет

```bash
pip install fastapi-grpc-gateway granian
```

Если на PyPI ещё нет (первый релиз / Trusted Publisher не настроен) — с GitHub Release:

```bash
pip install \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.1.0/fastapi_grpc_gateway-0.1.0-py3-none-any.whl
```

### 2. Бинарник worker

```bash
curl -sL -o fgg-worker \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.1.0/fgg-worker-x86_64-unknown-linux-gnu
chmod +x fgg-worker
```

### 3. Ваше FastAPI-приложение

```python
# app.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"message": "hello"}
```

### 4. Схемы + два процесса

```bash
# схемы из ваших роутов
fgg generate --app app:app --out ./gen

# терминал A — HTTP
granian --interface asgi --host 127.0.0.1 --port 8000 app:app

# терминал B — gRPC
./fgg-worker \
  --bind 127.0.0.1:50051 \
  --upstream http://127.0.0.1:8000 \
  --bindings ./gen/bindings.toml
```

Проверка: `curl http://127.0.0.1:8000/api/hello`

Подробнее про установку и релизы: [docs/PUBLISHING.md](docs/PUBLISHING.md)

---

## Кто за что отвечает

| Компонент | Откуда брать | Роль |
|-----------|--------------|------|
| `fastapi-grpc-gateway` | `pip install` / PyPI / Release `.whl` | `fgg generate` → proto + bindings |
| `fgg-worker` | GitHub Release (бинарник) | gRPC → HTTP |
| `granian` | `pip install granian` | HTTP для FastAPI |
| ваше `app.py` | вы | обычные FastAPI-роуты |

---

## Для контрибьюторов (сборка из исходников)

```bash
pip install -e ".[dev]"
cargo build -p fgg-worker
pytest
bash scripts/test_go_client.sh
```

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | pip / PyPI / Releases |
| [docs/PLAN.md](docs/PLAN.md) | Скоуп |
