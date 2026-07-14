"""Extra schema edge-case coverage."""

from __future__ import annotations

from fastapi import FastAPI, Query

from fastapi_grpc_gateway.schema import (
    SchemaBundle,
    RouteSpec,
    generate_schema,
    iter_json_routes,
    render_bindings,
    render_proto,
    _is_unsupported_route,
)


def test_operation_id_and_method_prefix():
    app = FastAPI()

    @app.get("/a", operation_id="fetch-thing")
    async def fetch_thing():
        return {}

    @app.get("/b", name="get_items")
    async def get_items():
        return {}

    routes = list(iter_json_routes(app))
    names = {r.rpc_name for r in routes}
    assert "FetchThing" in names
    assert "GetItems" in names


def test_duplicate_rpc_names_get_suffix():
    app = FastAPI()

    @app.api_route("/x", methods=["GET", "POST"], name="same")
    async def same():
        return {}

    # Force collide by also using operation_id that maps similarly — simpler:
    # two routes with same operation_id
    app2 = FastAPI()

    @app2.get("/one", operation_id="dup")
    async def one():
        return {}

    @app2.get("/two", operation_id="dup")
    async def two():
        return {}

    names = [r.rpc_name for r in iter_json_routes(app2)]
    assert "Dup" in names
    assert "Dup2" in names


def test_skips_upload_and_file_response():
    app = FastAPI()

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    # Simulate unsupported response / param types without python-multipart
    class _Param:
        type_ = "UploadFile"

    class _Field:
        type_ = "FileResponse"

    class _Dep:
        body_params = [_Param()]
        query_params = []
        path_params = []

    class _Route:
        dependant = _Dep()
        response_field = None

    class _RouteResp:
        dependant = _Dep.__new__(_Dep)
        dependant.body_params = []
        dependant.query_params = []
        dependant.path_params = []
        response_field = _Field()

    assert _is_unsupported_route(_Route()) is True  # type: ignore[arg-type]
    assert _is_unsupported_route(_RouteResp()) is True  # type: ignore[arg-type]

    paths = {r.path for r in iter_json_routes(app)}
    assert "/ok" in paths


def test_skips_non_api_routes():
    app = FastAPI()

    @app.get("/json")
    async def json_ok():
        return {"a": 1}

    # Mount adds non-APIRoute entries
    from starlette.routing import Mount
    from starlette.responses import PlainTextResponse

    async def sub(scope, receive, send):
        await PlainTextResponse("x")(scope, receive, send)

    app.router.routes.append(Mount("/mount", app=sub))
    paths = {r.path for r in iter_json_routes(app)}
    assert "/json" in paths
    assert all(not p.startswith("/mount") or p == "/json" for p in paths)


def test_query_params_in_bindings():
    app = FastAPI()

    @app.get("/search")
    async def search(q: str = Query(""), limit: int = 10):
        return {"q": q, "limit": limit}

    bundle = generate_schema(app)
    assert "query_params" in bundle.bindings_toml
    assert '"q"' in bundle.bindings_toml or "q" in bundle.bindings_toml
    assert "Search" in bundle.proto_source or "search" in bundle.proto_source.lower()


def test_render_proto_with_summary_and_path_params():
    bundle = SchemaBundle(
        package="pkg",
        service="Svc",
        routes=[
            RouteSpec(
                rpc_name="GetUser",
                http_method="GET",
                path="/u/{id}",
                path_params=("id",),
                query_params=("q",),
                has_body=False,
                summary="get user",
            )
        ],
    )
    proto = render_proto(bundle)
    assert "// get user" in proto
    bindings = render_bindings(bundle)
    assert 'path_params = ["id"]' in bindings
    assert 'query_params = ["q"]' in bindings


def test_is_unsupported_query_and_path_params():
    class _Param:
        def __init__(self, type_):
            self.type_ = type_

    class _Dep:
        body_params = []
        query_params = [_Param("StreamingResponse")]
        path_params = []

    class _RouteQ:
        dependant = _Dep()
        response_field = None

    class _DepPath:
        body_params = []
        query_params = []
        path_params = [_Param("HtmlResponse")]

    class _RouteP:
        dependant = _DepPath()
        response_field = None

    assert _is_unsupported_route(_RouteQ()) is True  # type: ignore[arg-type]
    assert _is_unsupported_route(_RouteP()) is True  # type: ignore[arg-type]


def test_is_unsupported_without_dependant():
    class Fake:
        dependant = None
        response_field = None

    assert _is_unsupported_route(Fake()) is False  # type: ignore[arg-type]


def test_iter_skips_when_unsupported(monkeypatch):
    app = FastAPI()

    @app.get("/hidden")
    async def hidden():
        return {}

    @app.get("/visible")
    async def visible():
        return {}

    def fake_unsupported(route):
        return getattr(route, "path", None) == "/hidden"

    monkeypatch.setattr(
        "fastapi_grpc_gateway.schema._is_unsupported_route", fake_unsupported
    )
    paths = {r.path for r in iter_json_routes(app)}
    assert "/visible" in paths
    assert "/hidden" not in paths
