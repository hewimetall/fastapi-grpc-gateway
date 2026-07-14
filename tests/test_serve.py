"""serve_app / helpers coverage."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from fastapi_grpc_gateway import serve as serve_mod
from fastapi_grpc_gateway.schema import generate_schema


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_wait_tcp_success():
    port = _free_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    try:
        serve_mod._wait_tcp("127.0.0.1", port, timeout=2.0)
    finally:
        sock.close()


def test_wait_tcp_timeout():
    port = _free_port()
    with pytest.raises(TimeoutError):
        serve_mod._wait_tcp("127.0.0.1", port, timeout=0.15)


def test_parse_bindings_toml():
    data = serve_mod._parse_bindings_toml('package = "x"\nservice = "Y"\n')
    assert data["package"] == "x"
    assert data["service"] == "Y"


@pytest.mark.asyncio
async def test_serve_app_grpc_only_writes_schema_and_stops(tmp_path):
    app = FastAPI()

    @app.get("/api/hello")
    async def hello():
        return {"ok": True}

    grpc_port = _free_port()
    out = tmp_path / "gen"
    bindings = tmp_path / "custom.toml"
    bindings.write_text(generate_schema(app).bindings_toml)
    stop = asyncio.Event()

    task = asyncio.create_task(
        serve_mod.serve_app(
            app,
            http_host="127.0.0.1",
            http_port=_free_port(),
            grpc_bind=f"127.0.0.1:{grpc_port}",
            bindings_path=bindings,
            schema_out=out,
            enable_http=False,
            stop_event=stop,
        )
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        stop.set()
        await task
        raise TimeoutError("grpc did not start")

    assert (out / "service.proto").exists()
    assert (out / "bindings.toml").exists()
    stop.set()
    await asyncio.wait_for(task, timeout=10)


@pytest.mark.asyncio
async def test_serve_app_with_http_and_shutdown():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    grpc_port = _free_port()
    http_port = _free_port()
    stop = asyncio.Event()
    hung = asyncio.Event()

    async def fake_serve():
        await hung.wait()

    fake_server = MagicMock()
    fake_server.serve = fake_serve

    def do_stop():
        hung.set()

    fake_server.stop = do_stop

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", http_port))
    sock.listen(1)

    try:
        with patch("granian.server.embed.Server", return_value=fake_server):
            task = asyncio.create_task(
                serve_mod.serve_app(
                    app,
                    http_host="127.0.0.1",
                    http_port=http_port,
                    grpc_bind=f"127.0.0.1:{grpc_port}",
                    enable_http=True,
                    stop_event=stop,
                )
            )
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=10)
    finally:
        sock.close()


@pytest.mark.asyncio
async def test_serve_app_http_task_timeout_cancels():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    grpc_port = _free_port()
    http_port = _free_port()
    stop = asyncio.Event()

    async def hang_forever():
        await asyncio.sleep(3600)

    fake_server = MagicMock()
    fake_server.serve = hang_forever
    fake_server.stop = MagicMock()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", http_port))
    sock.listen(1)

    real_wait_for = asyncio.wait_for

    async def selective_wait_for(aw, timeout=None):
        if timeout == 10:
            if isinstance(aw, asyncio.Task):
                aw.cancel()
            raise asyncio.TimeoutError
        return await real_wait_for(aw, timeout=timeout)

    try:
        with (
            patch("granian.server.embed.Server", return_value=fake_server),
            patch.object(serve_mod.asyncio, "wait_for", side_effect=selective_wait_for),
        ):
            task = asyncio.create_task(
                serve_mod.serve_app(
                    app,
                    http_host="127.0.0.1",
                    http_port=http_port,
                    grpc_bind=f"127.0.0.1:{grpc_port}",
                    enable_http=True,
                    stop_event=stop,
                )
            )
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                        break
                except OSError:
                    await asyncio.sleep(0.05)
            stop.set()
            await real_wait_for(task, timeout=10)
    finally:
        sock.close()


def test_run_serve_keyboard_interrupt(monkeypatch):
    app = FastAPI()

    async def boom(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(serve_mod, "serve_app", boom)
    serve_mod.run_serve(app, enable_http=False)


@pytest.mark.asyncio
async def test_serve_signal_handler_registers_and_fires():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    grpc_port = _free_port()
    stop = asyncio.Event()
    handlers: list = []

    loop = asyncio.get_running_loop()
    real_add = loop.add_signal_handler

    def capture(sig, cb):
        handlers.append(cb)
        return real_add(sig, cb)

    with patch.object(loop, "add_signal_handler", side_effect=capture):
        task = asyncio.create_task(
            serve_mod.serve_app(
                app,
                grpc_bind=f"127.0.0.1:{grpc_port}",
                enable_http=False,
                stop_event=stop,
            )
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        assert handlers
        handlers[0]()  # simulate SIGTERM
        await asyncio.wait_for(task, timeout=10)


@pytest.mark.asyncio
async def test_serve_signal_handler_add_fails_gracefully():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    grpc_port = _free_port()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    with patch.object(loop, "add_signal_handler", side_effect=RuntimeError("no signals")):
        task = asyncio.create_task(
            serve_mod.serve_app(
                app,
                grpc_bind=f"127.0.0.1:{grpc_port}",
                enable_http=False,
                stop_event=stop,
            )
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=10)
