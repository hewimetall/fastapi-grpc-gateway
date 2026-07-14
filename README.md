# fastapi-grpc-gateway

gRPC unary → **convert** → `app(scope, receive, send)` → convert back.

FastAPI itself routes and runs handlers. Schema gen: `.proto` + `FileDescriptorSet`.

```python
from fastapi import FastAPI
from fastapi_grpc_gateway import GrpcGateway

app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"message": "hello"}

gw = GrpcGateway(app, port=50051)
app.router.lifespan_context = gw.lifespan
# export schemas:
# gw.export_proto("gen/service.proto")
# gw.export_descriptor("gen/descriptor.pb")
```

```bash
fgg generate --app examples.hello_app:app --out ./gen
pytest
```

No cookies / redirects / FileResponse / StreamingResponse.

See [`docs/PLAN.md`](docs/PLAN.md).
