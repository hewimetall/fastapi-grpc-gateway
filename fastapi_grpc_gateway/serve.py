"""Custom Granian-based process: HTTP (Granian embed) + gRPC→ASGI in-process."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from pathlib import Path
from typing import Any

from fastapi_grpc_gateway.grpc_server import bindings_from_mapping, start_grpc_server
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


def _parse_bindings_toml(text: str) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore
    return tomllib.loads(text)


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
) -> None:
    """
    One process, one ASGI app instance:

      HTTP  → Granian embed → FastAPI
      gRPC  → adapter → same FastAPI (ASGI call, no localhost HTTP)
    """
    bundle = generate_schema(app, package=package, service=service)
    if schema_out is not None:
        schema_out.mkdir(parents=True, exist_ok=True)
        (schema_out / "service.proto").write_text(bundle.proto_source, encoding="utf-8")
        (schema_out / "bindings.toml").write_text(bundle.bindings_toml, encoding="utf-8")
        log.info("wrote schema to %s", schema_out)

    if bindings_path is not None:
        data = _parse_bindings_toml(bindings_path.read_text(encoding="utf-8"))
    else:
        data = _parse_bindings_toml(bundle.bindings_toml)

    pkg, svc, routes = bindings_from_mapping(data)
    http_server = (http_host, http_port)

    grpc = await start_grpc_server(
        app,
        package=pkg,
        service=svc,
        routes=routes,
        bind=grpc_bind,
        http_server=http_server,
    )

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

    log.info("gRPC on grpc://%s (in-process ASGI)", grpc_bind)

    stop = asyncio.Event()

    def _handle_signal() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            import signal

            loop.add_signal_handler(getattr(signal, sig_name), _handle_signal)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        await grpc.stop(grace=5)
        if granian_server is not None:
            granian_server.stop()
        if http_task is not None:
            try:
                await asyncio.wait_for(http_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                http_task.cancel()


def run_serve(
    app: Any,
    **kwargs: Any,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(serve_app(app, **kwargs))
    except KeyboardInterrupt:
        pass
