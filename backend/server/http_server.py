"""!
@file http_server.py
@brief HTTP plumbing: security checks, JSON in/out and serving the frontend files.

All real work is delegated to ``ApiRouter`` (API calls) or to the frontend
folder (static files). Every request passes the ``LocalhostGuard`` first.

The MIME types are registered explicitly so browsers get the right type even
if the OS registry is wrong. The page loads nothing from outside: styles, scripts and
the bundled Itim font all come from this server (_CONTENT_SECURITY_POLICY).
_MAX_BODY_BYTES limits the request body size.
"""

import json
import mimetypes
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .api import ApiRouter
from .security import LocalhostGuard

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/x-icon", ".ico")
mimetypes.add_type("font/ttf", ".ttf")

_MAX_BODY_BYTES = 64 * 1024

_CONTENT_SECURITY_POLICY = "default-src 'self'; frame-ancestors 'none'"


@dataclass(frozen=True)
class _ServerContext:
    """!
    @brief Everything the request handler needs, attached to the server object.
    """

    router: ApiRouter
    guard: LocalhostGuard
    frontend_dir: Path


class WebServer:
    """!
    @brief The local web server.
    """

    def __init__(self, host: str, port: int, frontend_dir: Path, router: ApiRouter) -> None:
        """!
        @brief Bind the server socket and attach the request context.
        @param host Address to listen on.
        @param port Port to listen on; 0 picks a free one.
        @param frontend_dir Folder with the static files.
        @param router Handles the API calls.

        ``port`` is set to the real port, which is useful if port was 0.
        """
        self._httpd = ThreadingHTTPServer((host, port), _RequestHandler)
        self.port: int = self._httpd.server_address[1]
        self._httpd.context = _ServerContext(
            router=router,
            guard=LocalhostGuard(self.port),
            frontend_dir=frontend_dir,
        )

    def serve_forever(self) -> None:
        """!
        @brief Serve requests until shutdown() is called.
        """
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """!
        @brief Stop serving and close the socket.
        """
        self._httpd.shutdown()
        self._httpd.server_close()


class _RequestHandler(BaseHTTPRequestHandler):
    """!
    @brief Handles a single HTTP request.
    """

    server_version = "RcloneSync"

    def do_GET(self) -> None:
        """!
        @brief Handle an HTTP GET request.
        """
        self._dispatch("GET")

    def do_POST(self) -> None:
        """!
        @brief Handle an HTTP POST request.
        """
        self._dispatch("POST")

    def do_PUT(self) -> None:
        """!
        @brief Handle an HTTP PUT request.
        """
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        """!
        @brief Handle an HTTP DELETE request.
        """
        self._dispatch("DELETE")

    def log_message(self, format: str, *args) -> None:
        """!
        @brief Silence the default per-request console output.
        @param format Ignored.
        @param args Ignored.
        """

    @property
    def _context(self) -> _ServerContext:
        """!
        @brief Get the context attached to the server object.
        @return The server context.
        """
        return self.server.context

    def _dispatch(self, method: str) -> None:
        """!
        @brief Run the security checks, then send the request to the API or the static files.
        @param method The HTTP method.
        """
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
        """!
        @brief Reject anything that does not come from this computer's own browser.
        @return True if the request may be served; otherwise a 403 was already sent and False is returned.
        """
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

    def _handle_api(self, method: str, path: str, query: dict) -> None:
        """!
        @brief Read the JSON body (for POST and PUT), call the router and send its response.
        @param method The HTTP method.
        @param path The URL path.
        @param query Parsed query parameters.

        If the body is invalid, an error response was already sent and nothing more happens.
        """
        body = self._read_json_body() if method in ("POST", "PUT") else {}
        if body is None:
            return
        response = self._context.router.handle(method, path, query, body)
        self._send_json(response.status, response.payload)

    def _read_json_body(self):
        """!
        @brief Parse the request body as a JSON object.
        @return The object, or None after an error response was sent (413 or 400).
        """
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

    def _serve_static(self, url_path: str) -> None:
        """!
        @brief Serve a file from the frontend folder, never from outside it.
        @param url_path The URL path; "/" means index.html.
        """
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

    def _send_json(self, status: int, payload: dict) -> None:
        """!
        @brief Send a JSON response.
        @param status The HTTP status code.
        @param payload The JSON-serialisable body.
        """
        data = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        """!
        @brief Send a response with the standard security headers.
        @param status The HTTP status code.
        @param data The body.
        @param content_type The Content-Type header value.
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.end_headers()
        self.wfile.write(data)
