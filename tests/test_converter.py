"""Tests for JSON -> .schem and .litematic conversion."""

import pytest
from mcschematic import MCSchematic

from minecraft_builder.converter import SchematicConverter
from minecraft_builder.schema import MinecraftStructure, StructureTooLargeError


def test_normalize_block_id():
    n = SchematicConverter.normalize_block_id
    assert n("stone") == "minecraft:stone"
    assert n("minecraft:stone") == "minecraft:stone"
    assert n("oak_log[axis=y]") == "minecraft:oak_log[axis=y]"
    assert n("minecraft:oak_log[axis=y]") == "minecraft:oak_log[axis=y]"


def test_split_block_state():
    s = SchematicConverter.split_block_state
    assert s("stone") == ("minecraft:stone", {})
    assert s("oak_log[axis=y]") == ("minecraft:oak_log", {"axis": "y"})
    assert s("minecraft:oak_stairs[facing=north,half=top]") == (
        "minecraft:oak_stairs",
        {"facing": "north", "half": "top"},
    )
    # Whitespace inside the brackets is tolerated.
    assert s("oak_log[ axis = y ]") == ("minecraft:oak_log", {"axis": "y"})


def test_split_block_state_rejects_malformed_state():
    # Silently dropping this would write a block with the wrong state, so it
    # has to fail loudly enough for the caller to fix the ID.
    with pytest.raises(ValueError, match="Malformed block state"):
        SchematicConverter.split_block_state("oak_log[axis]")


def test_creates_schem_file(tmp_path):
    structure = MinecraftStructure(
        name="platform",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 2], "block": "stone"}],
    )
    out = tmp_path / "platform.schem"
    path = SchematicConverter.to_schematic(structure, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    assert path.endswith("platform.schem")


def test_negative_coordinates_are_preserved(tmp_path):
    # Regression: blocks at negative coords used to be silently dropped.
    structure = MinecraftStructure(
        name="neg",
        blocks=[
            {"x": -3, "y": -1, "z": -2, "block_type": "stone"},
            {"x": 0, "y": 0, "z": 0, "block_type": "dirt"},
        ],
    )
    out = tmp_path / "neg.schem"
    SchematicConverter.to_schematic(structure, str(out))

    # Load it back and confirm both blocks survived, offset to the origin.
    loaded = MCSchematic(schematicToLoadPath_or_mcStructure=str(out))
    # Minimum corner was (-3, -1, -2) so it should map to (0, 0, 0).
    assert "minecraft:stone" in loaded.getBlockDataAt((0, 0, 0))
    assert "minecraft:dirt" in loaded.getBlockDataAt((3, 1, 2))


# --------------------------------------------------------------------------- #
# .litematic (Litematica blueprint) export
# --------------------------------------------------------------------------- #

def _load_region(path):
    """Load a .litematic and return its single region."""
    from litemapy import Schematic

    return next(iter(Schematic.load(str(path)).regions.values()))


def test_creates_litematic_file(tmp_path):
    structure = MinecraftStructure(
        name="platform",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 2], "block": "stone"}],
    )
    out = tmp_path / "platform.litematic"
    path = SchematicConverter.to_litematic(structure, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    assert path.endswith("platform.litematic")


def test_litematic_round_trip_matches_expanded_block_map(tmp_path):
    # The whole point of the format is that it reproduces the build, so compare
    # what was written against the block map it was written from. Air is skipped:
    # unset voxels read back as air, so explicit air is indistinguishable.
    structure = MinecraftStructure(
        name="hut",
        operations=[
            {"op": "hollow_box", "start": [0, 0, 0], "end": [4, 3, 4],
             "block": "stone", "ceiling": False},
            {"op": "cuboid", "start": [2, 1, 0], "end": [2, 2, 0], "block": "air"},
            {"op": "block", "pos": [0, 0, 0], "block": "oak_log[axis=y]"},
        ],
    )
    out = tmp_path / "hut.litematic"
    SchematicConverter.to_litematic(structure, str(out))

    block_map = structure.expand()
    min_x = min(c[0] for c in block_map)
    min_y = min(c[1] for c in block_map)
    min_z = min(c[2] for c in block_map)

    region = _load_region(out)
    compared = 0
    for (x, y, z), block_type in block_map.items():
        expected = SchematicConverter.normalize_block_id(block_type)
        if expected.startswith("minecraft:air"):
            continue
        actual = region[x - min_x, y - min_y, z - min_z].to_block_state_identifier()
        assert actual == expected, f"mismatch at {(x, y, z)}"
        compared += 1
    assert compared > 0


def test_litematic_preserves_block_states(tmp_path):
    structure = MinecraftStructure(
        name="stairs",
        blocks=[{"x": 0, "y": 0, "z": 0, "block_type": "oak_stairs[facing=north,half=top]"}],
    )
    out = tmp_path / "stairs.litematic"
    SchematicConverter.to_litematic(structure, str(out))
    identifier = _load_region(out)[0, 0, 0].to_block_state_identifier()
    assert identifier.startswith("minecraft:oak_stairs[")
    assert "facing=north" in identifier and "half=top" in identifier


def test_litematic_preserves_negative_coordinates(tmp_path):
    structure = MinecraftStructure(
        name="neg",
        blocks=[
            {"x": -3, "y": -1, "z": -2, "block_type": "stone"},
            {"x": 0, "y": 0, "z": 0, "block_type": "dirt"},
        ],
    )
    out = tmp_path / "neg.litematic"
    SchematicConverter.to_litematic(structure, str(out))
    region = _load_region(out)
    assert (region.width, region.height, region.length) == (4, 2, 3)
    assert region[0, 0, 0].to_block_state_identifier() == "minecraft:stone"
    assert region[3, 1, 2].to_block_state_identifier() == "minecraft:dirt"


def test_litematic_handles_empty_structure(tmp_path):
    # litemapy rejects a zero-sized region, so an empty build becomes 1x1x1 air
    # rather than an exception from deep inside the library.
    out = tmp_path / "empty.litematic"
    SchematicConverter.to_litematic(MinecraftStructure(name="empty"), str(out))
    region = _load_region(out)
    assert (region.width, region.height, region.length) == (1, 1, 1)
    assert region[0, 0, 0].to_block_state_identifier() == "minecraft:air"


def test_litematic_rejects_unsupported_version(tmp_path):
    structure = MinecraftStructure(
        name="x", blocks=[{"x": 0, "y": 0, "z": 0, "block_type": "stone"}]
    )
    with pytest.raises(ValueError, match="Unsupported Minecraft version"):
        SchematicConverter.to_litematic(structure, str(tmp_path / "x.litematic"), "1.7.10")


# --------------------------------------------------------------------------- #
# write_formats: the single entry point both the MCP server and the web UI use
# --------------------------------------------------------------------------- #

def _hut():
    return MinecraftStructure(
        name="hut",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [2, 0, 2], "block": "stone"}],
    )


