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
- Без внешнего HTTP hop (localhost proxy)

## В скоупе

JSON unary routes, path/query/body, schema gen, Go/Python gRPC-клиенты.

## Вне скоупа

Cookies, redirects, FileResponse, StreamingResponse, WebSocket.
