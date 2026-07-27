"""Tests for version support and block-ID validation."""

import pytest

from minecraft_builder import versions
from minecraft_builder.schema import MinecraftStructure
from minecraft_builder.converter import SchematicConverter


def test_supported_versions_map_to_mcschematic():
    for ver in versions.SUPPORTED_VERSIONS:
        # Raises if the enum member is missing.
        assert versions.mcschematic_version(ver) is not None


def test_normalize_rejects_unknown_version():
    with pytest.raises(ValueError, match="Unsupported"):
        versions.normalize_version("1.7.10")


def test_block_lists_load_and_contain_core_blocks():
    for ver in versions.SUPPORTED_VERSIONS:
        ids = versions.load_block_ids(ver)
        assert {"stone", "air", "oak_planks"} <= ids


def test_base_block_id_strips_namespace_and_state():
    assert versions.base_block_id("minecraft:oak_log[axis=y]") == "oak_log"
    assert versions.base_block_id("stone") == "stone"
    # Foreign namespace is preserved so it can be spotted as modded.
    assert versions.base_block_id("mymod:gadget") == "mymod:gadget"


def test_validate_flags_typo_with_suggestion():
    unknown = versions.validate_block_ids(["oak_plank"], "1.19.4")
    assert "oak_plank" in unknown
    assert "oak_planks" in unknown["oak_plank"]


def test_validate_passes_known_blocks():
    assert versions.validate_block_ids(
        ["stone", "minecraft:oak_log[axis=y]", "air"], "1.19.4"
    ) == {}


def test_validate_is_version_aware():
    # crafter arrived in 1.20 — unknown on 1.19.4, valid on 1.21.4.
    assert "crafter" in versions.validate_block_ids(["crafter"], "1.19.4")
    assert versions.validate_block_ids(["crafter"], "1.21.4") == {}
    # pale_oak_planks arrived in 1.21 — unknown on both earlier lists.
    assert "pale_oak_planks" in versions.validate_block_ids(["pale_oak_planks"], "1.20.4")
    assert versions.validate_block_ids(["pale_oak_planks"], "1.21.4") == {}


def test_validate_skips_modded_namespace():
    assert versions.validate_block_ids(["mymod:reactor_core"], "1.19.4") == {}


def test_converter_accepts_each_version(tmp_path):
    structure = MinecraftStructure(
        name="v",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [1, 0, 1], "block": "stone"}],
    )
    for ver in versions.SUPPORTED_VERSIONS:
        out = tmp_path / f"{ver.replace('.', '_')}.schem"
        SchematicConverter.to_schematic(structure, str(out), version=ver)
        assert out.exists() and out.stat().st_size > 0


def test_converter_rejects_bad_version(tmp_path):
    structure = MinecraftStructure(
        name="v",
        operations=[{"op": "block", "pos": [0, 0, 0], "block": "stone"}],
    )
    with pytest.raises(ValueError):
        SchematicConverter.to_schematic(structure, str(tmp_path / "x.schem"), version="9.9.9")
