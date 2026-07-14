# План / границы

Полное описание — в **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**.

## Архитектура

```
HTTP  → Granian embed ─┐
                       ├─► FastAPI (один ASGI app, один процесс)
gRPC  → ASGI adapter ──┘
```

- `fgg serve`: кастомный процесс вокруг Granian embed + gRPC→ASGI
- `fgg generate`: `service.proto` + `bindings.toml`
- `crates/fgg-core`: Rust protocol core (bindings / gRPC frames / mapping)
- Без внешнего HTTP hop (localhost proxy)
- Разработка через **uv** (`uv.lock`, `uv sync --extra dev`)
- Coverage **≥ 93%** для Python и Rust

## В скоупе

JSON unary routes, path/query/body, schema gen, Go/Python gRPC-клиенты,  
`fgg serve` (Granian embed + gRPC→ASGI), Rust `fgg-core`,  
тесты с **coverage ≥ 93%** (Python + Rust).

## Вне скоупа

Cookies, redirects, FileResponse, StreamingResponse, WebSocket.
