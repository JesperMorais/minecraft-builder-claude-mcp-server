"""Tests for the viewer payload, state store, chat bus and local HTTP server."""

import json
import queue
import threading
import urllib.error
import urllib.request

import pytest

from minecraft_builder import web
from minecraft_builder.schema import MinecraftStructure
from minecraft_builder.web.chat import CHAT, Chat, EventBus
from minecraft_builder.web.payload import VOXEL_STRIDE, build_payload, visible_coords
from minecraft_builder.web.state import ViewerState


def _solid_cube(size=5, block="stone"):
    return MinecraftStructure(
        name="cube",
        operations=[{"op": "cuboid", "start": [0, 0, 0],
                     "end": [size - 1, size - 1, size - 1], "block": block}],
    )


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #

def test_enclosed_voxels_are_dropped():
    # A solid 5x5x5 has 125 blocks but only its 98-block shell can ever be seen.
    payload = build_payload(_solid_cube(5))
    assert payload["counts"]["total"] == 125
    assert payload["counts"]["drawn"] == 125 - 27  # 3x3x3 interior removed
    assert payload["counts"]["hidden"] == 27


def test_include_interior_keeps_everything():
    block_map = _solid_cube(5).expand()
    assert len(visible_coords(block_map, include_interior=True)) == 125


def test_air_is_neither_drawn_nor_treated_as_solid():
    # Carving one interior voxel to air exposes its six neighbours, so the
    # drawn count must go up, not down.
    solid = build_payload(_solid_cube(5))["counts"]["drawn"]
    carved = MinecraftStructure(
        name="carved",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [4, 4, 4], "block": "stone"},
            {"op": "block", "pos": [2, 2, 2], "block": "air"},
        ],
    )
    payload = build_payload(carved)
    assert payload["counts"]["drawn"] > solid
    palette_blocks = [entry["block"] for entry in payload["palette"]]
    assert not any("air" in block for block in palette_blocks)


def test_voxel_array_is_a_multiple_of_the_stride():
    payload = build_payload(_solid_cube(4))
    assert payload["stride"] == VOXEL_STRIDE
    assert len(payload["voxels"]) % VOXEL_STRIDE == 0
    assert len(payload["voxels"]) // VOXEL_STRIDE == payload["counts"]["drawn"]


def test_every_voxel_carries_a_valid_palette_and_operation_index():
    structure = MinecraftStructure(
        name="mixed",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [3, 0, 3], "block": "stone"},
            {"op": "cuboid", "start": [0, 1, 0], "end": [3, 1, 3], "block": "oak_planks"},
        ],
    )
    payload = build_payload(structure)
    palette_size = len(payload["palette"])
    op_count = len(payload["operations"])
    voxels = payload["voxels"]
    for i in range(0, len(voxels), VOXEL_STRIDE):
        assert 0 <= voxels[i + 3] < palette_size
        assert 0 <= voxels[i + 4] < op_count


def test_provenance_survives_into_the_payload():
    structure = MinecraftStructure(
        name="two",
        operations=[
            {"op": "block", "pos": [0, 0, 0], "block": "stone"},
            {"op": "block", "pos": [5, 0, 0], "block": "oak_planks"},
        ],
    )
    payload = build_payload(structure)
    by_coord = {}
    v = payload["voxels"]
    for i in range(0, len(v), VOXEL_STRIDE):
        by_coord[(v[i], v[i + 1], v[i + 2])] = v[i + 4]
    assert by_coord[(0, 0, 0)] == 0
    assert by_coord[(5, 0, 0)] == 1


def test_operation_labels_match_the_structure():
    structure = MinecraftStructure(
        name="s",
        operations=[{"op": "sphere", "center": [0, 0, 0], "radius": 2, "block": "glass"}],
    )
    payload = build_payload(structure)
    assert payload["operations"][0]["label"].startswith("sphere ")


def test_bounds_use_authoring_coordinates_including_negatives():
    structure = MinecraftStructure(
        name="neg",
        blocks=[
            {"x": -4, "y": -2, "z": -6, "block_type": "stone"},
            {"x": 1, "y": 0, "z": 0, "block_type": "stone"},
        ],
    )
    bounds = build_payload(structure)["bounds"]
    assert bounds["min"] == [-4, -2, -6]
    assert bounds["max"] == [1, 0, 0]
    assert bounds["size"] == [6, 3, 7]


def test_palette_colours_are_hex():
    for entry in build_payload(_solid_cube(3))["palette"]:
        assert entry["color"].startswith("#") and len(entry["color"]) == 7


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

def test_state_starts_empty():
    state = ViewerState()
    assert state.current() is None
    assert state.version == 0
    assert state.payload()["empty"] is True


