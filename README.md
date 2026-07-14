# fastapi-grpc-gateway

Обычный FastAPI (`include_router`) + идея gRPC entry через обход дерева в lifespan.

**Короткий вывод:** нативно `grpc session → FastAPI` через uWSGI/Granian **нельзя** — разбор в [`docs/PLAN.md`](docs/PLAN.md).
