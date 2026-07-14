"""E2E: Granian + Rust fgg-worker (no Python gRPC imports)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "target" / "debug" / "fgg-worker"


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
    if not WORKER.exists():
        subprocess.check_call(
            ["cargo", "build", "-p", "fgg-worker"],
            cwd=ROOT,
        )
    assert WORKER.exists()

    tmp = tmp_path_factory.mktemp("e2e")
    http_port = _free_port()
    grpc_port = _free_port()

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'examples'}:{env.get('PYTHONPATH', '')}"
    env["FGG_WORKER"] = str(WORKER)

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
            "--worker",
            str(WORKER),
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
        assert bindings.exists()
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


@pytest.mark.asyncio
async def test_http_through_granian(e2e_stack):
    httpx = pytest.importorskip("httpx")
    port = e2e_stack["http_port"]
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/hello")
        assert r.status_code == 200
        assert r.json() == {"message": "hello"}

        r = await client.get(f"http://127.0.0.1:{port}/api/users/42")
        assert r.status_code == 200
        assert r.json()["user_id"] == 42


def test_grpc_port_accepts_tcp(e2e_stack):
    """gRPC is Rust — only check the port is open (Go client covers RPCs)."""
    with socket.create_connection(
        ("127.0.0.1", e2e_stack["grpc_port"]), timeout=1
    ):
        pass
