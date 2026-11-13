"""
HTTP plumbing: security checks, JSON in/out and serving the frontend files.

All real work is delegated to ``ApiRouter`` (API calls) or to the frontend
folder (static files). Every request passes the ``LocalhostGuard`` first.
"""

import json
import mimetypes
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .api import ApiRouter
from .security import LocalhostGuard

# Make sure browsers get the right type even if the OS registry is wrong.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

_MAX_BODY_BYTES = 64 * 1024

# The page only loads its own files; nothing from the internet.
_CONTENT_SECURITY_POLICY = "default-src 'self'; frame-ancestors 'none'"


@dataclass(frozen=True)
class _ServerContext:
    """Everything the request handler needs, attached to the server object."""

    router: ApiRouter
    guard: LocalhostGuard
    frontend_dir: Path


class WebServer:
    """The local web server."""

    def __init__(self, host: str, port: int, frontend_dir: Path, router: ApiRouter) -> None:
        self._httpd = ThreadingHTTPServer((host, port), _RequestHandler)
        self.port: int = self._httpd.server_address[1]  # real port (useful if port was 0)
        self._httpd.context = _ServerContext(  # type: ignore[attr-defined]
            router=router,
            guard=LocalhostGuard(self.port),
            frontend_dir=frontend_dir,
        )

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _RequestHandler(BaseHTTPRequestHandler):
    """Handles a single HTTP request."""

    server_version = "OneDriveSync"

    # --- HTTP verbs ---------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Silence the default per-request console output."""

    # --- Request flow -------------------------------------------------

    @property
    def _context(self) -> _ServerContext:
        return self.server.context  # type: ignore[attr-defined]

    def _dispatch(self, method: str) -> None:
        if not self._passes_security_checks():
            return

        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(method, parsed.path, parse_qs(parsed.query))
        elif method == "GET":
            self._serve_static(parsed.path)
        else:
            self._send_json(405, {"error": "Method not allowed."})

    def _passes_security_checks(self) -> bool:
        """Reject anything that does not come from this computer's own browser."""
        guard = self._context.guard
        if not guard.is_client_allowed(self.client_address[0]):
            self._send_json(403, {"error": "Only requests from this computer are accepted."})
            return False
        if not guard.is_host_header_allowed(self.headers.get("Host")):
            self._send_json(403, {"error": "Unexpected Host header."})
            return False
        if not guard.is_origin_allowed(self.headers.get("Origin")):
            self._send_json(403, {"error": "Cross-origin requests are not allowed."})
            return False
        return True

    # --- API ----------------------------------------------------------

    def _handle_api(self, method: str, path: str, query: dict) -> None:
        body = self._read_json_body() if method in ("POST", "PUT") else {}
        if body is None:
            return  # an error response was already sent
        response = self._context.router.handle(method, path, query, body)
        self._send_json(response.status, response.payload)

    def _read_json_body(self):
        """Parse the request body as a JSON object. Returns None after sending an error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY_BYTES:
            self._send_json(413, {"error": "Request body missing or too large."})
            return None
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "Body must be valid JSON."})
            return None
        if not isinstance(body, dict):
            self._send_json(400, {"error": "Body must be a JSON object."})
            return None
        return body

    # --- Static files -------------------------------------------------

    def _serve_static(self, url_path: str) -> None:
        """Serve a file from the frontend folder, never from outside it."""
        root = self._context.frontend_dir.resolve()
        relative = unquote(url_path).lstrip("/") or "index.html"
        try:
            candidate = (root / relative).resolve()
            is_valid = candidate.is_relative_to(root) and candidate.is_file()
        except (OSError, ValueError):
            is_valid = False
        if not is_valid:
            self._send_json(404, {"error": "Not found."})
            return

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self._send_bytes(200, candidate.read_bytes(), content_type)

    # --- Responses ----------------------------------------------------

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.end_headers()
        self.wfile.write(data)
