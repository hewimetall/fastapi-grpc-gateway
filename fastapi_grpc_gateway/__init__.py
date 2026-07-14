"""gRPC → ASGI convert → FastAPI app dispatch."""

from fastapi_grpc_gateway.gateway import GrpcGateway
from fastapi_grpc_gateway.schema import generate_proto, iter_json_routes

__all__ = ["GrpcGateway", "generate_proto", "iter_json_routes"]
