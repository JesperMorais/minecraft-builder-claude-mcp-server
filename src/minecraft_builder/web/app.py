"""Localhost HTTP server for the 3D viewer.

Built on ``http.server`` from the standard library rather than a framework. The
whole surface is three GETs on loopback for one local user, so a dependency would
buy nothing, and it keeps the framework choice open for when this grows a
two-way channel.

Runs in a daemon thread alongside the MCP server. It only ever binds 127.0.0.1:
the page can drive Claude in a later phase, so an externally reachable port would
be a prompt-injection route into a session that can run shell commands.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Optional, Tuple

from .state import STATE

HOST = "127.0.0.1"

# Tried first so the URL is stable between sessions; falls back to an ephemeral
# port if something else already holds it.
PREFERRED_PORT = 8791

# How often the serving thread checks whether it has been asked to stop.
SHUTDOWN_POLL_SECONDS = 0.1

# Anchored on the package rather than on "…web.static": that directory has no
# __init__.py, and resolving a bare directory as a resource anchor is a namespace
# package edge case on the older Pythons this supports.
_STATIC_PACKAGE = "minecraft_builder.web"
_STATIC_DIR = "static"

# Correct types matter more than usual here: a browser refuses to execute an ES
# module served as text/plain, which presents as a blank page with no error.
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

_server: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def _read_static(filename: str) -> bytes:
    """Read a packaged static file.

    Read per request rather than cached: it costs nothing locally and means
    editing the frontend only needs a browser refresh, not a session restart.
    """
    return resources.files(_STATIC_PACKAGE).joinpath(_STATIC_DIR, filename).read_bytes()


class _Handler(BaseHTTPRequestHandler):
    """Serves the viewer page and the current structure."""

    server_version = "MinecraftBuilderViewer/1.0"

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]

        if path == "/api/structure":
            self._send_json(STATE.payload())
            return

        if path == "/api/version":
            # Cheap poll target: the page fetches the full payload only when
            # this changes, which stands in for a push channel in this phase.
            self._send_json({"version": STATE.version})
            return

        static = _STATIC_FILES.get(path)
        if static is None:
            self.send_error(404, "Not found")
            return

        filename, content_type = static
        try:
            body = _read_static(filename)
        except FileNotFoundError:
            self.send_error(500, f"Missing packaged asset: {filename}")
            return
        self._send_bytes(body, content_type)

    def _send_json(self, data: dict) -> None:
        self._send_bytes(json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The payload changes as the build is revised, so never let it cache.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Browser navigated away mid-response; not worth logging.
            pass

    def log_message(self, format: str, *args) -> None:
        """Silence per-request logging.

        stderr is the MCP server's log channel and ends up in Claude Code's
        debug file, so request spam there is actively unhelpful.
        """


def _bind() -> Tuple[ThreadingHTTPServer, int]:
    """Bind the preferred port, falling back to any free one."""
    for port in (PREFERRED_PORT, 0):
        try:
            server = ThreadingHTTPServer((HOST, port), _Handler)
        except OSError:
            continue
        return server, server.server_address[1]
    raise OSError("Could not bind a local port for the viewer")


def ensure_running() -> str:
    """Start the viewer if it is not already running, and return its URL."""
    global _server, _thread
    with _lock:
        if _server is None:
            _server, port = _bind()
            _thread = threading.Thread(
                # serve_forever polls for the shutdown flag; the 0.5s default
                # makes every stop wait out a full tick for no benefit.
                target=_server.serve_forever,
                kwargs={"poll_interval": SHUTDOWN_POLL_SECONDS},
                name="minecraft-builder-viewer",
                daemon=True,  # must not keep the MCP process alive
            )
            _thread.start()
        else:
            port = _server.server_address[1]
    return f"http://{HOST}:{port}/"


def is_running() -> bool:
    with _lock:
        return _server is not None


def shutdown() -> None:
    """Stop the viewer. Mainly for tests; the daemon thread dies with the process."""
    global _server, _thread
    with _lock:
        server, thread = _server, _thread
        _server, _thread = None, None
    if server is not None:
        server.shutdown()
        server.server_close()
    if thread is not None:
        thread.join(timeout=5)


def port_in_use(port: int = PREFERRED_PORT) -> bool:
    """True if something is already listening on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) == 0
