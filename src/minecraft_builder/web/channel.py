"""Pushes browser prompts into the running Claude Code session.

Claude Code's *channels* feature lets an MCP server send events into the session
it is attached to, so Claude reacts to something that happened outside the
terminal. That inverts the usual MCP direction — normally only the model
initiates — and it is what lets the viewer double as a chat window.

Two constraints shape this module:

**No supported handle on the session.** ``Server.run()`` builds its
``ServerSession`` as a local and never exposes it, and a channel event is
spontaneous — triggered by an HTTP POST, not by a tool call — so
``request_context`` is not available either. What we do have is the write stream
that ``stdio_server()`` yields, and a channel event is an ordinary JSON-RPC
notification. Writing the frame onto that stream needs no private API and does
not change between SDK versions the way the session's internals might.

**Wrong thread.** The HTTP server is a thread; the MCP server is an asyncio task.
The stream can only be written from the event loop, so pushes are marshalled
across with ``run_coroutine_threadsafe``.

Everything channel-specific lives here on purpose. Channels are a research
preview whose contract may change, and the MCP tools have to keep working
without it — a break here should cost the chat box, not the product.
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any, Dict, Final, Literal, Optional

from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification
from pydantic import BaseModel

# The method Claude Code listens for once "claude/channel" is declared. Final so
# it narrows to its literal type, letting it serve as the model default below.
CHANNEL_METHOD: Final = "notifications/claude/channel"

# Meta keys become attributes on the <channel> tag Claude sees. Claude Code drops
# keys that are not plain identifiers *silently*, so they are filtered here where
# the cause is visible rather than turning into a mysteriously missing chat_id.
_VALID_META_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# How long a push waits for the event loop to accept the frame. Generous enough
# to cover a busy loop, short enough that the browser is not left hanging.
PUSH_TIMEOUT_SECONDS = 5.0


class ChannelParams(BaseModel):
    content: str
    meta: Optional[Dict[str, str]] = None


class ChannelNotification(BaseModel):
    """A ``notifications/claude/channel`` frame.

    Declared as a model rather than a hand-built dict so the wire format is
    asserted in one place and covered by a test.
    """

    # Spelled out rather than Literal[CHANNEL_METHOD]: Literal takes a literal,
    # not a name. The test asserts the two agree.
    method: Literal["notifications/claude/channel"] = CHANNEL_METHOD
    params: ChannelParams


def build_frame(content: str, meta: Optional[Dict[str, str]] = None) -> JSONRPCNotification:
    """Build the JSON-RPC notification for a channel event."""
    notification = ChannelNotification(params=ChannelParams(content=content, meta=meta))
    return JSONRPCNotification(
        jsonrpc="2.0",
        **notification.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def clean_meta(meta: Dict[str, object]) -> Dict[str, str]:
    """Keep only meta entries Claude Code will actually deliver.

    Values are stringified and non-identifier keys dropped, matching what the
    client does, so what we log is what Claude receives.
    """
    return {
        key: str(value)
        for key, value in meta.items()
        if _VALID_META_KEY.match(key) and value is not None
    }


class ChannelBridge:
    """Sends channel events into the MCP session from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._write_stream = None
        self._sent = 0
        # Latched: once the round trip has been observed to close, a later detach
        # does not un-prove it. The channel either works in this session or it
        # does not, and a reconnect is not evidence to the contrary.
        self._confirmed = False

    def attach(self, loop: asyncio.AbstractEventLoop, write_stream) -> None:
        """Bind to the running MCP session's event loop and write stream."""
        with self._lock:
            self._loop = loop
            self._write_stream = write_stream

    def detach(self) -> None:
        with self._lock:
            self._loop = None
            self._write_stream = None

    @property
    def attached(self) -> bool:
        """Whether there is a session to write to.

        Deliberately *not* the same as "the channel works". This is true whenever
        the MCP server is running over stdio, with or without the channel
        enabled, so on its own it is no evidence that anything is delivered. Use
        ``confirmed`` for that.
        """
        with self._lock:
            return self._loop is not None and self._write_stream is not None

    @property
    def sent(self) -> int:
        """How many events have been handed to the transport this session."""
        with self._lock:
            return self._sent

    @property
    def confirmed(self) -> bool:
        """Whether an event we pushed has ever been answered.

        The only positive proof the round trip closes. Channel notifications are
        unacknowledged, and a session lacking the channel — or blocked by org
        policy — discards them in silence, so nothing on the outbound side can
        tell "delivered" from "dropped". A reply coming back can.
        """
        with self._lock:
            return self._confirmed

    def confirm(self) -> bool:
        """Record that Claude answered an event we pushed.

        Returns whether this counted. A reply arriving before we have pushed
        anything proves nothing about the channel — Claude can call the ``reply``
        tool during an ordinary terminal turn, or while driving the viewer over
        ``await_prompt``, neither of which involves a channel event — so it is
        ignored rather than latched.
        """
        with self._lock:
            if self._sent == 0:
                return False
            self._confirmed = True
            return True

    def status(self) -> Dict[str, object]:
        """The channel's state as one snapshot, taken under a single lock.

        Read together so a caller cannot see a torn combination — ``confirmed``
        true while ``events_sent`` still reads zero — and draw a state that never
        happened.
        """
        with self._lock:
            attached = self._loop is not None and self._write_stream is not None
            return {
                "attached": attached,
                "events_sent": self._sent,
                "confirmed": self._confirmed,
            }

    @staticmethod
    async def _send(stream: Any, frame: JSONRPCNotification) -> None:
        """Write one frame. Takes the stream explicitly rather than reading it
        from ``self``, so a concurrent detach() cannot null it out between the
        check in push() and the send."""
        await stream.send(SessionMessage(message=JSONRPCMessage(frame)))

    def push(self, content: str, meta: Optional[Dict[str, object]] = None) -> bool:
        """Send a channel event. Returns False if there is nothing to send it to.

        A True result means the frame reached the transport, **not** that Claude
        acted on it: channel notifications are unacknowledged, and a session
        started without the channel enabled discards them without a word. That
        asymmetry is why the UI has to treat silence as an expected outcome.
        """
        with self._lock:
            loop, stream = self._loop, self._write_stream
        if loop is None or stream is None:
            return False

        frame = build_frame(content, clean_meta(meta) if meta else None)
        try:
            future = asyncio.run_coroutine_threadsafe(self._send(stream, frame), loop)
            future.result(timeout=PUSH_TIMEOUT_SECONDS)
        except Exception:
            # A closed stream or a stopped loop both mean the session is gone.
            return False
        with self._lock:
            self._sent += 1
        return True


# The process-wide bridge: attached by the MCP entry point, used by the HTTP thread.
BRIDGE = ChannelBridge()
