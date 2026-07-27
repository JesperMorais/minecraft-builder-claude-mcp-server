"""Tests for structure expansion, layering, and size calculation."""

import pytest

from minecraft_builder.schema import MinecraftStructure


def test_blocks_only_expansion():
    s = MinecraftStructure(
        name="pair",
        blocks=[
            {"x": 0, "y": 0, "z": 0, "block_type": "stone"},
            {"x": 1, "y": 0, "z": 0, "block_type": "dirt"},
        ],
    )
    m = s.expand()
    assert m == {(0, 0, 0): "stone", (1, 0, 0): "dirt"}


def test_operation_expands_to_blocks():
    s = MinecraftStructure(
        name="wall",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 0], "block": "stone"}],
    )
    assert len(s.expand()) == 3


def test_later_operations_overwrite_earlier():
    # Fill a solid box, then carve a hole with air.
    s = MinecraftStructure(
        name="carved",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 2, 2], "block": "stone"},
            {"op": "block", "pos": [1, 1, 1], "block": "air"},
        ],
    )
    assert s.expand()[(1, 1, 1)] == "air"


def test_replace_only_touches_matching_blocks():
    s = MinecraftStructure(
        name="swap",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 0], "block": "stone"},
            {"op": "block", "pos": [1, 0, 0], "block": "dirt"},
            {"op": "replace", "start": [0, 0, 0], "end": [2, 0, 0],
             "from_block": "stone", "to_block": "glass"},
        ],
    )
    m = s.expand()
    assert m[(0, 0, 0)] == "glass"
    assert m[(1, 0, 0)] == "dirt"  # untouched, wasn't stone
    assert m[(2, 0, 0)] == "glass"


def test_replace_ignores_block_state_suffix():
    s = MinecraftStructure(
        name="statey",
        operations=[
            {"op": "block", "pos": [0, 0, 0], "block": "minecraft:oak_log[axis=y]"},
            {"op": "replace", "start": [0, 0, 0], "end": [0, 0, 0],
             "from_block": "oak_log", "to_block": "air"},
        ],
    )
    assert s.expand()[(0, 0, 0)] == "air"


def test_size_from_bounds_including_negatives():
    s = MinecraftStructure(
        name="neg",
        blocks=[
            {"x": -2, "y": 0, "z": 0, "block_type": "stone"},
            {"x": 2, "y": 3, "z": 1, "block_type": "stone"},
        ],
    )
    size = s.calculate_size()
    assert (size.width, size.height, size.length) == (5, 4, 2)


def test_empty_structure_size():
    s = MinecraftStructure(name="empty")
    size = s.calculate_size()
    assert (size.width, size.height, size.length) == (0, 0, 0)


def test_unknown_op_rejected():
    with pytest.raises(Exception):
        MinecraftStructure(name="bad", operations=[{"op": "spiral", "block": "stone"}])


def test_new_geometry_ops_expand():
    # Each new op should route through the discriminated union and place blocks.
    ops = [
        {"op": "dome", "center": [0, 0, 0], "radius": 4, "block": "quartz_block"},
        {"op": "cone", "center": [20, 0, 0], "radius": 3, "height": 6, "block": "stone"},
        {"op": "ellipsoid", "center": [40, 0, 0], "rx": 5, "ry": 2, "rz": 3, "block": "glass"},
        {"op": "torus", "center": [60, 0, 0], "major_radius": 6, "minor_radius": 2, "block": "gold_block"},
    ]
    for op in ops:
        s = MinecraftStructure(name=op["op"], operations=[op])
        block_map = s.expand()
        assert block_map, f"{op['op']} produced no blocks"
        assert set(block_map.values()) == {op["block"]}


def test_new_ops_respect_hollow_and_layering():
    # A solid dome then a hollow dome carved into air still leaves a shell.
    s = MinecraftStructure(name="dome", operations=[
        {"op": "dome", "center": [0, 0, 0], "radius": 5, "block": "stone", "hollow": True},
    ])
    solid = MinecraftStructure(name="d2", operations=[
        {"op": "dome", "center": [0, 0, 0], "radius": 5, "block": "stone"},
    ])
    assert len(s.expand()) < len(solid.expand())


def test_torus_requires_positive_radii():
    with pytest.raises(Exception):
        MinecraftStructure(name="t", operations=[
            {"op": "torus", "center": [0, 0, 0], "major_radius": 0, "minor_radius": 2, "block": "stone"},
        ])
