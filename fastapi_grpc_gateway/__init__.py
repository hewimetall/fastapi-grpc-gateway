"""Minimal FastAPI helpers: route walk + .proto / bindings generation."""

from fastapi_grpc_gateway.schema import generate_schema, iter_json_routes

__all__ = ["generate_schema", "iter_json_routes"]
