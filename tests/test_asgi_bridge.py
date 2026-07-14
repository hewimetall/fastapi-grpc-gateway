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


@pytest.mark.asyncio
async def test_call_asgi_receive_disconnect_branch():
    """Drive receive() past the first http.request into http.disconnect."""

    events: list[str] = []

    async def raw_app(scope, receive, send):
        events.append((await receive())["type"])
        events.append((await receive())["type"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    status, body, headers = await call_asgi(raw_app, method="GET", path="/")
    assert status == 204
    assert body == b""
    assert events == ["http.request", "http.disconnect"]
    assert headers == {}
