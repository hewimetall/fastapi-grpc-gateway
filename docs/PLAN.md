# План / границы

Полное описание — в **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**.

## Архитектура

```
HTTP  → granian | uvicorn | gunicorn+uvicorn → FastAPI
gRPC  → fgg-worker (Rust) → HTTP → upstream → FastAPI
```

- Python: schema + HTTP orchestrator — **без** `import grpc` / grpcio
- `--http-backend`: `granian` (default) / `uvicorn` / `gunicorn`
- Rust `fgg-worker` / `fgg-core`: весь gRPC
- Coverage **≥ 93%** для Python и Rust `fgg-core`

## В скоупе

JSON unary routes, path/query/body, schema gen, Go gRPC-клиенты,  
`fgg serve`, Rust worker.

## Вне скоупа

Cookies, redirects, FileResponse, StreamingResponse, WebSocket,  
Python gRPC (`grpcio`).
