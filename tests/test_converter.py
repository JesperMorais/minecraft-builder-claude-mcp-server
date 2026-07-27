"""Tests for JSON -> .schem conversion."""

from mcschematic import MCSchematic

from minecraft_builder.converter import SchematicConverter
from minecraft_builder.schema import MinecraftStructure


def test_normalize_block_id():
    n = SchematicConverter.normalize_block_id
    assert n("stone") == "minecraft:stone"
    assert n("minecraft:stone") == "minecraft:stone"
    assert n("oak_log[axis=y]") == "minecraft:oak_log[axis=y]"
    assert n("minecraft:oak_log[axis=y]") == "minecraft:oak_log[axis=y]"


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
