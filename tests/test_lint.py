"""Tests for the programmatic style checks in lint.py."""

import pytest

from minecraft_builder.lint import (
    Finding,
    family,
    format_report,
    is_light,
    lint_structure,
)
from minecraft_builder.schema import MinecraftStructure


def _rules(findings, severity=None):
    return {f.rule for f in findings if severity is None or f.severity == severity}


def _plain_box(size=12, height=6, block="oak_planks"):
    """The guide's worked anti-pattern: one material, solid, square, dark."""
    return MinecraftStructure(
        name="box",
        operations=[{
            "op": "cuboid",
            "start": [0, 0, 0],
            "end": [size - 1, height - 1, size - 1],
            "block": block,
        }],
    )


def _decent_cottage():
    """Small build that follows the guide: 3+ materials, stairs, lights,
    carved interior, oblong footprint, broken-up facades."""
    ops = [
        {"op": "cuboid", "start": [0, 0, 0], "end": [11, 0, 7], "block": "cobblestone"},
        {"op": "hollow_box", "start": [0, 1, 0], "end": [11, 4, 7],
         "block": "oak_planks", "floor": False, "ceiling": False},
        # Windows break every facade before it reaches a 9-long flat run.
        {"op": "cuboid", "start": [2, 2, 0], "end": [3, 3, 0], "block": "glass_pane"},
        {"op": "cuboid", "start": [8, 2, 0], "end": [9, 3, 0], "block": "glass_pane"},
        {"op": "cuboid", "start": [2, 2, 7], "end": [3, 3, 7], "block": "glass_pane"},
        {"op": "cuboid", "start": [8, 2, 7], "end": [9, 3, 7], "block": "glass_pane"},
        {"op": "cuboid", "start": [0, 2, 3], "end": [0, 3, 4], "block": "glass_pane"},
        {"op": "cuboid", "start": [11, 2, 3], "end": [11, 3, 4], "block": "glass_pane"},
        {"op": "cuboid", "start": [5, 1, 0], "end": [6, 3, 0], "block": "air"},
        # Stepped stair roof, different material from the walls.
        {"op": "cuboid", "start": [-1, 5, -1], "end": [12, 5, -1], "block": "brick_stairs[facing=south]"},
        {"op": "cuboid", "start": [-1, 5, 8], "end": [12, 5, 8], "block": "brick_stairs[facing=north]"},
        {"op": "cuboid", "start": [-1, 5, 0], "end": [12, 5, 7], "block": "spruce_planks"},
        {"op": "cuboid", "start": [-1, 6, 0], "end": [12, 6, 0], "block": "brick_stairs[facing=south]"},
        {"op": "cuboid", "start": [-1, 6, 7], "end": [12, 6, 7], "block": "brick_stairs[facing=north]"},
        {"op": "cuboid", "start": [-1, 7, 1], "end": [12, 7, 1], "block": "brick_stairs[facing=south]"},
        {"op": "cuboid", "start": [-1, 7, 6], "end": [12, 7, 6], "block": "brick_stairs[facing=north]"},
        {"op": "cuboid", "start": [-1, 7, 2], "end": [12, 7, 5], "block": "bricks"},
        {"op": "block", "pos": [4, 1, -1], "block": "lantern"},
        {"op": "block", "pos": [7, 1, -1], "block": "lantern"},
        {"op": "block", "pos": [5, 3, 3], "block": "lantern[hanging=true]"},
    ]
    return MinecraftStructure(name="cottage", operations=ops)


# --------------------------------------------------------------------------- #
# Family and light classification
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("block,expected", [
    ("bricks", "brick"),
    ("brick_stairs[facing=south]", "brick"),
    ("brick_slab[type=bottom]", "brick"),
    ("stone_bricks", "stone_brick"),
    ("stone_brick_stairs", "stone_brick"),
    ("minecraft:cobblestone_slab", "cobblestone"),
    ("oak_planks", "oak_plank"),
    ("oak_fence", "oak_plank"),
    ("oak_door[half=upper]", "oak_plank"),
    ("spruce_trapdoor", "spruce_plank"),
    ("glass", "glass"),
    ("glass_pane", "glass"),
])
def test_shape_variants_collapse_into_their_material(block, expected):
    assert family(block) == expected


