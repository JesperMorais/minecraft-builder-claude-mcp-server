"""Pending browser prompts, for sessions that poll instead of using channels.

Channels push a browser prompt straight into the Claude Code session, but they
are a gated research preview: org policy can block them, they need a flag at
startup, and they do not exist at all on Bedrock/Vertex/Foundry. This module is
the inversion that works everywhere — prompts wait in a queue, and Claude pulls
them out with the ``await_prompt`` tool, which is an ordinary tool call no
policy objects to.

Threading mirrors ``chat.py``: prompts are enqueued on an HTTP thread and taken
from the MCP server's executor thread, so everything is built on a condition
variable rather than asyncio.

Delivery has three grades, which the HTTP layer uses to be honest in the UI:

- ``listening`` — an ``await_prompt`` call is blocked right now; a prompt
  enqueued at this moment reaches Claude within milliseconds.
- ``active`` — nobody is blocked, but a take happened recently, so a polling
  loop is plausibly between rounds (building, replying) and will be back.
- neither — the prompt is stored, but nothing suggests anyone will collect it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

# Prompts kept while nothing is collecting them. A sentence each, so the cap is
# about staleness, not memory: prompt #65 from an abandoned tab helps nobody.
MAX_PENDING = 64

# How long after the last take() a polling loop is still presumed alive. Covers
# an await_prompt round (up to 540s) plus the build-and-reply work between two
# rounds.
POLL_GRACE_SECONDS = 900.0


class PromptQueue:
    """Thread-safe FIFO of browser prompts with waiter accounting."""

    def __init__(self, max_pending: int = MAX_PENDING) -> None:
        self._cond = threading.Condition()
        self._items: Deque[Dict] = deque()
        self._max = max_pending
        self._waiters = 0
        # monotonic timestamp of the last take() attempt; None until the first.
        self._last_wait: Optional[float] = None

    def put(self, item: Dict) -> None:
        """Enqueue a prompt, dropping the oldest if the queue is full."""
        with self._cond:
            while len(self._items) >= self._max:
                self._items.popleft()
            self._items.append(item)
            self._cond.notify()

    def take(self, timeout: Optional[float] = None) -> Optional[Dict]:
        """Block until a prompt is available or ``timeout`` elapses.

        Returns the oldest prompt, or ``None`` on timeout.
        """
        with self._cond:
            self._waiters += 1
            self._last_wait = time.monotonic()
            try:
                if not self._cond.wait_for(lambda: bool(self._items), timeout=timeout):
                    return None
                return self._items.popleft()
            finally:
                self._waiters -= 1
                self._last_wait = time.monotonic()

    @property
    def listening(self) -> bool:
        """True while at least one take() is blocked waiting."""
        with self._cond:
            return self._waiters > 0

    def active(self, grace_seconds: float = POLL_GRACE_SECONDS) -> bool:
        """True if a poller is blocked now or polled within ``grace_seconds``.

        This is the "will the prompt actually be collected" signal: between two
        await_prompt rounds nobody is *listening*, but the loop is still there.
        """
        with self._cond:
            if self._waiters > 0:
                return True
            if self._last_wait is None:
                return False
            return (time.monotonic() - self._last_wait) < grace_seconds

    @property
    def pending(self) -> int:
        with self._cond:
            return len(self._items)

    def clear(self) -> None:
        """Drop queued prompts and waiter history. Mainly for tests."""
        with self._cond:
            self._items.clear()
            self._last_wait = None


# Process-wide instance shared by the MCP tools and the HTTP server.
PROMPTS = PromptQueue()
