"""Tests for the build style guide.

The important one is ``test_guide_block_ids_are_valid``: it holds every block ID
mentioned in the guide to the same registry check real builds go through, so the
shipped palettes can't rot as versions move on.
"""

import json
import re

import pytest

from minecraft_builder import versions
from minecraft_builder.converter import SchematicConverter
from minecraft_builder.schema import MinecraftStructure
from minecraft_builder.style import STYLE_CHECKLIST, load_style_guide

# Tokens in the guide that are backticked but aren't block IDs: op names, field
# names, block-state keys and tool names.
NON_BLOCK_TOKENS = frozenset({
    "cuboid", "hollow_box", "sphere", "cylinder", "line", "pyramid", "block",
    "replace", "op", "start", "end", "center", "radius", "height", "base",
    "hollow", "walls", "floor", "ceiling", "pos", "from_block", "to_block",
    "facing", "half", "type", "axis", "open", "hanging", "mc_version",
    "create_minecraft_structure", "get_build_style_guide",
    "true", "false",  # block-state values, referenced bare in prose
})

# A bare block id, optionally with a block-state suffix.
BLOCK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\[[a-z0-9_=,]+\])?$")


# The palettes target the mc_version default and hold until `chain` was renamed
# to `iron_chain`. Newer releases are covered by the guide's own version tables,
# which test_version_tables_match_the_registry checks instead.
GUIDE_BASELINE_RANGE = ("1.19.4", "1.21.8")

VERSION_SECTION = "## 9. Version awareness"


def _guide_without_version_section() -> str:
    """The guide minus the section that deliberately cites other versions' blocks."""
    text = load_style_guide()
    head, sep, tail = text.partition(VERSION_SECTION)
    assert sep, "version-awareness section heading moved or was renamed"
    return head + tail.partition("## Op cookbook")[2]


def _block_ids_in_guide() -> set[str]:
    """Every plausible block ID referenced in the guide, outside section 9."""
    text = _guide_without_version_section()
    candidates = set(re.findall(r"`([^`\n]+)`", text))
    candidates |= set(
        re.findall(r'"(?:block|from_block|to_block)"\s*:\s*"([^"]+)"', text)
    )
    return {
        c for c in candidates
        if BLOCK_ID_RE.match(c)
        and versions.base_block_id(c) not in NON_BLOCK_TOKENS
    }


def test_guide_loads_and_covers_the_core_rules():
    guide = load_style_guide()
    assert len(guide) > 5000
    for heading in ("Palette", "Depth", "Proportion", "Roofs", "Silhouette",
                    "Op cookbook", "Anti-patterns", "Pre-flight checklist"):
        assert heading in guide


def test_guide_block_ids_are_valid():
    ids = _block_ids_in_guide()
    # Sanity-check the extraction itself before trusting the assertion.
    assert len(ids) > 60, f"extraction looks broken, only found {len(ids)}"
    assert "stone_bricks" in ids and "lantern" in ids

    unknown = versions.validate_block_ids(sorted(ids), versions.DEFAULT_VERSION)
    assert not unknown, (
        f"invalid block IDs in style guide for {versions.DEFAULT_VERSION}: "
        + ", ".join(f"{k} (did you mean {v})" for k, v in unknown.items())
    )


def _versions_between(low: str, high: str) -> list[str]:
    order = versions.supported_versions()
    return list(order[order.index(low):order.index(high) + 1])


@pytest.mark.parametrize("version", _versions_between(*GUIDE_BASELINE_RANGE))
def test_guide_block_ids_valid_across_baseline_range(version):
    unknown = versions.validate_block_ids(sorted(_block_ids_in_guide()), version)
    assert not unknown, f"invalid for {version}: {', '.join(unknown)}"


