"""Tests for targeted operation edits.

The property that matters most here is that indices refer to the *pre-patch*
structure. Applying patches sequentially and letting each shift the next is the
obvious implementation and it silently corrupts a batch — a delete makes every
later index off by one. Several tests below exist only to pin that down.
"""

import pytest

from minecraft_builder.patches import PatchError, apply_patches
from minecraft_builder.schema import MinecraftStructure, StructureTooLargeError


def _structure(*operations, blocks=None, name="hut"):
    return MinecraftStructure(
        name=name,
        blocks=blocks or [],
        operations=list(operations),
    )


def _cuboid(block="stone", start=(0, 0, 0), end=(2, 2, 2)):
    return {"op": "cuboid", "start": list(start), "end": list(end), "block": block}


def _labels(structure):
    total = len(structure.blocks) + len(structure.operations)
    return [structure.describe_operation(i) for i in range(total)]


# --------------------------------------------------------------------------- #
# Single edits
# --------------------------------------------------------------------------- #

def test_replace_swaps_one_operation_and_leaves_the_rest():
    structure = _structure(_cuboid("stone"), _cuboid("oak_planks"), _cuboid("glass"))
    patched = apply_patches(structure, [
        {"index": 1, "action": "replace", "operation": _cuboid("bricks")},
    ])
    blocks = [op.block for op in patched.operations]
    assert blocks == ["stone", "bricks", "glass"]
    # The input is never mutated; the caller may still need the old version.
    assert [op.block for op in structure.operations] == ["stone", "oak_planks", "glass"]


def test_delete_removes_one_operation():
    structure = _structure(_cuboid("stone"), _cuboid("oak_planks"), _cuboid("glass"))
    patched = apply_patches(structure, [{"index": 1, "action": "delete"}])
    assert [op.block for op in patched.operations] == ["stone", "glass"]


def test_insert_goes_before_the_named_index():
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    patched = apply_patches(structure, [
        {"index": 1, "action": "insert", "operation": _cuboid("bricks")},
    ])
    assert [op.block for op in patched.operations] == ["stone", "bricks", "glass"]


def test_insert_at_the_count_appends():
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    patched = apply_patches(structure, [
        {"index": 2, "action": "insert", "operation": _cuboid("bricks")},
    ])
    assert [op.block for op in patched.operations] == ["stone", "glass", "bricks"]


# --------------------------------------------------------------------------- #
# Batches — indices must not shift under each other
# --------------------------------------------------------------------------- #

def test_a_delete_does_not_shift_a_later_replace():
    # The bug this guards: apply sequentially and "replace #2" lands on what was
    # #3, so the user's second note silently edits the wrong operation.
    structure = _structure(
        _cuboid("stone"), _cuboid("oak_planks"), _cuboid("glass"), _cuboid("dirt"),
    )
    patched = apply_patches(structure, [
        {"index": 0, "action": "delete"},
        {"index": 2, "action": "replace", "operation": _cuboid("bricks")},
    ])
    # #2 was glass, so glass becomes bricks and dirt is untouched.
    assert [op.block for op in patched.operations] == ["oak_planks", "bricks", "dirt"]


def test_two_deletes_both_land():
    structure = _structure(
        _cuboid("stone"), _cuboid("oak_planks"), _cuboid("glass"), _cuboid("dirt"),
    )
    patched = apply_patches(structure, [
        {"index": 0, "action": "delete"},
        {"index": 2, "action": "delete"},
    ])
    assert [op.block for op in patched.operations] == ["oak_planks", "dirt"]


def test_insert_and_delete_at_the_same_index_both_apply():
    # Insert goes before the index, delete removes it: the net effect is a
    # substitution that keeps the position.
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    patched = apply_patches(structure, [
        {"index": 1, "action": "insert", "operation": _cuboid("bricks")},
        {"index": 1, "action": "delete"},
    ])
    assert [op.block for op in patched.operations] == ["stone", "bricks"]


def test_patch_order_in_the_list_does_not_matter():
    structure = _structure(_cuboid("stone"), _cuboid("oak_planks"), _cuboid("glass"))
    forward = [
        {"index": 0, "action": "delete"},
        {"index": 2, "action": "replace", "operation": _cuboid("bricks")},
    ]
    reversed_order = list(reversed(forward))
    assert (
        [op.block for op in apply_patches(structure, forward).operations]
        == [op.block for op in apply_patches(structure, reversed_order).operations]
    )


# --------------------------------------------------------------------------- #
# The unified index space, blocks included
# --------------------------------------------------------------------------- #

def test_indices_span_blocks_then_operations():
    # Same space as expand_with_provenance() and get_annotations, so an op_index
    # can be handed straight to a patch with no translation.
    structure = _structure(
        _cuboid("stone"),
        blocks=[{"x": 0, "y": 0, "z": 0, "block_type": "torch"}],
    )
    assert _labels(structure) == ["block [0, 0, 0] = torch", structure.describe_operation(1)]

    patched = apply_patches(structure, [{"index": 0, "action": "delete"}])
    assert patched.blocks == []
    assert len(patched.operations) == 1


