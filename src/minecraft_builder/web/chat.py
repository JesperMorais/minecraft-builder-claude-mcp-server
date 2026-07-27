"""Chat transcript and the event bus that feeds the browser.

Two directions meet here. Prompts go *in* through the channel bridge, and
everything the page needs to know about — Claude's replies, a new structure
version, a warning — comes *out* over Server-Sent Events.

Threading: publishes originate on the MCP server's thread (a tool call) while
each SSE connection is served on its own HTTP thread, so the fan-out is built on
``queue.Queue`` rather than anything asyncio-flavoured.

Subscriber queues are bounded and drop their oldest event when full. A browser
tab that is throttled in the background should fall behind and recover, not grow
a queue until the process runs out of memory.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from typing import Dict, Iterator, List, Optional

# Per-connection backlog before the oldest events start being dropped.
SUBSCRIBER_QUEUE_SIZE = 256

# How long a transcript we keep for a page that connects late or reconnects.
MAX_TRANSCRIPT = 200


class EventBus:
    """Fan-out of JSON-serialisable events to connected SSE clients."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def clear_subscribers(self) -> None:
        """Forget every subscriber.

        Called when the HTTP server stops: the connections are gone with it, and
        the bus is process-global, so without this their queues would linger and
        be counted as connected viewers by the next server that starts.
        """
        with self._lock:
            self._subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        """Number of connected pages. Used to tell 'nobody is looking' apart
        from 'the page is looking but Claude never answered'."""
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: Dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                # Drop the oldest to make room; a stalled tab must not be able
                # to block a publish coming from the MCP thread.
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass


class Chat:
    """The conversation between the browser and Claude."""

    def __init__(self, max_transcript: int = MAX_TRANSCRIPT) -> None:
        self._lock = threading.Lock()
        self._messages: List[Dict] = []
        self._ids = itertools.count(1)
        self._max = max_transcript
        self.bus = EventBus()

    def _append(self, role: str, text: str, **extra) -> Dict:
        with self._lock:
            message = {
                "id": next(self._ids),
                "role": role,
                "text": text,
                "at": time.time(),
                **extra,
            }
            self._messages.append(message)
            if len(self._messages) > self._max:
                del self._messages[0]
        self.bus.publish({"type": "message", "message": message})
        return message

    def from_user(self, text: str, delivered: bool) -> Dict:
        """Record a prompt typed in the browser.

        ``delivered`` is whether the channel bridge accepted it. False means no
        session is attached, which the page reports rather than leaving the user
        waiting on a reply that cannot come.
        """
        return self._append("user", text, delivered=delivered)

    def from_claude(self, text: str) -> Dict:
        return self._append("assistant", text)

    def note(self, text: str) -> Dict:
        """A message from the tooling itself, not from Claude."""
        return self._append("system", text)

    def history(self) -> List[Dict]:
        with self._lock:
            return list(self._messages)

    def announce_structure(self, version: int, name: str) -> None:
        """Tell connected pages a new structure version is available."""
        self.bus.publish({"type": "structure", "version": version, "name": name})

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def stream(self, subscriber: queue.Queue, heartbeat: float = 15.0) -> Iterator[str]:
        """Yield SSE frames for one connection until the client disconnects.

        The heartbeat is what makes a closed browser tab detectable: without
        traffic the write that fails is the only signal, and it may never come.
        """
        while True:
            try:
                event = subscriber.get(timeout=heartbeat)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield _sse(event)


def _sse(event: Dict) -> str:
    import json

    # Newlines inside the payload would terminate the frame early, so the JSON is
    # emitted compactly on a single data line.
    return f"data: {json.dumps(event)}\n\n"


# Process-wide instance shared by the MCP tools and the HTTP server.
CHAT = Chat()
