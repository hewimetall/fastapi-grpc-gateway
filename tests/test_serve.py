"""serve_app / helpers — Granian + Rust worker spawn (no Python gRPC)."""

from __future__ import annotations

import asyncio
import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from fastapi_grpc_gateway import serve as serve_mod


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


def test_parse_host_port():
    assert serve_mod._parse_host_port("127.0.0.1:50051") == ("127.0.0.1", 50051)
    assert serve_mod._parse_host_port(":8000")[1] == 8000


def test_find_worker_binary_env(tmp_path, monkeypatch):
    fake = tmp_path / "fgg-worker"
    fake.write_text("x")
    fake.chmod(0o755)
    monkeypatch.setenv("FGG_WORKER", str(fake))
    assert serve_mod.find_worker_binary() == fake


def test_find_worker_binary_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("FGG_WORKER", raising=False)
    monkeypatch.setattr(serve_mod.shutil, "which", lambda _n: None)

    class FakePath(type(Path())):
        pass

    # Isolate cargo target search to empty temp tree
    fake_mod = tmp_path / "fastapi_grpc_gateway"
    fake_mod.mkdir()
    fake_file = fake_mod / "serve.py"
    fake_file.write_text("#")

    import fastapi_grpc_gateway.serve as m

    real_file = m.__file__
    monkeypatch.setattr(m, "__file__", str(fake_file))
    with pytest.raises(FileNotFoundError, match="fgg-worker not found"):
        serve_mod.find_worker_binary()
    monkeypatch.setattr(m, "__file__", real_file)


def test_find_worker_binary_which(monkeypatch, tmp_path):
    fake = tmp_path / "fgg-worker"
    fake.write_text("x")
    fake.chmod(0o755)
    monkeypatch.delenv("FGG_WORKER", raising=False)
    monkeypatch.setattr(serve_mod.shutil, "which", lambda _n: str(fake))
    assert serve_mod.find_worker_binary() == fake


def test_find_worker_binary_cargo_debug(monkeypatch, tmp_path):
    monkeypatch.delenv("FGG_WORKER", raising=False)
    monkeypatch.setattr(serve_mod.shutil, "which", lambda _n: None)
    pkg = tmp_path / "fastapi_grpc_gateway"
    pkg.mkdir()
    serve_py = pkg / "serve.py"
    serve_py.write_text("#")
    debug = tmp_path / "target" / "debug"
    debug.mkdir(parents=True)
    worker = debug / "fgg-worker"
    worker.write_text("x")
    worker.chmod(0o755)
    monkeypatch.setattr(serve_mod, "__file__", str(serve_py))
    assert serve_mod.find_worker_binary() == worker


@pytest.mark.asyncio
async def test_serve_writes_default_bindings_dir(tmp_path, monkeypatch):
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    http_port = _free_port()
    stop = asyncio.Event()
    monkeypatch.chdir(tmp_path)
    task = asyncio.create_task(
        serve_mod.serve_app(
            app,
            http_host="127.0.0.1",
            http_port=http_port,
            schema_out=None,
            bindings_path=None,
            enable_grpc=False,
            stop_event=stop,
        )
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                break
        except OSError:
            await asyncio.sleep(0.05)
    assert (tmp_path / ".fgg" / "bindings.toml").exists()
    stop.set()
    await asyncio.wait_for(task, timeout=15)


@pytest.mark.asyncio
async def test_serve_signal_handler_fires(tmp_path):
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    http_port = _free_port()
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
                http_host="127.0.0.1",
                http_port=http_port,
                schema_out=tmp_path,
                enable_grpc=False,
                stop_event=stop,
            )
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        assert handlers
        handlers[0]()
        await asyncio.wait_for(task, timeout=15)