@pytest.mark.parametrize("block,lit", [
    ("lantern[hanging=true]", True),
    ("sea_lantern", True),
    ("soul_torch", True),
    ("campfire", True),
    ("verdant_froglight", True),
    ("stone", False),
    ("oak_planks", False),
])
def test_light_classification(block, lit):
    assert is_light(block) is lit


# --------------------------------------------------------------------------- #
# The anti-pattern box trips the guide's core rules
# --------------------------------------------------------------------------- #

def test_plain_box_trips_the_core_anti_patterns():
    findings = lint_structure(_plain_box())
    warns = _rules(findings, "warn")
    assert "palette-size" in warns
    assert "palette-dominance" in warns
    assert "stairs-slabs" in warns
    assert "lighting" in warns
    assert "flat-face" in warns
    assert "interior" in warns


def test_plain_box_footprint_is_flagged_square():
    assert "footprint" in _rules(lint_structure(_plain_box()))


def test_flat_face_reports_size_and_side():
    finding = next(
        f for f in lint_structure(_plain_box()) if f.rule == "flat-face"
    )
    assert "12x" in finding.message


# --------------------------------------------------------------------------- #
# A guide-following build comes back without warnings
# --------------------------------------------------------------------------- #

def test_decent_cottage_has_no_warnings():
    findings = lint_structure(_decent_cottage())
    assert _rules(findings, "warn") == set(), [f.message for f in findings]


def test_hollow_interior_counts_as_carved():
    findings = lint_structure(_decent_cottage())
    assert "interior" not in _rules(findings)


# --------------------------------------------------------------------------- #
# Individual rules
# --------------------------------------------------------------------------- #

def test_windows_break_a_flat_face():
    box = _plain_box()
    broken = MinecraftStructure(
        name="broken",
        operations=box.operations + [
            {"op": "cuboid", "start": [3, 1, 0], "end": [4, 4, 0], "block": "glass_pane"},
            {"op": "cuboid", "start": [8, 1, 0], "end": [9, 4, 0], "block": "glass_pane"},
        ],
    )
    sides = {
        f.message.split("on the ")[1][:2]
        for f in lint_structure(broken) if f.rule == "flat-face"
    }
    # The carved side no longer has a 9+ run; the untouched sides still do.
    assert "-Z" not in sides
    assert sides  # other faces are still flat


def test_interior_face_of_a_room_is_not_a_flat_face_violation():
    # A hollow 14x6x10 shell: outside faces flagged, but the finding must come
    # from the outside — carve the exterior and the rule goes quiet even
    # though the identical interior faces remain.
    shell_ops = [
        {"op": "hollow_box", "start": [0, 0, 0], "end": [13, 5, 9], "block": "stone_bricks"},
        {"op": "block", "pos": [2, 1, 2], "block": "lantern"},
    ]
    pillars = [
        {"op": "cuboid", "start": [x, 0, z], "end": [x, 5, z], "block": "air"}
        for x in range(2, 13, 3) for z in (0, 9)
    ] + [
        {"op": "cuboid", "start": [x, 0, z], "end": [x, 5, z], "block": "air"}
        for x in (0, 13) for z in range(2, 9, 3)
    ]
    carved = MinecraftStructure(name="carved", operations=shell_ops + pillars)
    assert "flat-face" not in _rules(lint_structure(carved))


