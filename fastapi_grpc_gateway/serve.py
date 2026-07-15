"""Orchestrate HTTP ASGI server + Rust fgg-worker (gRPC). No Python gRPC."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi_grpc_gateway.schema import generate_schema

log = logging.getLogger("fgg.serve")

HttpBackend = Literal["granian", "uvicorn", "gunicorn"]


def _wait_tcp(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"{host}:{port} did not open")


def _parse_host_port(bind: str) -> tuple[str, int]:
    host, _, port_s = bind.rpartition(":")
    return (host or "127.0.0.1", int(port_s))


def find_worker_binary() -> Path:
    """Resolve fgg-worker: FGG_WORKER env, PATH, or local cargo target."""
    env = os.environ.get("FGG_WORKER")
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise FileNotFoundError(f"FGG_WORKER={env} not found")

    which = shutil.which("fgg-worker")
    if which:
        return Path(which)

    root = Path(__file__).resolve().parents[1]
    for candidate in (
        root / "target" / "release" / "fgg-worker",
        root / "target" / "debug" / "fgg-worker",
    ):
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "fgg-worker not found; set FGG_WORKER, install binary on PATH, "
        "or run `cargo build -p fgg-worker`"
    )


def build_uvicorn_cmd(
    app_target: str,
    *,
    host: str,
    port: int,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        app_target,
        "--host",
        host,
        "--port",
        str(port),
    ]


def build_gunicorn_cmd(
    app_target: str,
    *,
    host: str,
    port: int,
    workers: int = 1,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "gunicorn",
        app_target,
        "-k",
        "uvicorn.workers.UvicornWorker",
        "-b",
        f"{host}:{port}",
        "-w",
        str(workers),
    ]


@dataclass
class _HttpRuntime:
    backend: HttpBackend
    granian_server: Any = None
    http_task: asyncio.Task[Any] | None = None
    http_proc: subprocess.Popen[bytes] | None = None

    async def stop(self) -> None:
        if self.http_proc is not None:
            self.http_proc.terminate()
            try:
                await asyncio.to_thread(self.http_proc.wait, 5)
            except Exception:  # noqa: BLE001
                self.http_proc.kill()
            self.http_proc = None
        if self.granian_server is not None:
            self.granian_server.stop()
            self.granian_server = None
        if self.http_task is not None:
            try:
                await asyncio.wait_for(self.http_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.http_task.cancel()
            self.http_task = None


async def _start_http(
    app: Any,
    *,
    backend: HttpBackend,
    app_target: str | None,
    http_host: str,
    http_port: int,
    gunicorn_workers: int,
) -> _HttpRuntime:
    if backend == "granian":
        from granian.constants import Interfaces
        from granian.server.embed import Server

        server = Server(
            app,
            address=http_host,
            port=http_port,
            interface=Interfaces.ASGI,
        )
        task = asyncio.create_task(server.serve(), name="fgg-granian-http")
        await asyncio.to_thread(_wait_tcp, http_host, http_port)
        log.info("HTTP (granian embed) on http://%s:%d", http_host, http_port)
        return _HttpRuntime(backend=backend, granian_server=server, http_task=task)

    if not app_target or ":" not in app_target:
        raise ValueError(
            f"http-backend={backend} requires app target module:attr "
            "(pass the same --app value)"
        )

    if backend == "uvicorn":
        cmd = build_uvicorn_cmd(app_target, host=http_host, port=http_port)
    elif backend == "gunicorn":
        cmd = build_gunicorn_cmd(
            app_target,
            host=http_host,
            port=http_port,
            workers=gunicorn_workers,
        )
    else:  # pragma: no cover
        raise ValueError(f"unknown http backend: {backend}")

    log.info("starting HTTP backend %s: %s", backend, " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        await asyncio.to_thread(_wait_tcp, http_host, http_port)
    except TimeoutError:
        proc.terminate()
        raise
    log.info("HTTP (%s) on http://%s:%d", backend, http_host, http_port)
    return _HttpRuntime(backend=backend, http_proc=proc)


async def serve_app(
    app: Any,
    *,
    http_host: str = "127.0.0.1",
    http_port: int = 8000,
    grpc_bind: str = "127.0.0.1:50051",
    package: str = "fastapi_grpc",
    service: str = "API",
    bindings_path: Path | None = None,
    schema_out: Path | None = None,
    enable_http: bool = True,
    enable_grpc: bool = True,
    stop_event: asyncio.Event | None = None,
    worker_bin: Path | None = None,
    http_backend: HttpBackend = "granian",
    app_target: str | None = None,
    gunicorn_workers: int = 1,
) -> None:
    """
    HTTP via Granian embed / uvicorn / gunicorn+uvicorn.
    gRPC via Rust fgg-worker subprocess (no ``import grpc`` in Python).
    """
    bundle = generate_schema(app, package=package, service=service)
    if schema_out is not None:
        schema_out.mkdir(parents=True, exist_ok=True)
        (schema_out / "service.proto").write_text(bundle.proto_source, encoding="utf-8")
        (schema_out / "bindings.toml").write_text(bundle.bindings_toml, encoding="utf-8")
        log.info("wrote schema to %s", schema_out)

    if bindings_path is not None:
        bindings_file = bindings_path
    else:
        out = schema_out or Path.cwd() / ".fgg"
        out.mkdir(parents=True, exist_ok=True)
        bindings_file = out / "bindings.toml"
        bindings_file.write_text(bundle.bindings_toml, encoding="utf-8")
        if schema_out is None:
            (out / "service.proto").write_text(bundle.proto_source, encoding="utf-8")

    http_rt: _HttpRuntime | None = None
    if enable_http:
        http_rt = await _start_http(
            app,
            backend=http_backend,
            app_target=app_target,
            http_host=http_host,
            http_port=http_port,
            gunicorn_workers=gunicorn_workers,
        )

    worker_proc: subprocess.Popen[bytes] | None = None
    if enable_grpc:
        if not enable_http:
            raise RuntimeError("gRPC worker needs HTTP upstream (enable_http=True)")
        binary = worker_bin or find_worker_binary()
        grpc_host, grpc_port = _parse_host_port(grpc_bind)
        upstream = f"http://{http_host}:{http_port}"
        worker_proc = subprocess.Popen(
            [
                str(binary),
                "--bind",
                f"{grpc_host}:{grpc_port}",
                "--upstream",
                upstream,
                "--bindings",
                str(bindings_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        await asyncio.to_thread(_wait_tcp, grpc_host, grpc_port)
        log.info("gRPC (Rust fgg-worker) on grpc://%s → %s", grpc_bind, upstream)

    stop = stop_event if stop_event is not None else asyncio.Event()

    def _handle_signal() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, sig_name), _handle_signal)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        if worker_proc is not None:
            worker_proc.terminate()
            try:
                await asyncio.to_thread(worker_proc.wait, 5)
            except Exception:  # noqa: BLE001
                worker_proc.kill()
        if http_rt is not None:
            await http_rt.stop()


def run_serve(app: Any, **kwargs: Any) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(serve_app(app, **kwargs))
    except KeyboardInterrupt:
        pass
