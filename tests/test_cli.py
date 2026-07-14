"""CLI coverage: generate + serve dispatch (no Python gRPC)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fastapi_grpc_gateway import cli

ROOT = Path(__file__).resolve().parents[1]


def test_load_app_requires_colon():
    with pytest.raises(SystemExit, match="module:attr"):
        cli._load_app("hello_app")


def test_generate_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(ROOT / "examples"))
    cli.main(
        [
            "generate",
            "--app",
            "hello_app:app",
            "--out",
            str(tmp_path),
            "--package",
            "demo",
            "--service",
            "Svc",
        ]
    )
    assert (tmp_path / "service.proto").exists()
    assert (tmp_path / "bindings.toml").exists()
    out = capsys.readouterr().out
    assert "routes:" in out
    assert "package demo;" in (tmp_path / "service.proto").read_text()


def test_serve_cli_dispatches(monkeypatch, tmp_path):
    called = {}

    def fake_run(app, **kwargs):
        called["app"] = app
        called["kwargs"] = kwargs

    monkeypatch.setattr("fastapi_grpc_gateway.serve.run_serve", fake_run)
    monkeypatch.syspath_prepend(str(ROOT / "examples"))

    bindings = tmp_path / "bindings.toml"
    bindings.write_text('package = "fastapi_grpc"\nservice = "API"\n')
    worker = tmp_path / "fgg-worker"
    worker.write_text("x")

    cli.main(
        [
            "serve",
            "--app",
            "hello_app:app",
            "--http-host",
            "0.0.0.0",
            "--http-port",
            "9000",
            "--grpc-bind",
            "127.0.0.1:50052",
            "--out",
            str(tmp_path / "gen"),
            "--bindings",
            str(bindings),
            "--no-grpc",
            "--worker",
            str(worker),
        ]
    )
    assert called["app"] is not None
    assert called["kwargs"]["http_port"] == 9000
    assert called["kwargs"]["enable_grpc"] is False
    assert called["kwargs"]["bindings_path"] == bindings
    assert called["kwargs"]["worker_bin"] == worker
