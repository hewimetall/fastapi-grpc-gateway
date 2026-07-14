import json
from pathlib import Path

import pytest
from fastapi import Body, FastAPI, Request
from pydantic import BaseModel

from fastapi_grpc_gateway import GrpcGateway, generate_proto, iter_json_routes
from fastapi_grpc_gateway.convert import call_asgi, fill_path
from fastapi_grpc_gateway.server import compile_proto, start_grpc_server


def build_app() -> FastAPI:
    app = FastAPI()

    class Item(BaseModel):
        name: str
        qty: int = 1

    @app.get("/api/hello")
    async def hello() -> dict[str, str]:
        return {"message": "hello"}

    @app.get("/api/users/{user_id}")
    async def get_user(user_id: int, request: Request) -> dict:
        return {
            "user_id": user_id,
            "client": request.client.host if request.client else None,
        }

    @app.post("/api/items")
    async def create_item(item: Item = Body(...)) -> Item:
        return item

    return app


def test_iter_json_routes_and_proto():
    app = build_app()
    routes = list(iter_json_routes(app))
    assert {r.path for r in routes} >= {"/api/hello", "/api/users/{user_id}", "/api/items"}
    bundle = generate_proto(app)
    assert "service API" in bundle.proto_source
    assert "rpc " in bundle.proto_source
    assert "JsonResponse" in bundle.proto_source
    assert "fgg: GET /api/hello" in bundle.proto_source


def test_fill_path():
    assert fill_path("/api/users/{user_id}", {"user_id": "42"}) == "/api/users/42"


@pytest.mark.asyncio
async def test_call_asgi_direct():
    app = build_app()
    status, headers, body = await call_asgi(app, method="GET", path="/api/hello")
    assert status == 200
    assert json.loads(body) == {"message": "hello"}


@pytest.mark.asyncio
async def test_call_asgi_path_param_and_client():
    app = build_app()
    status, _, body = await call_asgi(
        app,
        method="GET",
        path="/api/users/7",
        client=("10.0.0.9", 1234),
    )
    assert status == 200
    data = json.loads(body)
    assert data["user_id"] == 7
    assert data["client"] == "10.0.0.9"


@pytest.mark.asyncio
async def test_grpc_end_to_end(unused_tcp_port):
    import grpc
    from grpc import aio

    app = build_app()
    bundle = generate_proto(app)
    port = unused_tcp_port
    server, tmp, pb2, pb2_grpc = await start_grpc_server(
        app, bundle, host="127.0.0.1", port=port
    )
    try:
        async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = pb2_grpc.APIStub(channel)

            # hello
            hello_rpc = next(r for r in bundle.routes if r.path == "/api/hello")
            req_cls = getattr(pb2, f"{hello_rpc.rpc_name}Request")
            method = getattr(stub, hello_rpc.rpc_name)
            resp = await method(req_cls())
            assert resp.status_code == 200
            assert json.loads(resp.body) == {"message": "hello"}

            # path param
            user_rpc = next(r for r in bundle.routes if r.path == "/api/users/{user_id}")
            req_cls = getattr(pb2, f"{user_rpc.rpc_name}Request")
            method = getattr(stub, user_rpc.rpc_name)
            resp = await method(req_cls(user_id="99"))
            assert resp.status_code == 200
            assert json.loads(resp.body)["user_id"] == 99

            # POST body
            item_rpc = next(r for r in bundle.routes if r.path == "/api/items")
            req_cls = getattr(pb2, f"{item_rpc.rpc_name}Request")
            method = getattr(stub, item_rpc.rpc_name)
            payload = json.dumps({"name": "x", "qty": 3}).encode()
            resp = await method(req_cls(body=payload))
            assert resp.status_code == 200
            assert json.loads(resp.body) == {"name": "x", "qty": 3}
    finally:
        await server.stop(None)
        import shutil
        import sys

        if str(tmp) in sys.path:
            sys.path.remove(str(tmp))
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_gateway_export(tmp_path: Path):
    app = build_app()
    gw = GrpcGateway(app)
    gw.build_schema()
    proto = gw.export_proto(tmp_path / "service.proto")
    desc = gw.export_descriptor(tmp_path / "descriptor.pb")
    assert proto.exists() and proto.stat().st_size > 0
    assert desc.exists() and desc.stat().st_size > 0
    # descriptor is a valid FileDescriptorSet
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(desc.read_bytes())
    assert len(fds.file) >= 1


@pytest.fixture
def unused_tcp_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
