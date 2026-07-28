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

from .annotations import ANNOTATIONS
from .channel import BRIDGE
from .chat import CHAT
from .prompts import PROMPTS
from .state import STATE

HOST = "127.0.0.1"

# The prompt the "Apply notes" button sends. Deliberately routed through the
# ordinary prompt path rather than a new mechanism: it has to reach Claude the
# same way a typed message does, over whichever of the two paths is working.
APPLY_NOTES_PROMPT = (
    "I have left notes on the build in the viewer. Call get_annotations to read "
    "them, then patch_operations to apply them, then show_structure so I can see "
    "the result."
)

# A prompt is a sentence, not a payload. Cap it so a stray POST cannot make the
# server allocate without bound.
MAX_PROMPT_BYTES = 64 * 1024

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
    # Chained rather than joinpath(dir, name): Traversable.joinpath only took a
    # single argument before Python 3.11, and this supports 3.10.
    return resources.files(_STATIC_PACKAGE).joinpath(_STATIC_DIR).joinpath(filename).read_bytes()


class _Handler(BaseHTTPRequestHandler):
    """Serves the viewer page and the current structure."""

    server_version = "MinecraftBuilderViewer/1.0"

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]

        if path == "/api/structure":
            self._send_json(STATE.payload())
            return

        if path == "/api/version":
            # Kept as a fallback for when the SSE stream drops: polling this
            # single integer lets the page recover without a reload.
            self._send_json({"version": STATE.version})
            return

        if path == "/api/status":
            self._send_json({
                **_link_status(),
                **_annotation_counts(),
                "viewers": CHAT.bus.subscriber_count,
                "version": STATE.version,
            })
            return

        if path == "/api/annotations":
            self._send_json({
                "annotations": [a.model_dump() for a in ANNOTATIONS.all()],
                **_annotation_counts(),
            })
            return

        if path == "/api/events":
            self._stream_events()
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

    def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/prompt": self._post_prompt,
            "/api/annotations": self._post_annotation,
            "/api/annotations/resolve": self._post_resolve_annotations,
            "/api/apply-notes": self._post_apply_notes,
        }.get(path)
        if handler is None:
            self.send_error(404, "Not found")
            return

        body = self._read_json_body()
        if body is None:
            return  # _read_json_body already sent the error
        handler(body)

    def do_DELETE(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0]
        prefix = "/api/annotations/"
        if not path.startswith(prefix):
            self.send_error(404, "Not found")
            return
        try:
            annotation_id = int(path[len(prefix):])
        except ValueError:
            self.send_error(400, "Annotation id must be an integer")
            return
        if not ANNOTATIONS.remove(annotation_id):
            self.send_error(404, f"No annotation {annotation_id}")
            return
        self._send_json({"removed": annotation_id, **_annotation_counts()})

    def _read_json_body(self) -> Optional[dict]:
        """Read and parse a JSON request body, or send an error and return None."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(400, "Bad Content-Length")
            return None
        if length > MAX_PROMPT_BYTES:
            self.send_error(413, "Body too large")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Body must be JSON")
            return None
        if not isinstance(body, dict):
            self.send_error(400, "Body must be a JSON object")
            return None
        return body

    # ----------------------------------------------------------------------- #
    # Annotations
    # ----------------------------------------------------------------------- #

    def _post_annotation(self, body: dict) -> None:
        """Create one annotation, resolved against the version it was drawn on."""
        # Default to the current version rather than rejecting a missing one: the
        # page always knows what it is displaying, but a curl-driven test should
        # not have to.
        version = body.get("structure_version")
        version = STATE.version if version is None else int(version)
        structure = STATE.get(version)
        if structure is None:
            # Either nothing is loaded, or the marked version has aged out of
            # history and its provenance is gone. Say which.
            self.send_error(
                409,
                f"Version {version} is no longer available to resolve against"
                if STATE.version else "No structure is loaded yet",
            )
            return

        try:
            annotation = ANNOTATIONS.add(
                structure,
                structure_version=version,
                kind=str(body.get("kind", "point")),
                note=str(body.get("note", "")),
                pos=body.get("pos"),
                start=body.get("start"),
                end=body.get("end"),
                op_index=body.get("op_index"),
            )
        except (ValueError, TypeError, IndexError) as error:
            self.send_error(400, str(error))
            return

        self._send_json({
            "annotation": annotation.model_dump(),
            **_annotation_counts(),
        })

    def _post_resolve_annotations(self, body: dict) -> None:
        """Mark annotations resolved. No ids means all open ones."""
        ids = body.get("ids")
        try:
            wanted = None if ids is None else [int(i) for i in ids]
        except (TypeError, ValueError):
            self.send_error(400, "ids must be a list of integers")
            return
        self._send_json({"resolved": ANNOTATIONS.resolve(wanted), **_annotation_counts()})

    def _post_apply_notes(self, _body: dict) -> None:
        """Ask Claude to read and apply the open notes.

        Sends a canned prompt down the ordinary prompt path so it travels over
        whichever mechanism is working, exactly as a typed message would.
        """
        open_count, _total = ANNOTATIONS.counts()
        if not open_count:
            self.send_error(400, "There are no open notes to apply")
            return
        self._send_json({
            **self._deliver_prompt(APPLY_NOTES_PROMPT),
            "notes": open_count,
        })

    # ----------------------------------------------------------------------- #
    # Prompts
    # ----------------------------------------------------------------------- #

    def _post_prompt(self, body: dict) -> None:
        text = str(body.get("text", "")).strip()
        if not text:
            self.send_error(400, "Empty prompt")
            return
        self._send_json(self._deliver_prompt(text))

    def _deliver_prompt(self, text: str) -> dict:
        """Get one prompt to Claude, and report honestly how it went."""
        # Push first, then record, so the transcript entry carries the real
        # delivery outcome rather than an optimistic guess.
        #
        # A successful push is NOT proof Claude received anything. push() only
        # reports that the frame reached the transport, and the bridge is attached
        # for every stdio session whether or not the channel is enabled — so a
        # session with channels blocked by org policy discards the notification in
        # silence and push() still returns True. Trusting it and skipping the
        # queue meant every browser prompt was destroyed in exactly that setup,
        # with an await_prompt loop blocked and waiting a few metres away, while
        # this endpoint reported delivered=True.
        #
        # So the prompt is queued as well until the channel has proven itself this
        # session. Once BRIDGE.confirmed is latched the push is trustworthy on its
        # own, and queueing a copy would deliver the same prompt twice.
        pushed = BRIDGE.push(text, {"chat_id": "web", "sender": "viewer"})
        channel_proven = pushed and BRIDGE.confirmed
        delivered = channel_proven or PROMPTS.active()
        message = CHAT.from_user(text, delivered=delivered)
        if not channel_proven:
            PROMPTS.put({"id": message["id"], "text": text, "pushed": pushed})
        if not delivered:
            # Both notes end on the flag with no trailing punctuation on purpose:
            # this line gets copy-pasted, and a sentence period lands inside the
            # server name, which Claude Code reports as "no MCP server configured
            # with that name" — a confusing second failure on top of the first.
            if pushed:
                # An event did go out; whether Claude sees it is undetectable
                # until one comes back answered. Say that, rather than implying
                # either success or failure.
                CHAT.note(
                    "Sent to the Claude session, but nothing has confirmed it yet "
                    "— channel events are not acknowledged, so a session with "
                    "channels disabled or blocked by org policy looks identical "
                    "from here. The prompt is also queued, so if no answer "
                    "arrives you can ask Claude in the terminal to listen with "
                    "its await_prompt tool and it will be picked up. To use "
                    "channels instead, restart Claude Code from the project root "
                    "with this flag:\n"
                    "--dangerously-load-development-channels server:minecraft-builder"
                )
            else:
                CHAT.note(
                    "That prompt was queued, but nothing is collecting prompts "
                    "right now. Either ask Claude in the terminal to listen with "
                    "its await_prompt tool (works everywhere, no flag needed), or "
                    "restart Claude Code from the project root with this flag:\n"
                    "--dangerously-load-development-channels server:minecraft-builder"
                )
        return {"delivered": delivered, "message": message, **_link_status()}

    def _stream_events(self) -> None:
        """Hold an SSE connection open, replaying history then streaming events."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # This response never ends, so it cannot be a keep-alive candidate.
        self.send_header("Connection", "close")
        self.end_headers()

        subscriber = CHAT.bus.subscribe()
        try:
            # Subscribing before replaying means an event published mid-replay is
            # queued rather than lost; the page dedupes on message id.
            self._write_frame(_sse_snapshot())
            for frame in CHAT.stream(subscriber):
                self._write_frame(frame)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Tab closed or navigated away.
        finally:
            CHAT.bus.unsubscribe(subscriber)

    def _write_frame(self, frame: str) -> None:
        self.wfile.write(frame.encode("utf-8"))
        # Without an explicit flush the frame can sit in the buffer, which for a
        # stream that is mostly idle means the page sees nothing at all.
        self.wfile.flush()

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


