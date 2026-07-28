"""Tests for the Claude Code channel bridge.

The one link these cannot cover is Claude Code itself: registering a channel
needs a session started with --dangerously-load-development-channels, which a
test cannot arrange. Everything up to the wire is covered here — the frame
format, the thread-to-loop hop, and that pushing events does not disturb normal
request/response traffic on the same transport.
"""

from __future__ import annotations

import asyncio

import anyio
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification, JSONRPCRequest

from minecraft_builder.web.channel import (
    CHANNEL_METHOD,
    ChannelBridge,
    build_frame,
    clean_meta,
)

TIMEOUT = 20


# --------------------------------------------------------------------------- #
# Wire format
# --------------------------------------------------------------------------- #

def test_frame_matches_the_channel_contract():
    frame = build_frame("build a stone hut", {"chat_id": "1", "sender": "web"})
    assert frame.jsonrpc == "2.0"
    assert frame.method == CHANNEL_METHOD == "notifications/claude/channel"
    assert frame.params["content"] == "build a stone hut"
    assert frame.params["meta"] == {"chat_id": "1", "sender": "web"}


def test_frame_has_no_id_because_it_is_a_notification():
    # An id would make it a request, and Claude Code would wait for a response
    # that never comes.
    assert "id" not in build_frame("hello").model_dump(exclude_none=True)


def test_frame_omits_meta_when_absent():
    assert "meta" not in build_frame("hello").model_dump(exclude_none=True)["params"]


def test_clean_meta_drops_keys_claude_code_would_silently_discard():
    # Claude Code keeps only plain identifiers and drops the rest without a
    # word, so filtering here is what makes a lost attribute debuggable.
    cleaned = clean_meta({
        "chat_id": 7,          # stringified
        "sender": "web",
        "chat-id": "nope",     # hyphen: dropped
        "with space": "nope",  # space: dropped
        "1st": "nope",         # leading digit: dropped
        "empty": None,         # no value: dropped
    })
    assert cleaned == {"chat_id": "7", "sender": "web"}


# --------------------------------------------------------------------------- #
# Bridge, unattached
# --------------------------------------------------------------------------- #

def test_push_fails_cleanly_with_no_session():
    bridge = ChannelBridge()
    assert bridge.attached is False
    assert bridge.push("anyone there?") is False
    assert bridge.sent == 0


def test_detach_releases_the_session():
    bridge = ChannelBridge()
    bridge.attach(asyncio.new_event_loop(), object())
    assert bridge.attached is True
    bridge.detach()
    assert bridge.attached is False


# --------------------------------------------------------------------------- #
# Proof of delivery
# --------------------------------------------------------------------------- #

def test_confirm_is_ignored_before_anything_has_been_pushed():
    # Claude calls reply from ordinary terminal turns and from the await_prompt
    # loop. Neither involves a channel event, so neither is evidence the channel
    # works, and latching on one would put the status dot straight back to
    # claiming a link it cannot see.
    bridge = ChannelBridge()
    assert bridge.confirm() is False
    assert bridge.confirmed is False


def test_confirm_counts_once_an_event_has_gone_out():
    async def scenario():
        async with create_client_server_memory_streams() as (_client, server):
            _server_read, server_write = server
            bridge = ChannelBridge()
            bridge.attach(asyncio.get_running_loop(), server_write)
            with anyio.fail_after(TIMEOUT):
                assert await asyncio.to_thread(bridge.push, "build a hut") is True
            assert bridge.confirmed is False  # pushed, but nothing answered yet
            assert bridge.confirm() is True
            assert bridge.confirmed is True

    asyncio.run(scenario())


def test_confirmation_survives_a_detach():
    # Latched on purpose: the channel either works in this session or it does
    # not, and a transport that goes away is not evidence it never worked.
    async def scenario():
        async with create_client_server_memory_streams() as (_client, server):
            _server_read, server_write = server
            bridge = ChannelBridge()
            bridge.attach(asyncio.get_running_loop(), server_write)
            with anyio.fail_after(TIMEOUT):
                await asyncio.to_thread(bridge.push, "build a hut")
            bridge.confirm()
            bridge.detach()
            assert bridge.attached is False
            assert bridge.confirmed is True

    asyncio.run(scenario())


def test_status_is_one_untorn_snapshot():
    bridge = ChannelBridge()
    assert bridge.status() == {"attached": False, "events_sent": 0, "confirmed": False}
    bridge.attach(asyncio.new_event_loop(), object())
    # confirmed cannot be true while events_sent is zero; the guard in confirm()
    # is what makes that combination unrepresentable.
    status = bridge.status()
    assert status == {"attached": True, "events_sent": 0, "confirmed": False}


