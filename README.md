# fastapi-grpc-gateway

gRPC unary → **convert** → `app(scope, receive, send)` → convert back.

FastAPI itself routes and runs handlers. Schema gen: `.proto` + `FileDescriptorSet`.

No cookies / redirects / FileResponse / StreamingResponse. No `methods.json` dispatch table.

See [`docs/PLAN.md`](docs/PLAN.md).
