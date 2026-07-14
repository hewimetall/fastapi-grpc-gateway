"""Minimal FastAPI helpers: schema gen + in-process Granian/gRPC serve."""

from fastapi_grpc_gateway.schema import generate_schema, iter_json_routes

__all__ = ["generate_schema", "iter_json_routes"]
