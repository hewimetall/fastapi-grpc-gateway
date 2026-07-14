"""In-process gRPC server: RpcRequest → ASGI → JsonResponse (no HTTP hop)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import grpc
from grpc import aio

from fastapi_grpc_gateway.asgi_bridge import call_asgi, fill_path
from fastapi_grpc_gateway import wire_pb2

log = logging.getLogger("fgg.grpc")


@dataclass(frozen=True)
class RouteBinding:
    rpc: str
    http_method: str
    path: str
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    has_body: bool = False


def bindings_from_mapping(data: Mapping[str, Any]) -> tuple[str, str, dict[str, RouteBinding]]:
    package = str(data["package"])
    service = str(data["service"])
    routes: dict[str, RouteBinding] = {}
    for raw in data.get("route") or []:
        binding = RouteBinding(
            rpc=str(raw["rpc"]),
            http_method=str(raw["http_method"]),
            path=str(raw["path"]),
            path_params=tuple(raw.get("path_params") or ()),
            query_params=tuple(raw.get("query_params") or ()),
            has_body=bool(raw.get("has_body", False)),
        )
        routes[binding.rpc] = binding
    return package, service, routes


def _make_unary(
    app: Any,
    binding: RouteBinding,
    http_server: tuple[str, int],
) -> Callable:
    async def handler(request: wire_pb2.RpcRequest, context: aio.ServicerContext):
        try:
            path = fill_path(binding.path, dict(request.path))
            body = bytes(request.body) if binding.has_body else b""
            status, resp_body, headers = await call_asgi(
                app,
                method=binding.http_method,
                path=path,
                query=dict(request.query),
                body=body,
                server=http_server,
            )
            return wire_pb2.JsonResponse(
                status_code=status,
                body=resp_body,
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001 — surface as gRPC INTERNAL
            log.exception("ASGI call failed for %s", binding.rpc)
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    return handler


async def start_grpc_server(
    app: Any,
    *,
    package: str,
    service: str,
    routes: Mapping[str, RouteBinding],
    bind: str = "127.0.0.1:50051",
    http_server: tuple[str, int] = ("127.0.0.1", 8000),
) -> aio.Server:
    """Create and start an aio gRPC server with one unary method per route."""
    method_handlers = {}
    for rpc, binding in routes.items():
        method_handlers[rpc] = grpc.unary_unary_rpc_method_handler(
            _make_unary(app, binding, http_server),
            request_deserializer=wire_pb2.RpcRequest.FromString,
            response_serializer=wire_pb2.JsonResponse.SerializeToString,
        )

    generic = grpc.method_handlers_generic_handler(
        f"{package}.{service}",
        method_handlers,
    )
    server = aio.server()
    server.add_generic_rpc_handlers((generic,))

    host, _, port_s = bind.rpartition(":")
    host = host or "127.0.0.1"
    port = int(port_s)
    bound = server.add_insecure_port(f"{host}:{port}")
    if bound == 0:
        raise RuntimeError(f"failed to bind gRPC on {bind}")

    await server.start()
    log.info("gRPC listening on %s (%s.%s, %d rpcs)", bind, package, service, len(routes))
    return server