def test_version_tables_match_the_registry():
    """The guide's rename and additions tables must agree with the block index.

    This is what stops the version guidance drifting: every claim is checked
    against the same data the validator uses.
    """
    section = load_style_guide().partition(VERSION_SECTION)[2].partition("## Op cookbook")[0]
    order = versions.supported_versions()

    renames = re.findall(r"^\| `(\w+)` \| `(\w+)` \| ([\d.]+) \|", section, re.M)
    assert len(renames) >= 3, f"rename table not parsed, got {renames}"
    for old, new, in_version in renames:
        old_span, new_span = versions.block_span(old), versions.block_span(new)
        assert old_span and new_span, f"{old}/{new} missing from the index"
        assert new_span.added == in_version, (
            f"{new} is recorded as added in {new_span.added}, guide claims {in_version}"
        )
        previous = order[order.index(in_version) - 1]
        assert old_span.removed_after == previous, (
            f"{old} is recorded as removed after {old_span.removed_after}, "
            f"guide implies {previous}"
        )

    # Additions table: every block listed on a row must have been added then.
    rows = re.findall(r"^\| ([\d.]+) \| (.+) \|$", section, re.M)
    assert len(rows) >= 9, f"additions table not parsed, got {len(rows)} rows"
    checked = 0
    for version, cell in rows:
        for block in re.findall(r"`(\w+)`", cell):
            span = versions.block_span(block)
            assert span, f"{block} (row {version}) is not a known block"
            assert span.added == version, (
                f"{block} was added in {span.added}, guide lists it under {version}"
            )
            checked += 1
    assert checked >= 40, f"only {checked} additions checked"


def _cookbook_recipes() -> list[list[dict]]:
    """Parse each ```json fence in the guide into an operation list.

    The fences are fragments — comma-separated ops without the enclosing array —
    so they can be dropped straight into an "operations" list.
    """
    fences = re.findall(r"```json\n(.*?)```", load_style_guide(), re.S)
    return [json.loads("[" + f.strip().rstrip(",") + "]") for f in fences]


def test_cookbook_recipes_build():
    recipes = _cookbook_recipes()
    assert len(recipes) >= 8, f"expected the full cookbook, found {len(recipes)}"
    for i, ops in enumerate(recipes, 1):
        structure = MinecraftStructure(name=f"recipe_{i}", operations=ops)
        block_map = structure.expand()
        assert block_map, f"recipe {i} produced no blocks"
        unknown = versions.validate_block_ids(
            set(block_map.values()), versions.DEFAULT_VERSION
        )
        assert not unknown, f"recipe {i} has invalid blocks: {unknown}"


def test_cookbook_recipes_convert(tmp_path):
    for i, ops in enumerate(_cookbook_recipes(), 1):
        structure = MinecraftStructure(name=f"recipe_{i}", operations=ops)
        out = tmp_path / f"recipe_{i}.schem"
        SchematicConverter.to_schematic(structure, str(out))
        assert out.exists() and out.stat().st_size > 0


def test_single_course_rings_are_not_solid_slabs():
    """Guard the hollow_box gotcha the cookbook warns about.

    A 1-tall hollow_box with floor/ceiling off must yield a perimeter ring, not a
    filled plane — this is what the plinth, cornice and battlement recipes rely on.
    """
    ring = MinecraftStructure(name="ring", operations=[{
        "op": "hollow_box", "start": [0, 0, 0], "end": [9, 0, 9],
        "block": "stone", "walls": True, "floor": False, "ceiling": False,
    }]).expand()
    assert len(ring) == 36, f"expected a 10x10 perimeter (36), got {len(ring)}"

    solid = MinecraftStructure(name="solid", operations=[{
        "op": "hollow_box", "start": [0, 0, 0], "end": [9, 0, 9], "block": "stone",
    }]).expand()
    assert len(solid) == 100, "default floor=True should fill the plane"


def test_checklist_stays_compact():
    # Ships in every tool listing, so it must not bloat the context.
    assert len(STYLE_CHECKLIST) < 1500
    assert "50/30/20" in STYLE_CHECKLIST
    assert "get_build_style_guide" in STYLE_CHECKLIST


def test_guide_is_cached():
    assert load_style_guide() is load_style_guide()
