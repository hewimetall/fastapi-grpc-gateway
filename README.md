# fastapi-grpc-gateway

Делает так, чтобы к обычному FastAPI можно было ходить ещё и по **gRPC**.

```
HTTP  → Granian → FastAPI
gRPC  → Rust worker → (тот же) Granian → FastAPI
```

FastAPI остаётся обычным. Worker только переводит gRPC в HTTP.

---

## С чего начать

**Прочитайте:** [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — простым языком: схема, шаги, примеры.

## За 30 секунд

```bash
pip install -e ".[dev]"
cargo build -p fgg-worker

# 1) сгенерировать схемы из FastAPI-роутов
PYTHONPATH=examples fgg generate --app hello_app:app --out ./gen

# 2) HTTP
cd examples && granian --interface asgi --host 127.0.0.1 --port 8000 hello_app:app

# 3) gRPC worker (другой терминал)
./target/debug/fgg-worker \
  --bind 127.0.0.1:50051 \
  --upstream http://127.0.0.1:8000 \
  --bindings ./gen/bindings.toml
```

Проверка:

- HTTP: `curl http://127.0.0.1:8000/api/hello`
- gRPC (Go): `bash scripts/test_go_client.sh`

Или одной командой: `bash scripts/run_example.sh`

---

## Кто за что отвечает

| Компонент | Роль |
|-----------|------|
| `examples/hello_app.py` | Ваше FastAPI-приложение |
| `fgg generate` | Пишет `gen/service.proto` + `gen/bindings.toml` |
| Granian | HTTP-сервер для FastAPI |
| `fgg-worker` | gRPC-сервер → HTTP на Granian |
| `clients/go` | Пример официального Go gRPC-клиента |

---

## Тесты

```bash
cargo build -p fgg-worker
pip install -e ".[dev]"
pytest                          # schema + python e2e
bash scripts/test_go_client.sh  # Go grpc-go клиент
```

## Сборка Python wheel

Локально:

```bash
pip install build
python -m build
# → dist/fastapi_grpc_gateway-*.whl
```

CI: [`.github/workflows/python-wheel.yml`](.github/workflows/python-wheel.yml) собирает `.whl` / sdist и кладёт в Artifacts.

---

## Документация

| Файл | Содержание |
|------|------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Как работает, простыми словами |
| [docs/PLAN.md](docs/PLAN.md) | Краткий план / границы скоупа |
