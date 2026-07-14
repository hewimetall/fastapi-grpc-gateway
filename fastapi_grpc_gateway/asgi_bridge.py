"""Call a FastAPI/ASGI app in-process from a gRPC RpcRequest."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote, urlencode


def fill_path(template: str, params: Mapping[str, str]) -> str:
    path = template
    for key, value in params.items():
        path = path.replace("{" + key + "}", quote(value, safe=""))
    return path


async def call_asgi(
    app: Any,
    *,
    method: str,
    path: str,
    query: Mapping[str, str] | None = None,
    body: bytes = b"",
    server: tuple[str, int] = ("127.0.0.1", 8000),
) -> tuple[int, bytes, dict[str, str]]:
    """Invoke ASGI HTTP and collect a unary response."""
    query = query or {}
    query_string = urlencode(list(query.items())).encode("ascii")
    headers: list[tuple[bytes, bytes]] = [
        (b"host", f"{server[0]}:{server[1]}".encode("ascii")),
        (b"accept", b"application/json"),
    ]
    if body:
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(body)).encode("ascii")))

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii", errors="ignore"),
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": server,
        "root_path": "",
    }

    status_code = 500
    resp_headers: dict[str, str] = {}
    chunks: list[bytes] = []
    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body or b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            resp_headers.clear()
            for raw_k, raw_v in message.get("headers") or []:
                key = raw_k.decode("latin-1").lower()
                val = raw_v.decode("latin-1")
                resp_headers[key] = val
        elif message["type"] == "http.response.body":
            chunk = message.get("body") or b""
            if chunk:
                chunks.append(chunk)

    await app(scope, receive, send)
    return status_code, b"".join(chunks), resp_headers