@pytest.mark.asyncio
async def test_serve_worker_kill_on_slow_exit(tmp_path):
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    http_port = _free_port()
    grpc_port = _free_port()
    stop = asyncio.Event()
    fake_bin = tmp_path / "fgg-worker"
    fake_bin.write_text("x")
    fake_bin.chmod(0o755)

    grpc_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    grpc_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    class SlowProc:
        def __init__(self):
            self._killed = False

        def terminate(self):
            pass

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="fgg-worker", timeout=timeout or 1)

        def kill(self):
            self._killed = True

    slow = SlowProc()

    def fake_popen(*_a, **_k):
        grpc_sock.bind(("127.0.0.1", grpc_port))
        grpc_sock.listen(1)
        return slow

    try:
        with patch.object(serve_mod.subprocess, "Popen", side_effect=fake_popen):
            task = asyncio.create_task(
                serve_mod.serve_app(
                    app,
                    http_host="127.0.0.1",
                    http_port=http_port,
                    grpc_bind=f"127.0.0.1:{grpc_port}",
                    schema_out=tmp_path,
                    enable_grpc=True,
                    stop_event=stop,
                    worker_bin=fake_bin,
                )
            )
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                        with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                            break
                except OSError:
                    await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, timeout=15)
            assert slow._killed
    finally:
        grpc_sock.close()


@pytest.mark.asyncio
async def test_serve_http_only(tmp_path):
    app = FastAPI()

    @app.get("/api/hello")
    async def hello():
        return {"ok": True}

    http_port = _free_port()
    stop = asyncio.Event()
    task = asyncio.create_task(
        serve_mod.serve_app(
            app,
            http_host="127.0.0.1",
            http_port=http_port,
            schema_out=tmp_path,
            enable_http=True,
            enable_grpc=False,
            stop_event=stop,
        )
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                break
        except OSError:
            await asyncio.sleep(0.05)
    assert (tmp_path / "bindings.toml").exists()
    stop.set()
    await asyncio.wait_for(task, timeout=15)


@pytest.mark.asyncio
async def test_serve_grpc_requires_http():
    app = FastAPI()
    with pytest.raises(RuntimeError, match="enable_http"):
        await serve_mod.serve_app(app, enable_http=False, enable_grpc=True)


@pytest.mark.asyncio
async def test_serve_spawns_worker(tmp_path):
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    http_port = _free_port()
    grpc_port = _free_port()
    stop = asyncio.Event()

    fake_bin = tmp_path / "fgg-worker"
    fake_bin.write_text("#!/bin/sh\nexec sleep 3600\n")
    fake_bin.chmod(0o755)

    grpc_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    grpc_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):
        # pretend worker bound the grpc port
        grpc_sock.bind(("127.0.0.1", grpc_port))
        grpc_sock.listen(1)
        return real_popen(["sleep", "3600"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    try:
        with patch.object(serve_mod.subprocess, "Popen", side_effect=fake_popen):
            task = asyncio.create_task(
                serve_mod.serve_app(
                    app,
                    http_host="127.0.0.1",
                    http_port=http_port,
                    grpc_bind=f"127.0.0.1:{grpc_port}",
                    schema_out=tmp_path,
                    enable_http=True,
                    enable_grpc=True,
                    stop_event=stop,
                    worker_bin=fake_bin,
                )
            )
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                        with socket.create_connection(("127.0.0.1", grpc_port), timeout=0.1):
                            break
                except OSError:
                    await asyncio.sleep(0.05)
            else:
                stop.set()
                await task
                raise TimeoutError("ports not open")
            stop.set()
            await asyncio.wait_for(task, timeout=15)
    finally:
        grpc_sock.close()


@pytest.mark.asyncio
async def test_serve_http_task_timeout_cancels():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

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
                    enable_http=True,
                    enable_grpc=False,
                    stop_event=stop,
                    schema_out=Path("/tmp/fgg-test-schema"),  # noqa: S108
                )
            )
            await asyncio.sleep(0.1)
            stop.set()
            await real_wait_for(task, timeout=10)
    finally:
        sock.close()


def test_run_serve_keyboard_interrupt(monkeypatch):
    app = FastAPI()

    async def boom(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(serve_mod, "serve_app", boom)
    serve_mod.run_serve(app, enable_grpc=False)


@pytest.mark.asyncio
async def test_serve_signal_handler_add_fails_gracefully(tmp_path):
    app = FastAPI()

    @app.get("/")
    async def root():
        return {}

    http_port = _free_port()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    with patch.object(loop, "add_signal_handler", side_effect=RuntimeError("no signals")):
        task = asyncio.create_task(
            serve_mod.serve_app(
                app,
                http_host="127.0.0.1",
                http_port=http_port,
                schema_out=tmp_path,
                enable_grpc=False,
                stop_event=stop,
            )
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=15)
