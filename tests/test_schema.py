"""Tests for structure expansion, layering, size calculation, provenance and limits."""

import pytest
from pydantic import ValidationError

from minecraft_builder.schema import MinecraftStructure, StructureTooLargeError


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
    with pytest.raises(ValidationError):
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
    with pytest.raises(ValidationError):
        MinecraftStructure(name="t", operations=[
            {"op": "torus", "center": [0, 0, 0], "major_radius": 0, "minor_radius": 2, "block": "stone"},
        ])


# --------------------------------------------------------------------------- #
# Provenance: which operation last wrote each coordinate
# --------------------------------------------------------------------------- #

def test_provenance_block_map_matches_expand():
    s = MinecraftStructure(
        name="hut",
        operations=[
            {"op": "hollow_box", "start": [0, 0, 0], "end": [6, 4, 6],
             "block": "stone", "ceiling": False},
            {"op": "cuboid", "start": [3, 1, 0], "end": [3, 3, 0], "block": "air"},
        ],
    )
    block_map, origin = s.expand_with_provenance()
    assert block_map == s.expand()
    assert set(origin) == set(block_map)  # every coordinate is attributed


def test_provenance_attributes_carved_doorway_to_the_carving_op():
    s = MinecraftStructure(
        name="hut",
        operations=[
            {"op": "hollow_box", "start": [0, 0, 0], "end": [6, 4, 6],
             "block": "stone", "ceiling": False},
            {"op": "cuboid", "start": [3, 1, 0], "end": [3, 3, 0], "block": "air"},
        ],
    )
    _, origin = s.expand_with_provenance()
    assert origin[(3, 2, 0)] == 1  # carved by the second op
    assert origin[(6, 2, 3)] == 0  # plain wall from the hollow_box


def test_provenance_credits_later_op_on_identical_block_overwrite():
    # The case a before/after diff cannot see: the second op rewrites the same
    # coordinates with the *same* block id, but it is still the last writer.
    s = MinecraftStructure(
        name="overwrite",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 0], "block": "stone"},
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 0], "block": "stone"},
        ],
    )
    _, origin = s.expand_with_provenance()
    assert set(origin.values()) == {1}


def test_provenance_index_space_puts_explicit_blocks_first():
    s = MinecraftStructure(
        name="mixed",
        blocks=[
            {"x": 0, "y": 0, "z": 0, "block_type": "dirt"},
            {"x": 1, "y": 0, "z": 0, "block_type": "dirt"},
        ],
        operations=[{"op": "block", "pos": [5, 0, 0], "block": "stone"}],
    )
    _, origin = s.expand_with_provenance()
    assert origin[(0, 0, 0)] == 0
    assert origin[(1, 0, 0)] == 1
    assert origin[(5, 0, 0)] == 2  # operations continue after the blocks


def test_provenance_tracks_replace_and_negative_coordinates():
    s = MinecraftStructure(
        name="neg",
        operations=[
            {"op": "cuboid", "start": [-5, -2, -9], "end": [-3, -2, -9], "block": "stone"},
            {"op": "replace", "start": [-5, -2, -9], "end": [-3, -2, -9],
             "from_block": "stone", "to_block": "glass"},
        ],
    )
    block_map, origin = s.expand_with_provenance()
    assert block_map[(-4, -2, -9)] == "glass"
    assert origin[(-4, -2, -9)] == 1


def test_describe_operation_labels_blocks_and_ops():
    s = MinecraftStructure(
        name="mixed",
        blocks=[{"x": 0, "y": 1, "z": 2, "block_type": "dirt"}],
        operations=[{"op": "sphere", "center": [0, 0, 0], "radius": 2, "block": "glass"}],
    )
    assert s.describe_operation(0) == "block [0, 1, 2] = dirt"
    label = s.describe_operation(1)
    assert label.startswith("sphere ") and "radius=2" in label


# --------------------------------------------------------------------------- #
# Safety ceilings: refuse oversized structures before expansion allocates
# --------------------------------------------------------------------------- #

