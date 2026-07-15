"""CLI: fgg generate | fgg serve — schema gen + HTTP backend + Rust fgg-worker."""

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

    serve = sub.add_parser(
        "serve",
        help="HTTP (granian|uvicorn|gunicorn) + Rust fgg-worker gRPC",
    )
    serve.add_argument("--app", required=True)
    serve.add_argument("--http-host", default="127.0.0.1")
    serve.add_argument("--http-port", type=int, default=8000)
    serve.add_argument("--grpc-bind", default="127.0.0.1:50051")
    serve.add_argument("--package", default="fastapi_grpc")
    serve.add_argument("--service", default="API")
    serve.add_argument(
        "--out",
        default=None,
        help="Directory to write service.proto + bindings.toml",
    )
    serve.add_argument(
        "--bindings",
        default=None,
        help="Optional bindings.toml (default: generated from app routes)",
    )
    serve.add_argument(
        "--http-backend",
        choices=("granian", "uvicorn", "gunicorn"),
        default="granian",
        help="ASGI HTTP server (default: granian embed)",
    )
    serve.add_argument(
        "--gunicorn-workers",
        type=int,
        default=1,
        help="Worker processes when --http-backend=gunicorn",
    )
    serve.add_argument(
        "--no-grpc",
        action="store_true",
        help="Only HTTP (do not spawn Rust fgg-worker)",
    )
    serve.add_argument(
        "--worker",
        default=None,
        help="Path to fgg-worker binary (or set FGG_WORKER)",
    )

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
        return

    if args.cmd == "serve":
        from fastapi_grpc_gateway.serve import run_serve

        app = _load_app(args.app)
        run_serve(
            app,
            http_host=args.http_host,
            http_port=args.http_port,
            grpc_bind=args.grpc_bind,
            package=args.package,
            service=args.service,
            bindings_path=Path(args.bindings) if args.bindings else None,
            schema_out=Path(args.out) if args.out else None,
            enable_http=True,
            enable_grpc=not args.no_grpc,
            worker_bin=Path(args.worker) if args.worker else None,
            http_backend=args.http_backend,
            app_target=args.app,
            gunicorn_workers=args.gunicorn_workers,
        )
        return


if __name__ == "__main__":
    main(sys.argv[1:])
