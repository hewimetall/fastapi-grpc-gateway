"""Unit tests for in-process ASGI bridge."""

from __future__ import annotations

import json

import pytest
from fastapi import Body, FastAPI
from pydantic import BaseModel

from fastapi_grpc_gateway.asgi_bridge import call_asgi, fill_path


def test_fill_path():
    assert fill_path("/api/users/{user_id}", {"user_id": "42"}) == "/api/users/42"


class _Item(BaseModel):
    name: str


@pytest.mark.asyncio
async def test_call_asgi_get_and_post():
    app = FastAPI()

    @app.get("/api/hello")
    async def hello():
        return {"message": "hello"}

    @app.post("/api/items")
    async def create(item: _Item = Body(...)):
        return item

    status, body, headers = await call_asgi(app, method="GET", path="/api/hello")
    assert status == 200
    assert json.loads(body) == {"message": "hello"}
    assert "content-type" in headers

    payload = json.dumps({"name": "x"}).encode()
    status, body, _ = await call_asgi(
        app, method="POST", path="/api/items", body=payload
    )
    assert status == 200
    assert json.loads(body)["name"] == "x"
