"""CLI: fgg generate --app module:attr --out dir."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def _load_app(target: str):
    if ":" not in target:
        raise SystemExit("app must be module:attr, e.g. main:app")
    module_name, attr = target.split(":", 1)
    module = importlib.import_module(module_name)
    app = getattr(module, attr)
    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fgg", description="FastAPI gRPC gateway tools")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate .proto and descriptor from FastAPI app")
    gen.add_argument("--app", required=True, help="module:attr to FastAPI instance")
    gen.add_argument("--out", required=True, help="output directory")
    gen.add_argument("--package", default="fastapi_grpc")
    gen.add_argument("--service", default="API")

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        from fastapi_grpc_gateway.gateway import GrpcGateway

        app = _load_app(args.app)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        gw = GrpcGateway(app, package=args.package, service=args.service)
        gw.build_schema()
        proto_path = gw.export_proto(out / "service.proto")
        desc_path = gw.export_descriptor(out / "descriptor.pb")
        print(f"wrote {proto_path}")
        print(f"wrote {desc_path}")
        print(f"routes: {len(gw.bundle.routes) if gw.bundle else 0}")


if __name__ == "__main__":
    main(sys.argv[1:])
