"""Convert between gRPC-shaped inputs and ASGI calls into the FastAPI app."""

from __future__ import annotations

import urllib.parse
from typing import Any, Mapping
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


def fill_path(template: str, params: Mapping[str, str]) -> str:
    path = template
    for key, value in params.items():
        path = path.replace("{" + key + "}", urllib.parse.quote(str(value), safe=""))
    return path


def build_query(params: Mapping[str, str]) -> bytes:
    if not params:
        return b""
    return urllib.parse.urlencode(params).encode("utf-8")


async def call_asgi(
    app: ASGIApp,
    *,
    method: str,
    path: str,
    query: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    client: tuple[str, int] | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Invoke ASGI app with a synthetic HTTP request; return status, headers, body."""
    query = query or {}
    headers = headers or {}
    client = client or ("127.0.0.1", 0)

    header_list: list[tuple[bytes, bytes]] = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()
    ]
    if body and not any(k == b"content-type" for k, _ in header_list):
        header_list.append((b"content-type", b"application/json"))
    if body and not any(k == b"content-length" for k, _ in header_list):
        header_list.append((b"content-length", str(len(body)).encode("ascii")))

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": build_query(query),
        "headers": header_list,
        "client": client,
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }

    body_sent = False

    async def receive() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    status_code = 500
    response_headers: list[tuple[bytes, bytes]] = []
    chunks: list[bytes] = []

    async def send(message: Message) -> None:
        nonlocal status_code, response_headers
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            response_headers = list(message.get("headers") or [])
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body") or b"")

    await app(scope, receive, send)
    return status_code, response_headers, b"".join(chunks)


def headers_to_map(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers:
        out[k.decode("latin-1")] = v.decode("latin-1")
    return out


def metadata_to_headers(metadata: Any) -> dict[str, str]:
    """Convert gRPC invocation metadata to HTTP headers."""
    result: dict[str, str] = {}
    if metadata is None:
        return result
    for key, value in metadata:
        k = key.lower() if isinstance(key, str) else str(key).lower()
        if k.endswith("-bin"):
            continue
        result[k] = value if isinstance(value, str) else str(value)
    return result
