# План / границы

Полное описание — в **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**.

## Архитектура

```
gRPC → fgg-worker (Rust) → HTTP → Granian → FastAPI
```

- Python: только генерация `service.proto` + `bindings.toml`
- Rust worker: convert + proxy
- Granian: ASGI для приложения

## В скоупе

JSON unary routes, path/query/body, schema gen, Go/Python gRPC-клиенты.

## Вне скоупа

Cookies, redirects, FileResponse, StreamingResponse, WebSocket.
