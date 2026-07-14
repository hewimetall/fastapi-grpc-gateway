import json
from pathlib import Path

from fastapi import Body, FastAPI
from pydantic import BaseModel

from fastapi_grpc_gateway import generate_schema, iter_json_routes


def build_app() -> FastAPI:
    app = FastAPI()

    class Item(BaseModel):
        name: str
        qty: int = 1

    @app.get("/api/hello")
    async def hello() -> dict[str, str]:
        return {"message": "hello"}

    @app.get("/api/users/{user_id}")
    async def get_user(user_id: int) -> dict:
        return {"user_id": user_id}

    @app.post("/api/items")
    async def create_item(item: Item = Body(...)) -> Item:
        return item

    return app


def test_iter_routes():
    routes = list(iter_json_routes(build_app()))
    paths = {r.path for r in routes}
    assert "/api/hello" in paths
    assert "/api/users/{user_id}" in paths
    assert "/api/items" in paths


def test_generate_schema_artifacts(tmp_path: Path):
    bundle = generate_schema(build_app())
    assert "message RpcRequest" in bundle.proto_source
    assert "service API" in bundle.proto_source
    assert "Hello" in bundle.bindings_toml
    assert 'http_method = "GET"' in bundle.bindings_toml
    assert 'path = "/api/hello"' in bundle.bindings_toml

    proto = tmp_path / "service.proto"
    bindings = tmp_path / "bindings.toml"
    proto.write_text(bundle.proto_source)
    bindings.write_text(bundle.bindings_toml)
    assert proto.stat().st_size > 0
    assert "package =" in bindings.read_text()
