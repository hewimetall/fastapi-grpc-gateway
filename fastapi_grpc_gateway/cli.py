"""CLI: fgg generate — emit proto + bindings for the Rust worker."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def _load_app(target: str):
    if ":" not in target:
        raise SystemExit("app must be module:attr, e.g. hello_app:app")
    module_name, attr = target.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fgg")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate service.proto + bindings.toml")
    gen.add_argument("--app", required=True)
    gen.add_argument("--out", required=True)
    gen.add_argument("--package", default="fastapi_grpc")
    gen.add_argument("--service", default="API")

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        from fastapi_grpc_gateway.schema import generate_schema

        app = _load_app(args.app)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        bundle = generate_schema(app, package=args.package, service=args.service)
        (out / "service.proto").write_text(bundle.proto_source, encoding="utf-8")
        (out / "bindings.toml").write_text(bundle.bindings_toml, encoding="utf-8")
        print(f"wrote {out / 'service.proto'}")
        print(f"wrote {out / 'bindings.toml'}")
        print(f"routes: {len(bundle.routes)}")


if __name__ == "__main__":
    main(sys.argv[1:])