def test_a_block_can_be_replaced_by_a_block():
    structure = _structure(
        _cuboid("stone"),
        blocks=[{"x": 0, "y": 0, "z": 0, "block_type": "torch"}],
    )
    patched = apply_patches(structure, [
        {"index": 0, "action": "replace",
         "operation": {"x": 5, "y": 1, "z": 5, "block_type": "lantern"}},
    ])
    assert len(patched.blocks) == 1
    assert patched.blocks[0].block_type == "lantern"
    assert patched.blocks[0].x == 5


# --------------------------------------------------------------------------- #
# Rejections — the message is what Claude reads to correct itself
# --------------------------------------------------------------------------- #

def test_index_past_the_end_is_rejected_with_the_real_range():
    structure = _structure(_cuboid("stone"))
    with pytest.raises(PatchError) as excinfo:
        apply_patches(structure, [{"index": 7, "action": "delete"}])
    assert "7" in str(excinfo.value)
    assert "0..0" in str(excinfo.value)


def test_insert_may_target_one_past_the_end_but_not_two():
    structure = _structure(_cuboid("stone"))
    apply_patches(structure, [
        {"index": 1, "action": "insert", "operation": _cuboid("glass")},
    ])
    with pytest.raises(PatchError):
        apply_patches(structure, [
            {"index": 2, "action": "insert", "operation": _cuboid("glass")},
        ])


def test_replace_without_an_operation_is_rejected():
    with pytest.raises(PatchError, match="needs an operation"):
        apply_patches(_structure(_cuboid()), [{"index": 0, "action": "replace"}])


def test_replacing_the_same_index_twice_is_rejected():
    # Ambiguous rather than harmless: nothing says which one wins.
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    with pytest.raises(PatchError, match="replaced twice"):
        apply_patches(structure, [
            {"index": 0, "action": "replace", "operation": _cuboid("bricks")},
            {"index": 0, "action": "replace", "operation": _cuboid("dirt")},
        ])


def test_deleting_and_replacing_the_same_index_is_rejected():
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    with pytest.raises(PatchError, match="both deleted and replaced"):
        apply_patches(structure, [
            {"index": 0, "action": "delete"},
            {"index": 0, "action": "replace", "operation": _cuboid("bricks")},
        ])


def test_an_invalid_operation_names_the_patch_that_carried_it():
    structure = _structure(_cuboid("stone"), _cuboid("glass"))
    with pytest.raises(PatchError) as excinfo:
        apply_patches(structure, [
            {"index": 0, "action": "replace", "operation": _cuboid("bricks")},
            {"index": 1, "action": "replace", "operation": {"op": "cuboid"}},
        ])
    assert "patch 1" in str(excinfo.value)


def test_a_payload_with_no_op_field_says_so():
    with pytest.raises(PatchError, match='needs an "op" field'):
        apply_patches(_structure(_cuboid()), [
            {"index": 0, "action": "replace", "operation": {"start": [0, 0, 0]}},
        ])


def test_an_unknown_action_is_rejected():
    with pytest.raises(PatchError):
        apply_patches(_structure(_cuboid()), [{"index": 0, "action": "reticulate"}])


def test_deleting_everything_is_rejected():
    # An empty structure renders as nothing, and "your build vanished" is a worse
    # outcome than a refusal Claude can react to.
    with pytest.raises(PatchError, match="leave the structure empty"):
        apply_patches(_structure(_cuboid()), [{"index": 0, "action": "delete"}])


def test_a_patch_that_breaches_the_voxel_cap_is_caught():
    # The result goes back through the model, so caps apply to patched structures
    # exactly as they do to incoming ones.
    structure = _structure(_cuboid("stone"))
    with pytest.raises(StructureTooLargeError):
        apply_patches(structure, [{
            "index": 0, "action": "replace",
            "operation": _cuboid("stone", (0, 0, 0), (10_000, 10_000, 10_000)),
        }])


def test_name_and_description_survive_patching():
    structure = MinecraftStructure(
        name="pagoda", description="three tiers", operations=[_cuboid("stone")],
    )
    patched = apply_patches(structure, [
        {"index": 0, "action": "replace", "operation": _cuboid("bricks")},
    ])
    assert patched.name == "pagoda"
    assert patched.description == "three tiers"


def test_patching_actually_changes_what_gets_drawn():
    # End to end: the point of a patch is a different build, not a different list.
    structure = _structure(_cuboid("stone", (0, 0, 0), (1, 1, 1)))
    before = set(structure.expand().values())
    patched = apply_patches(structure, [
        {"index": 0, "action": "replace",
         "operation": _cuboid("oak_planks", (0, 0, 0), (1, 1, 1))},
    ])
    assert before == {"stone"}
    assert set(patched.expand().values()) == {"oak_planks"}
