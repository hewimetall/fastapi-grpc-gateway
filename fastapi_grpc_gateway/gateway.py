"""Public gateway: schema export + lifespan-managed gRPC server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI

from fastapi_grpc_gateway.schema import SchemaBundle, generate_proto
from fastapi_grpc_gateway.server import start_grpc_server, write_descriptor_set


class GrpcGateway:
    """Attach gRPC unary entry that converts to ASGI and calls `app`."""

    def __init__(
        self,
        app: FastAPI,
        *,
        package: str = "fastapi_grpc",
        service: str = "API",
        host: str = "127.0.0.1",
        port: int = 50051,
    ) -> None:
        self.app = app
        self.package = package
        self.service = service
        self.host = host
        self.port = port
        self.bundle: SchemaBundle | None = None
        self._server: Any = None
        self._tmpdir: Path | None = None
        self._pb2: Any = None
        self._pb2_grpc: Any = None

    def build_schema(self) -> SchemaBundle:
        self.bundle = generate_proto(
            self.app, package=self.package, service=self.service
        )
        return self.bundle

    def export_proto(self, path: str | Path) -> Path:
        bundle = self.bundle or self.build_schema()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(bundle.proto_source, encoding="utf-8")
        return out

    def export_descriptor(self, path: str | Path) -> Path:
        """Compile current schema and write FileDescriptorSet bytes."""
        from fastapi_grpc_gateway.server import compile_proto

        bundle = self.bundle or self.build_schema()
        tmp, pb2, _ = compile_proto(bundle.proto_source, package=bundle.package)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            write_descriptor_set(pb2, out)
        finally:
            import shutil
            import sys

            if str(tmp) in sys.path:
                sys.path.remove(str(tmp))
            shutil.rmtree(tmp, ignore_errors=True)
        return out

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        await self.start()
        try:
            yield
        finally:
            await self.stop()

    async def start(self) -> None:
        if self._server is not None:
            return
        bundle = self.bundle or self.build_schema()
        self._server, self._tmpdir, self._pb2, self._pb2_grpc = await start_grpc_server(
            self.app,
            bundle,
            host=self.host,
            port=self.port,
        )

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop(grace=None)
            self._server = None
        if self._tmpdir is not None:
            import shutil
            import sys

            if str(self._tmpdir) in sys.path:
                sys.path.remove(str(self._tmpdir))
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
