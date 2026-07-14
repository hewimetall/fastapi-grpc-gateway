"""In-process gRPC server unit tests."""

from __future__ import annotations

import json
import socket

import pytest
from fastapi import FastAPI
from grpc import aio

from fastapi_grpc_gateway import wire_pb2
from fastapi_grpc_gateway.grpc_server import (
    RouteBinding,
    bindings_from_mapping,
    start_grpc_server,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_bindings_from_mapping_defaults():
    pkg, svc, routes = bindings_from_mapping(
        {
            "package": "p",
            "service": "S",
            "route": [
                {
                    "rpc": "Hello",
                    "http_method": "GET",
                    "path": "/hi",
                }
            ],
        }
    )
    assert pkg == "p"
    assert svc == "S"
    assert routes["Hello"].has_body is False
    assert routes["Hello"].path_params == ()


def test_bindings_empty_routes():
    pkg, svc, routes = bindings_from_mapping({"package": "p", "service": "S"})
    assert routes == {}
    assert pkg == "p"


@pytest.mark.asyncio
async def test_grpc_unary_success_and_query():
    app = FastAPI()

    @app.get("/api/hello")
    async def hello(q: str = "x"):
        return {"q": q}

    port = _free_port()
    routes = {
        "GetHello": RouteBinding(
            rpc="GetHello",
            http_method="GET",
            path="/api/hello",
            query_params=("q",),
        )
    }
    server = await start_grpc_server(
        app,
        package="fastapi_grpc",
        service="API",
        routes=routes,
        bind=f"127.0.0.1:{port}",
    )
    try:
        async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            method = channel.unary_unary(
                "/fastapi_grpc.API/GetHello",
                request_serializer=wire_pb2.RpcRequest.SerializeToString,
                response_deserializer=wire_pb2.JsonResponse.FromString,
            )
            resp = await method(wire_pb2.RpcRequest(query={"q": "ok"}))
            assert resp.status_code == 200
            assert json.loads(resp.body) == {"q": "ok"}
    finally:
        await server.stop(grace=1)


@pytest.mark.asyncio
async def test_grpc_handler_aborts_on_asgi_error(monkeypatch):
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("explode")

    port = _free_port()
    routes = {
        "Boom": RouteBinding(rpc="Boom", http_method="GET", path="/boom"),
    }
    server = await start_grpc_server(
        app,
        package="demo",
        service="API",
        routes=routes,
        bind=f"127.0.0.1:{port}",
    )
    try:
        async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            method = channel.unary_unary(
                "/demo.API/Boom",
                request_serializer=wire_pb2.RpcRequest.SerializeToString,
                response_deserializer=wire_pb2.JsonResponse.FromString,
            )
            with pytest.raises(aio.AioRpcError) as ei:
                await method(wire_pb2.RpcRequest())
            assert ei.value.code().name == "INTERNAL"
    finally:
        await server.stop(grace=1)


@pytest.mark.asyncio
async def test_grpc_bind_failure():
    from unittest.mock import patch

    app = FastAPI()
    real_factory = aio.server

    def factory(*args, **kwargs):
        server = real_factory(*args, **kwargs)
        server.add_insecure_port = lambda _addr: 0
        return server

    with patch("fastapi_grpc_gateway.grpc_server.aio.server", side_effect=factory):
        with pytest.raises(RuntimeError, match="failed to bind"):
            await start_grpc_server(
                app,
                package="p",
                service="S",
                routes={},
                bind="127.0.0.1:1",
            )