def test_zero_lights_warns_and_one_light_downgrades():
    dark = lint_structure(_plain_box())
    lit_ops = _plain_box().operations + [
        {"op": "block", "pos": [0, 6, 0], "block": "lantern"},
    ]
    lit = lint_structure(MinecraftStructure(name="lit", operations=lit_ops))
    assert any(f.rule == "lighting" and f.severity == "warn" for f in dark)
    assert not any(f.rule == "lighting" and f.severity == "warn" for f in lit)


def test_roof_matching_walls_is_noted():
    ops = [
        {"op": "hollow_box", "start": [0, 0, 0], "end": [11, 3, 7], "block": "stone_bricks"},
        # A "roof" of the same stone the walls are made of.
        {"op": "cuboid", "start": [0, 4, 0], "end": [11, 6, 7], "block": "stone_brick_stairs"},
    ]
    findings = lint_structure(MinecraftStructure(name="mono", operations=ops))
    assert "roof-contrast" in _rules(findings)


def _steep_roofed_longhouse():
    """Nordic profile: three courses of wall under a 63-degree roof that takes
    the other ten. The roof reaches well below half the build's height."""
    ops = [
        {"op": "cuboid", "start": [0, 0, 0], "end": [19, 0, 9], "block": "stone_bricks"},
        {"op": "hollow_box", "start": [0, 1, 0], "end": [19, 3, 9],
         "block": "spruce_planks", "floor": False, "ceiling": False},
        {"op": "block", "pos": [3, 2, 0], "block": "lantern"},
    ]
    # Two courses of rise per course of run: z steps in by 1 every second y.
    for i in range(10):
        y, inset = 4 + i, i // 2
        ops += [
            {"op": "cuboid", "start": [-1, y, -1 + inset], "end": [20, y, -1 + inset],
             "block": "dark_oak_planks"},
            {"op": "cuboid", "start": [-1, y, 10 - inset], "end": [20, y, 10 - inset],
             "block": "dark_oak_planks"},
        ]
    return MinecraftStructure(name="longhouse", operations=ops)


def test_a_steep_roof_is_not_read_as_matching_the_walls():
    """The bug this rule had: sampling the walls at a fixed fraction of the
    height lands inside a roof this steep and compares it against itself."""
    findings = lint_structure(_steep_roofed_longhouse())
    assert "roof-contrast" not in _rules(findings)


def test_a_roof_sharing_only_the_foundation_material_is_not_flagged():
    """Stone footings under a stone-slab roof, with timber walls between: the
    top and the base match, but nothing about the build is monochrome."""
    ops = [
        {"op": "cuboid", "start": [0, 0, 0], "end": [13, 1, 9], "block": "stone_bricks"},
        {"op": "hollow_box", "start": [0, 2, 0], "end": [13, 7, 9],
         "block": "oak_planks", "floor": False, "ceiling": False},
        {"op": "cuboid", "start": [-1, 8, -1], "end": [14, 8, 10],
         "block": "stone_brick_slab[type=top]"},
        {"op": "block", "pos": [3, 4, 0], "block": "lantern"},
    ]
    findings = lint_structure(MinecraftStructure(name="footed", operations=ops))
    assert "roof-contrast" not in _rules(findings)


def test_block_spam_is_noted():
    structure = MinecraftStructure(
        name="spam",
        blocks=[
            {"x": x, "y": 0, "z": z, "block_type": "stone"}
            for x in range(15) for z in range(15)
        ],
    )
    assert "block-spam" in _rules(lint_structure(structure))


def test_small_builds_stay_quiet():
    tiny = MinecraftStructure(
        name="tiny",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [2, 2, 2], "block": "stone"}],
    )
    assert _rules(lint_structure(tiny), "warn") == set()


def test_report_formats_clean_and_dirty():
    assert "clean" in format_report([])
    report = format_report([
        Finding("lighting", "warn", "zero light sources"),
        Finding("footprint", "info", "nearly square"),
    ])
    assert "1 warning(s)" in report
    assert "1 note(s)" in report
    assert "[lighting]" in report
