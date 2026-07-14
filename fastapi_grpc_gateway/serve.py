"""Orchestrate Granian (HTTP) + Rust fgg-worker (gRPC). No Python gRPC."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi_grpc_gateway.schema import generate_schema

log = logging.getLogger("fgg.serve")


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
) -> None:
    """
    HTTP via Granian embed (Python/ASGI).
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

    granian_server = None
    http_task = None
    if enable_http:
        from granian.constants import Interfaces
        from granian.server.embed import Server

        granian_server = Server(
            app,
            address=http_host,
            port=http_port,
            interface=Interfaces.ASGI,
        )
        http_task = asyncio.create_task(granian_server.serve(), name="fgg-granian-http")
        await asyncio.to_thread(_wait_tcp, http_host, http_port)
        log.info("HTTP (Granian embed) on http://%s:%d", http_host, http_port)

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
        if granian_server is not None:
            granian_server.stop()
        if http_task is not None:
            try:
                await asyncio.wait_for(http_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                http_task.cancel()


def run_serve(app: Any, **kwargs: Any) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(serve_app(app, **kwargs))
    except KeyboardInterrupt:
        pass
