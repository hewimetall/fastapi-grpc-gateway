# Как поставить пакет и как публиковать

## Как притащить в свой проект

### После публикации в PyPI (тег `v*`)

```bash
pip install fastapi-grpc-gateway
```

В `pyproject.toml`:

```toml
dependencies = [
  "fastapi-grpc-gateway>=0.1.0",
]
```

### Пока не в PyPI / для разработки

```bash
# из git
pip install "git+https://github.com/hewimetall/fastapi-grpc-gateway.git@main"

# с GitHub Release (после тега)
pip install https://github.com/hewimetall/fastapi-grpc-gateway/releases/download/v0.1.0/fastapi_grpc_gateway-0.1.0-py3-none-any.whl
```

Rust-бинарник `fgg-worker` в wheel **не входит** — его ставят отдельно (`cargo build -p fgg-worker` или свой релиз).

---

## Как выложить релиз

1. Подними версию в `pyproject.toml` (`version = "0.1.0"`).
2. Закоммить и поставь тег **с той же версией**:

```bash
git tag v0.1.0
git push origin v0.1.0
```

3. Workflow [`.github/workflows/python-release.yml`](../.github/workflows/python-release.yml) сам:
   - соберёт `.whl` + sdist
   - создаст **GitHub Release** и прикрепит файлы
   - отправит пакет в **PyPI** (Trusted Publishing)

### Один раз настроить PyPI Trusted Publishing

1. Зайди на https://pypi.org → Manage → Publishing → **Add a new pending publisher**
2. Укажи:
   - Owner: `hewimetall`
   - Repository: `fastapi-grpc-gateway`
   - Workflow: `python-release.yml`
   - Environment: `pypi`
3. В GitHub репо: Settings → Environments → создай environment **`pypi`** (можно без protection rules).

После первого успешного тега: `pip install fastapi-grpc-gateway`.

### Dry-run

В Actions → **Release Python package** → Run workflow → `dry_run: true` — только сборка, без публикации.
