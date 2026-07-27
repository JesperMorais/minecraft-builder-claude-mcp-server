"""Tests for polling-mode chat: the prompt queue and the await_prompt tool.

Channels can be blocked by org policy, absent on Bedrock, or simply not enabled
at startup. These tests pin down the fallback: prompts queue up in
``web.prompts.PROMPTS`` and Claude collects them with ``await_prompt``, an
ordinary tool call no policy gates.
"""

import asyncio
import json
import threading
import urllib.request

import pytest

from minecraft_builder import web
from minecraft_builder.server import call_tool
from minecraft_builder.web.chat import CHAT
from minecraft_builder.web.prompts import PROMPTS, PromptQueue

# --------------------------------------------------------------------------- #
# PromptQueue
# --------------------------------------------------------------------------- #

def test_take_returns_prompts_oldest_first():
    q = PromptQueue()
    q.put({"id": 1, "text": "a"})
    q.put({"id": 2, "text": "b"})
    assert q.take(timeout=0)["text"] == "a"
    assert q.take(timeout=0)["text"] == "b"


def test_take_times_out_with_none():
    assert PromptQueue().take(timeout=0.05) is None


def test_take_wakes_when_a_prompt_arrives():
    q = PromptQueue()
    result = {}

    def waiter():
        result["prompt"] = q.take(timeout=5)

    thread = threading.Thread(target=waiter)
    thread.start()
    _wait_for(lambda: q.listening)
    q.put({"id": 1, "text": "hello"})
    thread.join(timeout=5)
    assert result["prompt"]["text"] == "hello"


def test_listening_tracks_blocked_waiters():
    q = PromptQueue()
    assert not q.listening

    stop = threading.Event()
    thread = threading.Thread(target=lambda: (q.take(timeout=5), stop.set()))
    thread.start()
    _wait_for(lambda: q.listening)
    q.put({"id": 1, "text": "x"})
    stop.wait(timeout=5)
    assert not q.listening
    thread.join(timeout=5)


def test_active_is_false_until_someone_has_polled():
    q = PromptQueue()
    assert not q.active()
    q.take(timeout=0)
    # A poll just happened, so the loop is presumed alive within the grace.
    assert q.active()
    assert not q.active(grace_seconds=0)


def test_full_queue_drops_the_oldest_prompt():
    q = PromptQueue(max_pending=2)
    for i in range(3):
        q.put({"id": i, "text": str(i)})
    assert q.pending == 2
    assert q.take(timeout=0)["id"] == 1


def test_clear_resets_backlog_and_history():
    q = PromptQueue()
    q.put({"id": 1, "text": "x"})
    q.take(timeout=0)
    q.clear()
    assert q.pending == 0
    assert not q.active()


# --------------------------------------------------------------------------- #
# HTTP delivery into the queue
# --------------------------------------------------------------------------- #

@pytest.fixture
def viewer():
    web.STATE.clear()
    CHAT.clear()
    PROMPTS.clear()
    url = web.ensure_running().rstrip("/")
    yield url
    web.shutdown()
    web.STATE.clear()
    CHAT.clear()
    PROMPTS.clear()


def _post(url, path, payload):
    request = urllib.request.Request(
        url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def _get_json(url, path):
    with urllib.request.urlopen(url + path, timeout=5) as response:
        return json.loads(response.read())


def _wait_for(predicate, timeout=5.0, interval=0.02):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def test_prompt_is_queued_when_channel_push_fails(viewer):
    # No MCP session attached, so the channel push fails and the queue is the
    # only route. Nothing has ever polled, so the prompt reports undelivered.
    status, body = _post(viewer, "/api/prompt", {"text": "build a hut"})
    assert status == 200
    assert body["delivered"] is False
    assert PROMPTS.pending == 1
    assert PROMPTS.take(timeout=0)["text"] == "build a hut"


def test_prompt_reaches_a_blocked_waiter_and_reports_delivered(viewer):
    result = {}
    thread = threading.Thread(target=lambda: result.update(prompt=PROMPTS.take(timeout=5)))
    thread.start()
    _wait_for(lambda: PROMPTS.listening)

    _, body = _post(viewer, "/api/prompt", {"text": "add a chimney"})
    thread.join(timeout=5)

    assert body["delivered"] is True
    assert result["prompt"]["text"] == "add a chimney"
    # Delivered prompts should not leave a "nothing is listening" note behind.
    roles = [m["role"] for m in CHAT.history()]
    assert roles == ["user"]


def test_undelivered_note_mentions_both_recovery_paths(viewer):
    _post(viewer, "/api/prompt", {"text": "hello?"})
    note = CHAT.history()[1]["text"]
    assert "await_prompt" in note
    assert "development-channels" in note


def test_status_reports_waiting_and_queue_depth(viewer):
    status = _get_json(viewer, "/api/status")
    assert status["waiting"] is False
    assert status["queued"] == 0

    thread = threading.Thread(target=lambda: PROMPTS.take(timeout=5))
    thread.start()
    _wait_for(lambda: PROMPTS.listening)
    assert _get_json(viewer, "/api/status")["waiting"] is True

    PROMPTS.put({"id": 1, "text": "x"})
    thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# The await_prompt tool
# --------------------------------------------------------------------------- #

def test_await_prompt_returns_a_queued_prompt(viewer):
    PROMPTS.put({"id": 1, "text": "build a lighthouse"})
    result = asyncio.run(call_tool("await_prompt", {}))
    text = result[0].text
    assert "build a lighthouse" in text
    # The result must coach the loop, or Claude answers once and stops listening.
    assert "await_prompt" in text
    assert "reply" in text


def test_await_prompt_timeout_is_a_normal_result(viewer, monkeypatch):
    from minecraft_builder import server

    monkeypatch.setattr(server, "MIN_AWAIT_SECONDS", 0.01)
    result = asyncio.run(call_tool("await_prompt", {"timeout_seconds": 0.01}))
    text = result[0].text
    assert "No prompt" in text
    assert "await_prompt" in text  # keep-listening coaching survives a timeout


def test_await_prompt_clamps_a_nonsense_timeout(viewer, monkeypatch):
    from minecraft_builder import server

    taken = {}

    def fake_take(timeout=None):
        taken["timeout"] = timeout
        return {"id": 1, "text": "hi"}

    monkeypatch.setattr(server.viewer_prompts, "take", fake_take)
    asyncio.run(call_tool("await_prompt", {"timeout_seconds": 10_000}))
    assert taken["timeout"] == server.MAX_AWAIT_SECONDS

    asyncio.run(call_tool("await_prompt", {"timeout_seconds": "not a number"}))
    assert taken["timeout"] == server.DEFAULT_AWAIT_SECONDS


def test_await_prompt_starts_the_viewer(viewer):
    # The tool must guarantee there is a page to type into; the fixture already
    # started one, so this pins the ensure_running path stays in the handler.
    PROMPTS.put({"id": 1, "text": "x"})
    result = asyncio.run(call_tool("await_prompt", {}))
    assert web.is_running()
    assert result  # and the call still returned the prompt


def test_server_instructions_mention_polling():
    from minecraft_builder.server import app

    instructions = (app.instructions or "").lower()
    assert "await_prompt" in instructions
