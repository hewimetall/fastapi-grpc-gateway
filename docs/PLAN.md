# План / границы

Полное описание — в **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**.

## Архитектура

```
HTTP  → Granian (Python) → FastAPI
gRPC  → fgg-worker (Rust) → HTTP → Granian → FastAPI
```

- Python: schema + Granian orchestrator — **без** `import grpc` / grpcio
- Rust `fgg-worker` / `fgg-core`: весь gRPC
- Coverage **≥ 93%** для Python и Rust `fgg-core`

## В скоупе

JSON unary routes, path/query/body, schema gen, Go gRPC-клиенты,  
`fgg serve`, Rust worker.

## Вне скоупа

Cookies, redirects, FileResponse, StreamingResponse, WebSocket,  
Python gRPC (`grpcio`).
