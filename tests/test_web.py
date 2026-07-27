"""Tests for the viewer payload, state store and local HTTP server."""

import json
import urllib.error
import urllib.request

import pytest

from minecraft_builder import web
from minecraft_builder.schema import MinecraftStructure
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
    url = web.ensure_running().rstrip("/")
    yield url
    web.shutdown()
    web.STATE.clear()


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