def _annotation_counts() -> dict:
    """Open/total note counts, so the page can badge the tray without a fetch."""
    open_count, total = ANNOTATIONS.counts()
    return {"notes_open": open_count, "notes_total": total}


def _link_status() -> dict:
    """Whether a prompt typed in the browser actually reaches Claude.

    One function because three responses answer this question — ``/api/status``,
    the SSE snapshot, and the reply to ``POST /api/prompt`` — and a page that got
    a different answer depending on which one it read would be worse than a page
    with no indicator at all.

    The three keys that mean "yes, it gets collected", in descending strength:

    - ``waiting`` — an ``await_prompt`` call is blocked on the queue right now.
      A prompt enqueued this instant reaches Claude in milliseconds.
    - ``polling`` — nobody is blocked, but a take happened within the grace
      window, so a polling loop is between rounds and will be back.
    - ``confirmed`` — a channel event we pushed came back answered, which is the
      only positive proof the channel round trip closes.

    ``attached`` is **not** one of them. It says an MCP session exists over
    stdio, with or without the channel enabled; when org policy blocks channels
    its pushes are discarded in silence. Treating it as proof is what let the
    status dot show green through an entire debugging session in which nothing
    was delivered.
    """
    channel = BRIDGE.status()
    return {
        "attached": channel["attached"],
        "confirmed": channel["confirmed"],
        "events_sent": channel["events_sent"],
        "waiting": PROMPTS.listening,
        "polling": PROMPTS.active(),
        "queued": PROMPTS.pending,
    }


def _sse_snapshot() -> str:
    """First frame on a new connection: enough to render without a second fetch."""
    return (
        "data: "
        + json.dumps({
            "type": "snapshot",
            "messages": CHAT.history(),
            "version": STATE.version,
            **_link_status(),
        })
        + "\n\n"
    )


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
    # The SSE connections died with the server; the bus outlives it, so its
    # subscriber list has to be dropped or they count as live viewers forever.
    CHAT.bus.clear_subscribers()


def port_in_use(port: int = PREFERRED_PORT) -> bool:
    """True if something is already listening on ``port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) == 0