def test_attached_alone_is_not_proof_of_delivery():
    # The distinction the whole status indicator rests on: attach() succeeds for
    # any stdio session, with or without the channel enabled.
    bridge = ChannelBridge()
    bridge.attach(asyncio.new_event_loop(), object())
    assert bridge.attached is True
    assert bridge.confirmed is False


# --------------------------------------------------------------------------- #
# Bridge, across the thread boundary
# --------------------------------------------------------------------------- #

def test_push_from_a_thread_reaches_the_stream():
    """The core mechanism: HTTP thread -> event loop -> transport."""

    async def scenario():
        async with create_client_server_memory_streams() as (client, server):
            client_read, _client_write = client
            _server_read, server_write = server

            bridge = ChannelBridge()
            bridge.attach(asyncio.get_running_loop(), server_write)

            # to_thread is the point: push() is called from a worker thread,
            # exactly as the HTTP handler calls it.
            with anyio.fail_after(TIMEOUT):
                delivered = await asyncio.to_thread(
                    bridge.push, "build a hut", {"chat_id": "1"}
                )
                assert delivered is True
                received = await client_read.receive()

            frame = received.message.root
            assert frame.method == CHANNEL_METHOD
            assert frame.params["content"] == "build a hut"
            assert frame.params["meta"]["chat_id"] == "1"
            assert bridge.sent == 1

    asyncio.run(scenario())


def test_push_reports_failure_once_the_stream_is_closed():
    async def scenario():
        async with create_client_server_memory_streams() as (_client, server):
            _server_read, server_write = server
            bridge = ChannelBridge()
            bridge.attach(asyncio.get_running_loop(), server_write)
            await server_write.aclose()
            with anyio.fail_after(TIMEOUT):
                assert await asyncio.to_thread(bridge.push, "too late") is False

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Alongside a real server
# --------------------------------------------------------------------------- #

def _request(request_id: int, method: str, params: dict | None = None) -> SessionMessage:
    return SessionMessage(
        message=JSONRPCMessage(
            JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=params or {})
        )
    )


def _notification(method: str, params: dict | None = None) -> SessionMessage:
    return SessionMessage(
        message=JSONRPCMessage(
            JSONRPCNotification(jsonrpc="2.0", method=method, params=params or {})
        )
    )


def test_channel_events_coexist_with_normal_tool_traffic():
    """Push events while the server is live and confirm the transport survives.

    Raw frames rather than the SDK's ClientSession: notifications/claude/channel
    is a Claude Code extension and is not in the SDK client's ServerNotification
    union, so a ClientSession would reject the very frame this asserts. Claude
    Code's own client understands it. Reading raw is what Claude Code sees.
    """
    from minecraft_builder.server import app
    from minecraft_builder.web.channel import ChannelBridge

    async def scenario():
        async with create_client_server_memory_streams() as (client, server):
            client_read, client_write = client
            server_read, server_write = server

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    lambda: app.run(
                        server_read,
                        server_write,
                        app.create_initialization_options(
                            experimental_capabilities={"claude/channel": {}}
                        ),
                        raise_exceptions=True,
                    )
                )

                with anyio.fail_after(TIMEOUT):
                    # Handshake.
                    await client_write.send(_request(1, "initialize", {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    }))
                    init = (await client_read.receive()).message.root
                    caps = init.result["capabilities"]
                    assert caps["experimental"]["claude/channel"] == {}
                    await client_write.send(_notification("notifications/initialized"))

                    # Push a channel event from a worker thread mid-session.
                    bridge = ChannelBridge()
                    bridge.attach(asyncio.get_running_loop(), server_write)
                    assert await asyncio.to_thread(bridge.push, "hello", {"chat_id": "1"})
                    pushed = (await client_read.receive()).message.root
                    assert pushed.method == CHANNEL_METHOD
                    assert pushed.params["content"] == "hello"

                    # The transport must still be usable for ordinary requests.
                    await client_write.send(_request(2, "tools/list"))
                    listed = (await client_read.receive()).message.root
                    assert listed.id == 2
                    names = {tool["name"] for tool in listed.result["tools"]}
                    assert "show_structure" in names

                tg.cancel_scope.cancel()

    asyncio.run(scenario())


def test_server_declares_the_channel_capability():
    from minecraft_builder.server import app

    caps = app.create_initialization_options(
        experimental_capabilities={"claude/channel": {}}
    ).capabilities.model_dump(by_alias=True, mode="json", exclude_none=True)
    assert caps["experimental"]["claude/channel"] == {}
    # Tools must still be advertised: the reply tool is how Claude answers back.
    assert "tools" in caps


def test_server_instructions_mention_the_channel_workflow():
    from minecraft_builder.server import app

    instructions = app.instructions or ""
    assert "channel" in instructions.lower()
    # The instructions are the only place Claude learns to route replies.
    assert "reply" in instructions.lower()
