# План: Rust worker + Granian + минимальный Python

## Модель

```
gRPC unary
    │
    ▼
fgg-worker (Rust)     # convert gRPC → HTTP
    │
    ▼
Granian ASGI          # HTTP server
    │
    ▼
FastAPI app           # обычный спуск routes
```

Python **минимален**: только обход `app.routes` → `service.proto` + `bindings.toml`.

## Артефакты `fgg generate`

| Файл | Кто читает |
|------|------------|
| `service.proto` | клиенты / grpcurl codegen |
| `bindings.toml` | Rust worker (rpc → method/path) |

Wire: общий `RpcRequest` / `JsonResponse` (path/query/body maps) — worker app-agnostic.

## Запуск

1. `granian --interface asgi hello_app:app`
2. `fgg-worker --upstream http://127.0.0.1:8000 --bindings gen/bindings.toml`

## Скоуп

JSON unary routes. Без cookies / redirects / File / Streaming.