# Each entry is (operation, an upper bound we expect estimated_volume to respect).
_ALL_OPS = [
    {"op": "cuboid", "start": [0, 0, 0], "end": [4, 3, 2], "block": "stone"},
    {"op": "hollow_box", "start": [0, 0, 0], "end": [5, 5, 5], "block": "stone"},
    {"op": "sphere", "center": [0, 0, 0], "radius": 4, "block": "stone"},
    {"op": "sphere", "center": [0, 0, 0], "radius": 4, "block": "stone", "hollow": True},
    {"op": "cylinder", "center": [0, 0, 0], "radius": 3, "height": 5, "block": "stone"},
    {"op": "cylinder", "center": [0, 0, 0], "radius": 3, "height": 5, "axis": "x",
     "block": "stone", "hollow": True},
    {"op": "line", "start": [0, 0, 0], "end": [9, 3, 5], "block": "stone"},
    {"op": "pyramid", "center": [0, 0, 0], "base": 4, "block": "stone"},
    {"op": "pyramid", "center": [0, 0, 0], "base": 4, "axis": "z", "block": "stone",
     "hollow": True},
    {"op": "dome", "center": [0, 0, 0], "radius": 5, "block": "stone"},
    {"op": "dome", "center": [0, 0, 0], "radius": 5, "axis": "x", "block": "stone",
     "hollow": True},
    {"op": "cone", "center": [0, 0, 0], "radius": 4, "height": 7, "block": "stone"},
    {"op": "cone", "center": [0, 0, 0], "radius": 4, "height": 7, "axis": "z",
     "block": "stone", "hollow": True},
    {"op": "ellipsoid", "center": [0, 0, 0], "rx": 5, "ry": 2, "rz": 3, "block": "stone"},
    {"op": "ellipsoid", "center": [0, 0, 0], "rx": 5, "ry": 2, "rz": 3, "block": "stone",
     "hollow": True},
    {"op": "torus", "center": [0, 0, 0], "major_radius": 6, "minor_radius": 2,
     "block": "stone"},
    {"op": "torus", "center": [0, 0, 0], "major_radius": 6, "minor_radius": 2,
     "axis": "x", "block": "stone", "hollow": True},
    {"op": "block", "pos": [1, 2, 3], "block": "stone"},
    # replace adds no coordinates of its own, but still walks its whole region,
    # so its bound is the region volume.
    {"op": "replace", "start": [0, 0, 0], "end": [3, 3, 3],
     "from_block": "stone", "to_block": "glass"},
]


def _operation_classes():
    """Every concrete operation class in the discriminated union."""
    from typing import get_args

    from minecraft_builder.schema import Operation

    union = get_args(Operation)[0]  # Annotated[Union[...], Field(discriminator=...)]
    return list(get_args(union))


def test_every_operation_implements_volume_bound():
    """No operation may inherit the base class's NotImplementedError.

    This is the guard that matters: expand() routes through check_limits(), so an
    operation without a bound does not degrade — it raises on the most basic call
    in the library. Adding a shape and forgetting the bound is an easy mistake and
    merges cleanly, so it is caught here by construction rather than by remembering
    to extend a hand-written list.
    """
    from minecraft_builder.schema import _Operation

    missing = [
        cls.__name__
        for cls in _operation_classes()
        if cls.volume_bound is _Operation.volume_bound
    ]
    assert not missing, f"operations missing volume_bound(): {', '.join(missing)}"


def test_upper_bound_samples_cover_every_operation():
    """Keep _ALL_OPS in step with the union, so the bound check stays exhaustive."""
    from typing import Literal, get_args

    declared = set()
    for cls in _operation_classes():
        annotation = cls.model_fields["op"].annotation
        if get_args(annotation):  # Literal["cuboid"] -> ("cuboid",)
            declared.add(get_args(annotation)[0])
        else:  # pragma: no cover - defensive
            assert annotation is not Literal
    covered = {op["op"] for op in _ALL_OPS}
    assert declared - covered == set(), f"no volume-bound sample for: {declared - covered}"


@pytest.mark.parametrize("op", _ALL_OPS, ids=lambda o: f"{o['op']}-{o.get('axis', '')}{o.get('hollow', '')}")
def test_volume_bound_is_an_upper_bound_for_every_op(op):
    # The ceiling is only safe if the cheap estimate never under-counts what
    # expansion actually produces.
    s = MinecraftStructure(name="one", operations=[op])
    assert s.estimated_volume() >= len(s.expand())


def test_oversized_cuboid_is_refused_before_expansion():
    s = MinecraftStructure(
        name="typo",
        # A stray extra digit: 200001^3 would be ~8e15 blocks.
        operations=[{"op": "cuboid", "start": [-100000, -100000, -100000],
                     "end": [100000, 100000, 100000], "block": "stone"}],
    )
    with pytest.raises(StructureTooLargeError, match="coordinate typo"):
        s.expand()


def test_too_many_operations_is_refused():
    s = MinecraftStructure(
        name="many",
        operations=[{"op": "block", "pos": [i, 0, 0], "block": "stone"} for i in range(11)],
    )
    with pytest.raises(StructureTooLargeError, match="operations"):
        s.check_limits(max_operations=10)


def test_too_many_explicit_blocks_is_refused():
    s = MinecraftStructure(
        name="many",
        blocks=[{"x": i, "y": 0, "z": 0, "block_type": "stone"} for i in range(11)],
    )
    with pytest.raises(StructureTooLargeError, match="explicit blocks"):
        s.check_limits(max_blocks=10)


def test_limits_allow_a_normal_build():
    s = MinecraftStructure(
        name="cottage",
        operations=[
            {"op": "hollow_box", "start": [0, 0, 0], "end": [8, 6, 6], "block": "oak_planks"},
            {"op": "cuboid", "start": [4, 1, 0], "end": [4, 3, 0], "block": "air"},
        ],
    )
    s.check_limits()  # must not raise
    assert len(s.expand()) > 0
