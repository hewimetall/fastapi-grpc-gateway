# fastapi-grpc-gateway

gRPC unary entry over existing FastAPI JSON routes:

`grpc → adapter → FastAPI → adapter`

No cookies / redirects / FileResponse / StreamingResponse.

See [`docs/PLAN.md`](docs/PLAN.md).
