"""Compile generated proto and serve gRPC that dispatches through ASGI app."""

from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from grpc import aio

from fastapi_grpc_gateway.convert import (
    call_asgi,
    fill_path,
    headers_to_map,
    metadata_to_headers,
)
from fastapi_grpc_gateway.schema import RouteSpec, SchemaBundle


def compile_proto(proto_source: str, *, package: str) -> tuple[Path, Any, Any]:
    """Write proto, run grpc_tools.protoc, import generated modules.

    Returns (tmpdir, pb2_module, pb2_grpc_module).
    """
    from grpc_tools import protoc

    tmp = Path(tempfile.mkdtemp(prefix="fgg_"))
    proto_name = "service.proto"
    proto_path = tmp / proto_name
    proto_path.write_text(proto_source, encoding="utf-8")

    ok = protoc.main(
        [
            "protoc",
            f"-I{tmp}",
            f"--python_out={tmp}",
            f"--grpc_python_out={tmp}",
            str(proto_path),
        ]
    )
    if ok != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("protoc failed to compile generated proto")

    # generated file is service_pb2.py
    sys.path.insert(0, str(tmp))
    try:
        pb2 = importlib.import_module("service_pb2")
        pb2_grpc = importlib.import_module("service_pb2_grpc")
    except Exception:
        sys.path.remove(str(tmp))
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp, pb2, pb2_grpc


def write_descriptor_set(pb2: Any, out_path: Path) -> None:
    """Serialize FileDescriptorSet from compiled pb2 module."""
    fds = descriptor_pb2.FileDescriptorSet()
    file_desc = pb2.DESCRIPTOR
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_desc.CopyToProto(file_proto)
    fds.file.append(file_proto)
    out_path.write_bytes(fds.SerializeToString())


def _message_to_http(
    spec: RouteSpec,
    request_msg: Any,
) -> tuple[str, str, dict[str, str], bytes]:
    """Convert protobuf request message fields into HTTP parts."""
    path_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    body = b""

    for name in spec.path_params:
        path_params[name] = str(getattr(request_msg, name, "") or "")
    for name in spec.query_params:
        val = getattr(request_msg, name, "") or ""
        if val != "":
            query_params[name] = str(val)
    if spec.has_body and hasattr(request_msg, "body"):
        raw = request_msg.body
        body = bytes(raw) if raw else b""

    path = fill_path(spec.path, path_params)
    return spec.http_method, path, query_params, body


def build_servicer(app: Any, bundle: SchemaBundle, pb2: Any, pb2_grpc: Any) -> type:
    """Create a Servicer class that converts each RPC into an ASGI call."""
    specs = {s.rpc_name: s for s in bundle.routes}
    base = getattr(pb2_grpc, f"{bundle.service}Servicer")

    class _Servicer(base):  # type: ignore[valid-type,misc]
        pass

    for rpc_name, spec in specs.items():

        async def _handler(
            self: Any,
            request: Any,
            context: grpc.aio.ServicerContext,
            _spec: RouteSpec = spec,
        ) -> Any:
            method, path, query, body = _message_to_http(_spec, request)
            md = metadata_to_headers(context.invocation_metadata())
            peer = context.peer()  # e.g. ipv4:127.0.0.1:12345
            client = ("127.0.0.1", 0)
            if peer and ":" in peer:
                # ipv4:host:port or ipv6:[...]:port — keep simple
                parts = peer.split(":")
                if parts[0].startswith("ipv4") and len(parts) >= 3:
                    try:
                        client = (parts[1], int(parts[-1]))
                    except ValueError:
                        pass

            status, resp_headers, resp_body = await call_asgi(
                app,
                method=method,
                path=path,
                query=query,
                headers=md,
                body=body,
                client=client,
            )
            # Pass through HTTP status inside the message; gRPC call itself succeeds.
            await context.send_initial_metadata((("x-http-status", str(status)),))
            return pb2.JsonResponse(
                status_code=status,
                body=resp_body,
                headers=headers_to_map(resp_headers),
            )

        setattr(_Servicer, rpc_name, _handler)

    return _Servicer


async def start_grpc_server(
    app: Any,
    bundle: SchemaBundle,
    *,
    host: str = "127.0.0.1",
    port: int = 50051,
) -> tuple[aio.Server, Path, Any, Any]:
    """Compile proto, start aio gRPC server. Returns server, tmpdir, pb2, pb2_grpc."""
    tmp, pb2, pb2_grpc = compile_proto(bundle.proto_source, package=bundle.package)
    servicer_cls = build_servicer(app, bundle, pb2, pb2_grpc)
    server = aio.server()
    add_fn = getattr(pb2_grpc, f"add_{bundle.service}Servicer_to_server")
    add_fn(servicer_cls(), server)
    bound = server.add_insecure_port(f"{host}:{port}")
    if bound == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"failed to bind gRPC port {host}:{port}")
    await server.start()
    return server, tmp, pb2, pb2_grpc
