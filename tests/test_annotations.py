"""Tests for build markup and its resolution to operations.

The transformation under test is coordinate -> operation. A note saying "the
block at [7, 4, 3] is wrong" makes Claude guess which of forty operations to
edit; "operation #4, the roof pyramid" is a targeted edit. Everything here is
about getting that mapping right, and right *at the moment the user marked it* --
resolving later would point at whatever occupies the coordinate after a revision.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from minecraft_builder import web
from minecraft_builder.schema import MinecraftStructure
from minecraft_builder.web.annotations import (
    ANNOTATIONS,
    AnnotationStore,
    resolve_target,
)
from minecraft_builder.web.chat import CHAT
from minecraft_builder.web.prompts import PROMPTS

# A three-part house whose parts own disjoint, unequal voxel counts, so
# "dominant operation" tests are not accidentally testing a tie:
#   index 0: floor  y=0,    the full 5x5           = 25 voxels
#   index 1: walls  y=1..2, ring only, no ceiling  = 32 voxels (16 per layer)
#   index 2: roof   y=3,    the full 5x5 on top    = 25 voxels
FLOOR, WALLS, ROOF = 0, 1, 2


def _house():
    return MinecraftStructure(
        name="house",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [4, 0, 4], "block": "stone"},
            {"op": "hollow_box", "start": [0, 1, 0], "end": [4, 2, 4],
             "block": "oak_planks", "floor": False, "ceiling": False},
            {"op": "cuboid", "start": [0, 3, 0], "end": [4, 3, 4], "block": "oak_slab"},
        ],
    )


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def test_a_point_resolves_to_the_operation_that_placed_it():
    resolved = resolve_target(_house(), "point", pos=[2, 3, 2])
    assert resolved["op_index"] == ROOF
    assert "cuboid" in resolved["op_summary"]


def test_a_point_resolves_to_the_last_writer_not_the_first():
    # Layering is the whole reason provenance is recorded at write time: an
    # operation that overwrites a coordinate is the one the user is looking at.
    structure = MinecraftStructure(
        name="over",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 2, 2], "block": "stone"},
            {"op": "cuboid", "start": [1, 1, 1], "end": [1, 1, 1], "block": "glass"},
        ],
    )
    assert resolve_target(structure, "point", pos=[1, 1, 1])["op_index"] == 1
    assert resolve_target(structure, "point", pos=[0, 0, 0])["op_index"] == 0


def test_a_point_in_empty_space_resolves_to_nothing():
    resolved = resolve_target(_house(), "point", pos=[40, 40, 40])
    assert resolved["op_index"] is None
    assert resolved["op_summary"] is None


def test_a_region_resolves_to_the_operation_owning_most_of_it():
    # A box drawn round the roof inevitably clips the walls. The roof is still
    # what the user meant, so the dominant operation wins: 25 roof voxels against
    # the 16 wall voxels in the top wall layer.
    resolved = resolve_target(_house(), "region", start=[0, 2, 0], end=[4, 3, 4])
    assert resolved["op_index"] == ROOF
    assert resolved["also_covered"] == [WALLS]
    assert resolved["covered_voxels"] == 25
    assert resolved["region_voxels"] == 25 + 16


def test_a_tie_goes_to_the_later_operation():
    # Ties are common, since a selection often catches equal parts of two layers.
    # The later operation is drawn on top, so it is the one the user clicked at.
    # Without an explicit rule this would depend on block-map iteration order.
    structure = MinecraftStructure(
        name="tie",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [3, 0, 0], "block": "stone"},
            {"op": "cuboid", "start": [0, 1, 0], "end": [3, 1, 0], "block": "glass"},
        ],
    )
    resolved = resolve_target(structure, "region", start=[0, 0, 0], end=[3, 1, 0])
    assert resolved["covered_voxels"] == 4
    assert resolved["region_voxels"] == 8
    assert resolved["op_index"] == 1


def test_a_region_reports_its_coverage_share():
    resolved = resolve_target(_house(), "region", start=[0, 3, 0], end=[4, 3, 4])
    # Entirely roof: dominant accounts for every marked voxel.
    assert resolved["covered_voxels"] == resolved["region_voxels"] == 25
    assert resolved["also_covered"] == []


def test_region_corners_may_be_given_in_any_order():
    forward = resolve_target(_house(), "region", start=[0, 0, 0], end=[4, 3, 4])
    backward = resolve_target(_house(), "region", start=[4, 3, 4], end=[0, 0, 0])
    assert forward == backward


def test_an_empty_region_resolves_to_nothing():
    resolved = resolve_target(_house(), "region", start=[50, 50, 50], end=[52, 52, 52])
    assert resolved["op_index"] is None
    assert resolved["region_voxels"] == 0


def test_an_operation_annotation_takes_the_index_directly():
    resolved = resolve_target(_house(), "operation", op_index=WALLS)
    assert resolved["op_index"] == WALLS
    assert "hollow_box" in resolved["op_summary"]


def test_a_global_annotation_targets_no_operation():
    assert resolve_target(_house(), "global") == {"op_index": None, "op_summary": None}


@pytest.mark.parametrize("kwargs,message", [
    ({"kind": "operation", "op_index": 99}, "op_index"),
    ({"kind": "operation", "op_index": None}, "op_index"),
    ({"kind": "point"}, "pos"),
    ({"kind": "region", "start": [0, 0, 0]}, "start and end"),
    ({"kind": "nonsense"}, "unknown annotation kind"),
])
def test_bad_resolution_input_is_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        resolve_target(_house(), **kwargs)


def test_indices_span_blocks_then_operations():
    # Same space as expand_with_provenance() and patch_operations, so an op_index
    # needs no translation on its way to a patch.
    structure = MinecraftStructure(
        name="mixed",
        blocks=[{"x": 9, "y": 9, "z": 9, "block_type": "torch"}],
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [1, 1, 1],
                     "block": "stone"}],
    )
    assert resolve_target(structure, "point", pos=[9, 9, 9])["op_index"] == 0
    assert resolve_target(structure, "point", pos=[0, 0, 0])["op_index"] == 1


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

def test_add_resolves_and_assigns_an_id():
    store = AnnotationStore()
    first = store.add(_house(), 1, "point", "too flat", pos=[2, 3, 2])
    second = store.add(_house(), 1, "global", "whole thing is too grey")
    assert (first.id, second.id) == (1, 2)
    assert first.op_index == ROOF
    assert second.op_index is None
    assert first.status == "open"


def test_a_note_is_required():
    store = AnnotationStore()
    with pytest.raises(ValueError, match="needs a note"):
        store.add(_house(), 1, "point", "   ", pos=[2, 3, 2])


def test_resolve_closes_only_what_was_asked():
    store = AnnotationStore()
    a = store.add(_house(), 1, "point", "a", pos=[2, 3, 2])
    b = store.add(_house(), 1, "point", "b", pos=[0, 0, 0])
    assert store.resolve([a.id]) == [a.id]
    assert [n.id for n in store.open()] == [b.id]
    # Already-resolved ids are not reported as changed a second time.
    assert store.resolve([a.id]) == []


def test_resolve_with_no_ids_closes_everything_open():
    store = AnnotationStore()
    store.add(_house(), 1, "point", "a", pos=[2, 3, 2])
    store.add(_house(), 1, "point", "b", pos=[0, 0, 0])
    assert len(store.resolve()) == 2
    assert store.open() == []
    assert len(store.all()) == 2  # resolved, not deleted


def test_remove_deletes_outright():
    store = AnnotationStore()
    a = store.add(_house(), 1, "point", "a", pos=[2, 3, 2])
    assert store.remove(a.id) is True
    assert store.all() == []
    assert store.remove(a.id) is False


def test_counts_track_open_and_total():
    store = AnnotationStore()
    a = store.add(_house(), 1, "point", "a", pos=[2, 3, 2])
    store.add(_house(), 1, "point", "b", pos=[0, 0, 0])
    assert store.counts() == (2, 2)
    store.resolve([a.id])
    assert store.counts() == (1, 2)


def test_the_oldest_note_is_dropped_when_full():
    store = AnnotationStore(max_annotations=2)
    first = store.add(_house(), 1, "point", "a", pos=[2, 3, 2])
    store.add(_house(), 1, "point", "b", pos=[0, 0, 0])
    store.add(_house(), 1, "point", "c", pos=[1, 1, 1])
    assert first.id not in [n.id for n in store.all()]
    assert len(store.all()) == 2


def test_describe_leads_with_the_operation():
    store = AnnotationStore()
    note = store.add(_house(), 1, "point", "too flat", pos=[2, 3, 2])
    line = note.describe()
    assert f"operation #{ROOF}" in line
    assert "too flat" in line
    # The label is what makes it actionable without a second lookup.
    assert "cuboid" in line


def test_describe_of_a_region_reports_the_share_and_overlap():
    store = AnnotationStore()
    note = store.add(_house(), 1, "region", "roof too flat",
                     start=[0, 2, 0], end=[4, 3, 4])
    line = note.describe()
    assert "% of the selection" in line
    assert "also touches" in line


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

@pytest.fixture
def viewer():
    web.STATE.clear()
    CHAT.clear()
    PROMPTS.clear()
    ANNOTATIONS.clear()
    url = web.ensure_running().rstrip("/")
    yield url
    web.shutdown()
    web.STATE.clear()
    CHAT.clear()
    PROMPTS.clear()
    ANNOTATIONS.clear()


def _post(url, path, payload):
    request = urllib.request.Request(
        url + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def _get(url, path):
    with urllib.request.urlopen(url + path, timeout=5) as response:
        return json.loads(response.read())


def _delete(url, path):
    request = urllib.request.Request(url + path, method="DELETE")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_posting_a_point_annotation_resolves_it(viewer):
    web.STATE.put(_house())
    status, body = _post(viewer, "/api/annotations", {
        "kind": "point", "pos": [2, 3, 2], "note": "roof is too flat",
    })
    assert status == 200
    annotation = body["annotation"]
    assert annotation["op_index"] == ROOF
    assert annotation["note"] == "roof is too flat"
    assert body["notes_open"] == 1


def test_annotations_resolve_against_the_version_that_was_marked(viewer):
    """The reason resolution happens at creation time.

    Mark a coordinate on version 1, then revise the build so a different
    operation owns that coordinate. The note must still point at what the user
    was looking at.
    """
    # Version numbering is process-global and never restarts, so take the number
    # from the store rather than assuming this is version 1.
    marked_version = web.STATE.put(_house())
    _status, body = _post(viewer, "/api/annotations", {
        "kind": "point", "pos": [2, 3, 2], "note": "roof",
        "structure_version": marked_version,
    })
    assert body["annotation"]["op_index"] == ROOF

    # A later version where [2,3,2] belongs to operation 0 instead.
    web.STATE.put(MinecraftStructure(
        name="house",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [4, 4, 4],
                     "block": "stone"}],
    ))
    stored = _get(viewer, "/api/annotations")["annotations"][0]
    assert stored["op_index"] == ROOF
    assert stored["structure_version"] == marked_version


def test_annotating_a_version_that_has_aged_out_is_refused(viewer):
    web.STATE.put(_house())
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/annotations", {
            "kind": "point", "pos": [2, 3, 2], "note": "x", "structure_version": 999,
        })
    # Refused rather than silently resolved against the current build.
    assert excinfo.value.code == 409


def test_annotating_with_nothing_loaded_is_refused(viewer):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/annotations", {
            "kind": "point", "pos": [0, 0, 0], "note": "x",
        })
    assert excinfo.value.code == 409


def test_a_bad_annotation_is_a_400_not_a_500(viewer):
    web.STATE.put(_house())
    for payload in (
        {"kind": "point", "note": "no pos"},
        {"kind": "point", "pos": [0, 0, 0], "note": ""},
        {"kind": "operation", "op_index": 99, "note": "out of range"},
        {"kind": "wat", "note": "bad kind"},
    ):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(viewer, "/api/annotations", payload)
        assert excinfo.value.code == 400, payload


def test_listing_and_resolving_over_http(viewer):
    web.STATE.put(_house())
    _, first = _post(viewer, "/api/annotations",
                     {"kind": "point", "pos": [2, 3, 2], "note": "a"})
    _, second = _post(viewer, "/api/annotations",
                      {"kind": "point", "pos": [0, 0, 0], "note": "b"})
    first_id = first["annotation"]["id"]
    second_id = second["annotation"]["id"]
    assert _get(viewer, "/api/annotations")["notes_open"] == 2

    _status, body = _post(viewer, "/api/annotations/resolve", {"ids": [first_id]})
    assert body["resolved"] == [first_id]
    assert body["notes_open"] == 1

    # No ids: everything still open, which is just the second one.
    _status, body = _post(viewer, "/api/annotations/resolve", {})
    assert body["resolved"] == [second_id]
    assert body["notes_open"] == 0


def test_deleting_an_annotation_over_http(viewer):
    web.STATE.put(_house())
    _, created = _post(viewer, "/api/annotations",
                       {"kind": "point", "pos": [2, 3, 2], "note": "a"})
    path = f"/api/annotations/{created['annotation']['id']}"
    assert _delete(viewer, path)["notes_open"] == 0
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _delete(viewer, path)
    assert excinfo.value.code == 404


def test_a_non_numeric_annotation_id_is_a_400(viewer):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _delete(viewer, "/api/annotations/not-a-number")
    assert excinfo.value.code == 400


def test_status_carries_the_note_counts(viewer):
    web.STATE.put(_house())
    assert _get(viewer, "/api/status")["notes_open"] == 0
    _post(viewer, "/api/annotations", {"kind": "point", "pos": [2, 3, 2], "note": "a"})
    status = _get(viewer, "/api/status")
    assert (status["notes_open"], status["notes_total"]) == (1, 1)


def test_apply_notes_sends_a_prompt_down_the_ordinary_path(viewer):
    """"Apply notes" must not invent a third delivery mechanism."""
    web.STATE.put(_house())
    _post(viewer, "/api/annotations", {"kind": "point", "pos": [2, 3, 2], "note": "a"})

    taken = {}
    thread = threading.Thread(target=lambda: taken.setdefault("p", PROMPTS.take(timeout=5)))
    thread.start()
    _wait_for(lambda: PROMPTS.listening)

    _status, body = _post(viewer, "/api/apply-notes", {})
    thread.join(timeout=5)

    assert body["notes"] == 1
    assert body["delivered"] is True
    assert "get_annotations" in taken["p"]["text"]
    # It appears in the transcript like any other prompt, so the user sees what
    # was asked on their behalf.
    assert CHAT.history()[-1]["role"] == "user"


def test_apply_notes_with_nothing_marked_is_refused(viewer):
    web.STATE.put(_house())
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post(viewer, "/api/apply-notes", {})
    assert excinfo.value.code == 400


def _wait_for(predicate, timeout=5.0, interval=0.02):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


# --------------------------------------------------------------------------- #
# The MCP tools — the loop as Claude drives it
# --------------------------------------------------------------------------- #

def _call(tool, arguments=None):
    import asyncio

    from minecraft_builder.server import call_tool

    return asyncio.run(call_tool(tool, arguments or {}))[0].text


def _pitched_roof():
    """A replacement for the flat roof, using the real PyramidOp field names."""
    return {
        "op": "pyramid", "center": [2, 3, 2], "base": 2, "block": "oak_planks",
    }


def test_get_annotations_says_so_plainly_when_there_are_none(viewer):
    text = _call("get_annotations")
    assert "No notes" in text
    # Claude must not be tempted to invent what the user meant.
    assert "say so" in text


def test_get_annotations_reports_the_operation_to_edit(viewer):
    web.STATE.put(_house())
    _post(viewer, "/api/annotations",
          {"kind": "point", "pos": [2, 3, 2], "note": "roof is too flat"})
    text = _call("get_annotations")
    assert "roof is too flat" in text
    assert f"operation #{ROOF}" in text
    assert "cuboid" in text          # the label, so no second lookup is needed
    assert "patch_operations" in text  # and what to do about it


def test_get_annotations_warns_when_a_note_predates_the_current_version(viewer):
    web.STATE.put(_house())
    _post(viewer, "/api/annotations",
          {"kind": "point", "pos": [2, 3, 2], "note": "roof"})
    web.STATE.put(_house())  # a revision the note was not drawn on
    text = _call("get_annotations")
    assert "re-check this index" in text


def test_get_annotations_hides_resolved_notes_by_default(viewer):
    web.STATE.put(_house())
    _post(viewer, "/api/annotations", {"kind": "point", "pos": [2, 3, 2], "note": "old"})
    ANNOTATIONS.resolve()
    assert "No notes" in _call("get_annotations")
    assert "old" in _call("get_annotations", {"include_resolved": True})


def test_resolve_annotations_closes_the_tray(viewer):
    web.STATE.put(_house())
    _post(viewer, "/api/annotations", {"kind": "point", "pos": [2, 3, 2], "note": "a"})
    text = _call("resolve_annotations")
    assert "Closed note" in text
    assert "tray is now clear" in text
    assert ANNOTATIONS.counts() == (0, 1)


def test_resolve_annotations_reports_what_is_left(viewer):
    web.STATE.put(_house())
    _, first = _post(viewer, "/api/annotations",
                     {"kind": "point", "pos": [2, 3, 2], "note": "a"})
    _post(viewer, "/api/annotations", {"kind": "point", "pos": [0, 0, 0], "note": "b"})
    text = _call("resolve_annotations", {"ids": [first["annotation"]["id"]]})
    assert "1 still open" in text


def test_resolve_annotations_with_no_match_changes_nothing(viewer):
    assert "nothing changed" in _call("resolve_annotations", {"ids": [999]})


def test_patch_operations_revises_the_build_and_shows_it(viewer):
    before = web.STATE.put(_house())
    text = _call("patch_operations", {"patches": [
        {"index": ROOF, "action": "replace", "operation": _pitched_roof()},
    ]})
    assert "❌" not in text, text
    assert "Patched" in text
    # A new version was stored and announced, so the page has already updated.
    assert web.STATE.version == before + 1
    assert "do not call show_structure" in text
    current = web.STATE.current()
    assert current.operations[ROOF].op == "pyramid"


def test_patch_operations_with_nothing_on_screen_is_an_error(viewer):
    text = _call("patch_operations", {"patches": [{"index": 0, "action": "delete"}]})
    assert "❌" in text
    assert "show_structure" in text


def test_patch_operations_returns_a_correctable_error_not_a_traceback(viewer):
    web.STATE.put(_house())
    text = _call("patch_operations", {"patches": [{"index": 99, "action": "delete"}]})
    assert "❌" in text
    assert "99" in text
    assert "Traceback" not in text


def test_patch_operations_rejects_an_empty_patch_list(viewer):
    web.STATE.put(_house())
    assert "❌" in _call("patch_operations", {"patches": []})


def test_the_whole_loop(viewer):
    """Mark, apply, patch, resolve — the feature end to end."""
    web.STATE.put(_house())

    # 1. The user clicks the roof and leaves a note.
    _, created = _post(viewer, "/api/annotations", {
        "kind": "point", "pos": [2, 3, 2], "note": "roof should be pitched",
    })
    note_id = created["annotation"]["id"]
    assert created["annotation"]["op_index"] == ROOF

    # 2. ...then presses "Apply notes", which prompts Claude the ordinary way.
    _post(viewer, "/api/apply-notes", {})
    assert "get_annotations" in PROMPTS.take(timeout=1)["text"]

    # 3. Claude reads them and learns which operation to edit.
    assert f"operation #{ROOF}" in _call("get_annotations")

    # 4. Claude edits exactly that operation.
    patch_result = _call("patch_operations", {"patches": [
        {"index": ROOF, "action": "replace", "operation": _pitched_roof()},
    ]})
    assert "❌" not in patch_result, patch_result
    patched = web.STATE.current()
    assert patched.operations[ROOF].op == "pyramid"
    # The parts the user did not complain about are untouched, which is the
    # entire argument for patching over regenerating.
    assert patched.operations[FLOOR].block == "stone"
    assert patched.operations[WALLS].op == "hollow_box"

    # 5. Claude closes the note, and the tray empties.
    _call("resolve_annotations", {"ids": [note_id]})
    assert _get(viewer, "/api/status")["notes_open"] == 0
