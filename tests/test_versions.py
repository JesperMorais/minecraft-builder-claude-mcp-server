"""Tests for version support and block-ID validation."""

import pytest

from minecraft_builder import versions
from minecraft_builder.converter import SchematicConverter
from minecraft_builder.schema import MinecraftStructure


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


def test_versions_are_in_chronological_order():
    order = versions.supported_versions()
    dvs = [versions.data_version(v) for v in order]
    assert dvs == sorted(dvs), "versions must be ordered by DataVersion"
    assert order[0] == "1.13", "index starts at the flattening"
    assert versions.LATEST_VERSION == order[-1]


def test_can_target_versions_beyond_the_mcschematic_enum(tmp_path):
    """mcschematic's enum stops at 1.21.5; we target newer via the DataVersion."""
    import nbtlib

    latest = versions.LATEST_VERSION
    assert versions.data_version(latest) > 4325, "expected a post-1.21.5 latest"
    structure = MinecraftStructure(
        name="new", operations=[{"op": "block", "pos": [0, 0, 0], "block": "stone"}]
    )
    out = tmp_path / "new.schem"
    SchematicConverter.to_schematic(structure, str(out), version=latest)
    root = nbtlib.load(str(out))
    root = root[""] if "" in root else root
    assert int(root["DataVersion"]) == versions.data_version(latest)


def test_renamed_blocks_have_bounded_spans():
    # chain was renamed to iron_chain in 1.21.9.
    chain = versions.block_span("chain")
    assert chain.added == "1.16" and chain.removed_after == "1.21.8"
    assert versions.block_span("iron_chain").added == "1.21.9"
    assert "chain" in versions.load_block_ids("1.21.8")
    assert "chain" not in versions.load_block_ids("1.21.9")
    assert "iron_chain" in versions.load_block_ids("1.21.9")


def test_explain_unknown_distinguishes_the_three_failure_modes():
    # Too new for the target version.
    assert "added in 1.21.9" in versions.explain_unknown("copper_lantern", "1.19.4")
    # Renamed away.
    assert "iron_chain" in versions.explain_unknown("chain", "1.21.9")
    # Plain typo.
    assert "did you mean" in versions.explain_unknown("oak_plank", "1.19.4")


def test_blocks_added_in_matches_the_registry_delta():
    order = versions.supported_versions()
    for version in ("1.21.3", "1.21.4", "1.21.9"):
        previous = order[order.index(version) - 1]
        delta = versions.load_block_ids(version) - versions.load_block_ids(previous)
        assert versions.blocks_added_in(version) == delta
    assert "pale_oak_planks" in versions.blocks_added_in("1.21.3")
    assert "copper_lantern" in versions.blocks_added_in("1.21.9")


def test_provisional_versions_are_flagged():
    assert versions.is_provisional("26.2")
    assert not versions.is_provisional("1.21.4")
    assert "cinnabar_bricks" in versions.load_block_ids("26.2")
    assert "cinnabar_bricks" not in versions.load_block_ids("1.21.11")


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
