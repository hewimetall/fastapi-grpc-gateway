# Как поставить пакет и как публиковать

## В свой проект (без сборки)

### Python

```bash
pip install fastapi-grpc-gateway granian
```

В `pyproject.toml`:

```toml
dependencies = [
  "fastapi-grpc-gateway>=0.1.0",
  "granian>=1.6.0",
]
```

Если на PyPI ещё нет — с GitHub Release:

```bash
pip install \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.1.0/fastapi_grpc_gateway-0.1.0-py3-none-any.whl
```

### Rust worker (бинарник)

```bash
curl -sL -o fgg-worker \
  https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.1.0/fgg-worker-x86_64-unknown-linux-gnu
chmod +x fgg-worker
```

Wheel **не** содержит `fgg-worker` — это отдельный файл в Release.

### Дальше

```bash
fgg generate --app app:app --out ./gen
granian --interface asgi --host 127.0.0.1 --port 8000 app:app
./fgg-worker --bind 127.0.0.1:50051 --upstream http://127.0.0.1:8000 --bindings ./gen/bindings.toml
```

---

## Как выложить релиз

1. Версия в `pyproject.toml` (`version = "0.1.0"`).
2. Тег с той же версией:

```bash
git tag v0.1.0
git push origin v0.1.0
```

3. Workflow [`.github/workflows/python-release.yml`](../.github/workflows/python-release.yml):
   - `.whl` + sdist
   - бинарник `fgg-worker-x86_64-unknown-linux-gnu`
   - **GitHub Release** со всеми файлами
   - **PyPI** (Trusted Publishing; если не настроено — шаг может упасть, Release всё равно будет)

### Один раз: PyPI Trusted Publishing

1. https://pypi.org → Publishing → pending publisher
2. Owner `hewimetall`, repo `fastapi-grpc-gateway`, workflow `python-release.yml`, environment `pypi`
3. GitHub → Settings → Environments → **`pypi`**

### Dry-run

Actions → **Release** → Run workflow → `dry_run: true`.