def test_state_versions_increment_and_current_is_the_latest():
    state = ViewerState()
    assert state.put(_solid_cube(2, "stone")) == 1
    assert state.put(_solid_cube(2, "oak_planks")) == 2
    assert state.version == 2
    assert state.current().operations[0].block == "oak_planks"


def test_state_evicts_old_versions_but_keeps_numbering():
    state = ViewerState(max_versions=2)
    for _ in range(5):
        state.put(_solid_cube(2))
    # Numbering must not restart, or the browser's poll would miss updates.
    assert state.version == 5
    assert len(state._versions) == 2


def test_state_payload_reports_the_current_version():
    state = ViewerState()
    state.put(_solid_cube(3))
    state.put(_solid_cube(4))
    assert state.payload()["version"] == 2


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

@pytest.fixture
def viewer():
    """A running viewer, torn down afterwards so the port is released."""
    web.STATE.clear()
    CHAT.clear()
    url = web.ensure_running().rstrip("/")
    yield url
    web.shutdown()
    web.STATE.clear()
    CHAT.clear()


def _post(url, path, payload):
    request = urllib.request.Request(
        url + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def _read_sse(url, expected_frames, timeout=10):
    """Collect SSE frames on a background thread.

    Returns (frames, stop) where stop() ends the read. Frames are parsed from
    ``data:`` lines; keepalive comments are skipped.
    """
    frames = []
    done = threading.Event()

    def reader():
        try:
            with urllib.request.urlopen(url + "/api/events", timeout=timeout) as response:
                buffer = b""
                while len(frames) < expected_frames and not done.is_set():
                    chunk = response.read(1)
                    if not chunk:
                        break
                    buffer += chunk
                    if buffer.endswith(b"\n\n"):
                        text = buffer.decode().strip()
                        buffer = b""
                        if text.startswith("data:"):
                            frames.append(json.loads(text[len("data:"):].strip()))
        except Exception:
            pass
        finally:
            done.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return frames, done


# --------------------------------------------------------------------------- #
# Chat bus
# --------------------------------------------------------------------------- #

def test_bus_delivers_to_every_subscriber():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    assert bus.subscriber_count == 2
    bus.publish({"type": "ping"})
    assert a.get_nowait() == {"type": "ping"}
    assert b.get_nowait() == {"type": "ping"}


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    subscriber = bus.subscribe()
    bus.unsubscribe(subscriber)
    assert bus.subscriber_count == 0
    bus.publish({"type": "ping"})
    with pytest.raises(queue.Empty):
        subscriber.get_nowait()


def test_full_subscriber_queue_drops_oldest_instead_of_blocking():
    # A publish comes from the MCP thread, so a stalled browser tab must never
    # be able to block it.
    bus = EventBus()
    subscriber = bus.subscribe()
    for i in range(subscriber.maxsize + 20):
        bus.publish({"n": i})
    assert subscriber.full()
    # The oldest were discarded, so the queue now starts past zero.
    assert subscriber.get_nowait()["n"] > 0


def test_chat_records_roles_and_delivery():
    chat = Chat()
    user = chat.from_user("build a hut", delivered=False)
    assistant = chat.from_claude("done")
    note = chat.note("heads up")
    assert (user["role"], user["delivered"]) == ("user", False)
    assert assistant["role"] == "assistant"
    assert note["role"] == "system"
    assert [m["id"] for m in chat.history()] == [1, 2, 3]


def test_chat_transcript_is_bounded():
    chat = Chat(max_transcript=5)
    for i in range(12):
        chat.from_claude(f"message {i}")
    history = chat.history()
    assert len(history) == 5
    # Ids keep climbing so a reconnecting page can dedupe correctly.
    assert history[-1]["id"] == 12


def _get(url, path):
    with urllib.request.urlopen(url + path, timeout=5) as response:
        return response.status, response.headers.get("Content-Type"), response.read()


def test_ensure_running_is_idempotent(viewer):
    assert web.is_running()
    assert web.ensure_running().rstrip("/") == viewer


def test_server_binds_loopback_only(viewer):
    assert viewer.startswith("http://127.0.0.1:")


@pytest.mark.parametrize("path,expected_type", [
    ("/", "text/html"),
    ("/index.html", "text/html"),
    # A wrong type here is not cosmetic: browsers refuse to execute an ES
    # module that is not served as JavaScript, and the page silently blanks.
    ("/viewer.js", "text/javascript"),
    ("/style.css", "text/css"),
])
def test_static_assets_are_served_with_correct_types(viewer, path, expected_type):
    status, content_type, body = _get(viewer, path)
    assert status == 200
    assert content_type.startswith(expected_type)
    assert len(body) > 0


def test_unknown_path_is_404(viewer):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(viewer, "/does-not-exist")
    assert excinfo.value.code == 404


def test_api_reports_empty_state_before_anything_is_shown(viewer):
    _, _, body = _get(viewer, "/api/structure")
    assert json.loads(body)["empty"] is True
    _, _, body = _get(viewer, "/api/version")
    assert json.loads(body)["version"] == 0


def test_api_serves_the_current_structure(viewer):
    web.STATE.put(_solid_cube(4, "oak_planks"))
    _, _, body = _get(viewer, "/api/version")
    version = json.loads(body)["version"]
    assert version == 1

    _, content_type, body = _get(viewer, "/api/structure")
    assert content_type.startswith("application/json")
    payload = json.loads(body)
    assert payload["name"] == "cube"
    assert payload["version"] == version
    assert payload["palette"][0]["block"] == "oak_planks"


def test_version_endpoint_tracks_updates(viewer):
    web.STATE.put(_solid_cube(3))
    _, _, first = _get(viewer, "/api/version")
    web.STATE.put(_solid_cube(4))
    _, _, second = _get(viewer, "/api/version")
    assert json.loads(second)["version"] > json.loads(first)["version"]


def test_payload_is_not_cached(viewer):
    # The build changes under the browser, so a cached payload would show a
    # stale structure after a revision.
    web.STATE.put(_solid_cube(3))
    with urllib.request.urlopen(viewer + "/api/structure", timeout=5) as response:
        assert response.headers.get("Cache-Control") == "no-store"


# --------------------------------------------------------------------------- #
# Prompt in, events out
# --------------------------------------------------------------------------- #

def test_prompt_reports_undelivered_with_no_session_attached(viewer):
    # No MCP session in a test, so this is the exact path a user hits when they
    # forget --dangerously-load-development-channels.
    status, body = _post(viewer, "/api/prompt", {"text": "build a hut"})
    assert status == 200
    assert body["delivered"] is False
    assert body["message"]["role"] == "user"

    # The transcript must explain why, not just silently record the prompt.
    roles = [m["role"] for m in CHAT.history()]
    assert roles == ["user", "system"]
    assert "development-channels" in CHAT.history()[1]["text"]


@pytest.mark.parametrize("payload,expected", [
    ({"text": ""}, 400),
    ({"text": "   "}, 400),
    ({}, 400),
])
def test_empty_prompts_are_rejected(viewer, payload, expected):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/prompt", payload)
    assert excinfo.value.code == expected


def test_oversized_prompt_is_rejected(viewer):
    from minecraft_builder.web.app import MAX_PROMPT_BYTES

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/prompt", {"text": "x" * (MAX_PROMPT_BYTES + 100)})
    assert excinfo.value.code == 413


def test_post_to_unknown_path_is_404(viewer):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/nope", {"text": "hi"})
    assert excinfo.value.code == 404


def test_events_stream_opens_with_a_snapshot(viewer):
    web.STATE.put(_solid_cube(3))
    CHAT.from_claude("earlier message")

    frames, stop = _read_sse(viewer, expected_frames=1)
    try:
        _wait_for(lambda: len(frames) >= 1)
        snapshot = frames[0]
        assert snapshot["type"] == "snapshot"
        # Version numbering is process-global and never restarts, so compare
        # against the store rather than hard-coding a number.
        assert snapshot["version"] == web.STATE.version
        # History is replayed so a page opened late is not blank.
        assert [m["text"] for m in snapshot["messages"]] == ["earlier message"]
    finally:
        stop.set()


def test_events_stream_pushes_replies_and_structure_updates(viewer):
    frames, stop = _read_sse(viewer, expected_frames=3)
    try:
        _wait_for(lambda: len(frames) >= 1)  # snapshot first
        CHAT.from_claude("added a doorway")
        CHAT.announce_structure(7, "hut")
        _wait_for(lambda: len(frames) >= 3)

        kinds = [f["type"] for f in frames]
        assert kinds == ["snapshot", "message", "structure"]
        assert frames[1]["message"]["text"] == "added a doorway"
        assert frames[2]["version"] == 7
    finally:
        stop.set()


def test_status_reports_no_attached_session(viewer):
    _, _, body = _get(viewer, "/api/status")
    status = json.loads(body)
    assert status["attached"] is False
    assert status["events_sent"] == 0


def test_status_counts_connected_viewers(viewer):
    _, _, body = _get(viewer, "/api/status")
    assert json.loads(body)["viewers"] == 0

    frames, stop = _read_sse(viewer, expected_frames=1)
    try:
        _wait_for(lambda: len(frames) >= 1)
        _, _, body = _get(viewer, "/api/status")
        assert json.loads(body)["viewers"] == 1
    finally:
        stop.set()


def _wait_for(predicate, timeout=5.0, interval=0.02):
    """Poll until ``predicate`` holds, rather than sleeping a fixed guess."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")