def test_write_formats_defaults_to_schem_only(tmp_path):
    written = SchematicConverter.write_formats(_hut(), tmp_path, "hut")
    assert list(written) == ["schem"]
    assert (tmp_path / "hut.schem").exists()
    assert not (tmp_path / "hut.litematic").exists()


def test_write_formats_writes_both_and_preserves_order(tmp_path):
    written = SchematicConverter.write_formats(
        _hut(), tmp_path, "hut", formats=["litematic", "schem"]
    )
    assert list(written) == ["litematic", "schem"]
    assert (tmp_path / "hut.schem").exists()
    assert (tmp_path / "hut.litematic").exists()


def test_write_formats_dedupes_and_creates_missing_directory(tmp_path):
    nested = tmp_path / "a" / "b"
    written = SchematicConverter.write_formats(
        _hut(), nested, "hut", formats=["schem", "schem"]
    )
    assert list(written) == ["schem"]
    assert (nested / "hut.schem").exists()


def test_write_formats_rejects_unknown_and_empty_formats(tmp_path):
    with pytest.raises(ValueError, match="Unknown output format"):
        SchematicConverter.write_formats(_hut(), tmp_path, "hut", formats=["nbt"])
    with pytest.raises(ValueError, match="No output format requested"):
        SchematicConverter.write_formats(_hut(), tmp_path, "hut", formats=[])


def test_write_formats_writes_nothing_when_structure_is_too_large(tmp_path):
    # The size check runs once up front so a refused build can't leave a
    # half-written set of files behind.
    huge = MinecraftStructure(
        name="typo",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [200000, 200000, 200000],
                     "block": "stone"}],
    )
    with pytest.raises(StructureTooLargeError):
        SchematicConverter.write_formats(
            huge, tmp_path, "typo", formats=["schem", "litematic"]
        )
    assert list(tmp_path.iterdir()) == []


def test_oversized_structure_refused_by_both_writers(tmp_path):
    structure = MinecraftStructure(
        name="typo",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [200000, 200000, 200000],
                     "block": "stone"}],
    )
    with pytest.raises(StructureTooLargeError):
        SchematicConverter.to_schematic(structure, str(tmp_path / "a.schem"))
    with pytest.raises(StructureTooLargeError):
        SchematicConverter.to_litematic(structure, str(tmp_path / "a.litematic"))
