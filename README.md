# fastapi-grpc-gateway

gRPC unary entry over existing FastAPI JSON routes:

`grpc → adapter → FastAPI → adapter`

Schema generation from the FastAPI route tree (`.proto`, descriptor, method map).

No cookies / redirects / FileResponse / StreamingResponse.

See [`docs/PLAN.md`](docs/PLAN.md).
