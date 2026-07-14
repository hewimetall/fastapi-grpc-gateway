# Как поставить пакет и как публиковать

## В свой проект

```bash
pip install fastapi-grpc-gateway
```

В `pyproject.toml`:

```toml
dependencies = [
  "fastapi-grpc-gateway>=0.2.0",
]
```

Если на PyPI ещё нет — с GitHub Release:

```bash
pip install \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.2.0/fastapi_grpc_gateway-0.2.0-py3-none-any.whl
```

### Дальше

```bash
fgg serve --app app:app --http-port 8000 --grpc-bind 127.0.0.1:50051 --out ./gen
```

Отдельный бинарник `fgg-worker` больше не нужен — gRPC и HTTP в одном `fgg serve`.

Для разработки: `pip install -e ".[dev]" && pytest` (coverage ≥ 93%).

---

## Как выложить релиз

1. Версия в `pyproject.toml` (`version = "0.2.0"`).
2. Тег с той же версией:

```bash
git tag v0.2.0
git push origin v0.2.0
```

3. Workflow [`.github/workflows/python-release.yml`](../.github/workflows/python-release.yml):
   - `.whl` + sdist
   - **GitHub Release**
   - **PyPI** (Trusted Publishing; если не настроено — шаг может упасть, Release всё равно будет)

### Один раз: PyPI Trusted Publishing

1. https://pypi.org → Publishing → pending publisher
2. Owner `hewimetall`, repo `fastapi-grpc-gateway`, workflow `python-release.yml`, environment `pypi`
3. GitHub → Settings → Environments → **`pypi`**

### Dry-run

Actions → **Release** → Run workflow → `dry_run: true`.
