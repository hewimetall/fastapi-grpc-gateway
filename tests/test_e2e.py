"""End-to-end: fgg serve (Granian embed + in-process gRPC→ASGI)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"{host}:{port} not open")


@pytest.fixture(scope="module")
def e2e_stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    http_port = _free_port()
    grpc_port = _free_port()

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'examples'}:{env.get('PYTHONPATH', '')}"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fastapi_grpc_gateway.cli",
            "serve",
            "--app",
            "hello_app:app",
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(http_port),
            "--grpc-bind",
            f"127.0.0.1:{grpc_port}",
            "--out",
            str(tmp),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_port("127.0.0.1", http_port)
        _wait_port("127.0.0.1", grpc_port)
        bindings = tmp / "bindings.toml"
        deadline = time.time() + 10
        while time.time() < deadline and not bindings.exists():
            time.sleep(0.05)
        assert bindings.exists(), "bindings.toml was not written"
        yield {
            "grpc_port": grpc_port,
            "http_port": http_port,
            "proto_dir": tmp,
            "bindings": bindings,
            "proc": proc,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def _compile_proto(proto_dir: Path):
    from grpc_tools import protoc

    proto = proto_dir / "service.proto"
    rc = protoc.main(
        [
            "protoc",
            f"-I{proto_dir}",
            f"--python_out={proto_dir}",
            f"--grpc_python_out={proto_dir}",
            str(proto),
        ]
    )
    assert rc == 0, "protoc failed"
    sys.path.insert(0, str(proto_dir))
    import importlib

    # Fresh import each time module name collides across tests
    for name in ("service_pb2", "service_pb2_grpc"):
        sys.modules.pop(name, None)
    pb2 = importlib.import_module("service_pb2")
    pb2_grpc = importlib.import_module("service_pb2_grpc")
    return pb2, pb2_grpc


@pytest.mark.asyncio
async def test_grpc_inprocess_asgi(e2e_stack):
    grpc = pytest.importorskip("grpc")
    from grpc import aio

    pb2, pb2_grpc = _compile_proto(e2e_stack["proto_dir"])
    port = e2e_stack["grpc_port"]

    import tomllib

    data = tomllib.loads(e2e_stack["bindings"].read_text())
    by_path = {r["path"]: r for r in data["route"]}

    async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
        stub = pb2_grpc.APIStub(channel)

        hello = by_path["/api/hello"]
        method = getattr(stub, hello["rpc"])
        resp = await method(pb2.RpcRequest())
        assert resp.status_code == 200
        assert json.loads(resp.body) == {"message": "hello"}

        user = by_path["/api/users/{user_id}"]
        method = getattr(stub, user["rpc"])
        resp = await method(pb2.RpcRequest(path={"user_id": "42"}))
        assert resp.status_code == 200
        assert json.loads(resp.body)["user_id"] == 42

        items = by_path["/api/items"]
        method = getattr(stub, items["rpc"])
        payload = json.dumps({"name": "x", "price": 1.5}).encode()
        resp = await method(pb2.RpcRequest(body=payload))
        assert resp.status_code == 200
        assert json.loads(resp.body)["name"] == "x"


@pytest.mark.asyncio
async def test_http_still_works(e2e_stack):
    httpx = pytest.importorskip("httpx")
    port = e2e_stack["http_port"]
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/hello")
        assert r.status_code == 200
        assert r.json() == {"message": "hello"}
