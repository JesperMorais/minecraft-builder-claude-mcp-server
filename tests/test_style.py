"""Tests for the build style guide.

The important one is ``test_guide_block_ids_are_valid``: it holds every block ID
mentioned in the guide to the same registry check real builds go through, so the
shipped palettes can't rot as versions move on.
"""

import re

import pytest

from minecraft_builder import versions
from minecraft_builder.style import STYLE_CHECKLIST, load_style_guide

# Tokens in the guide that are backticked but aren't block IDs: op names, field
# names, block-state keys and tool names.
NON_BLOCK_TOKENS = frozenset({
    "cuboid", "hollow_box", "sphere", "cylinder", "line", "pyramid", "block",
    "replace", "op", "start", "end", "center", "radius", "height", "base",
    "hollow", "walls", "floor", "ceiling", "pos", "from_block", "to_block",
    "facing", "half", "type", "axis", "open", "hanging", "mc_version",
    "create_minecraft_structure", "get_build_style_guide",
})

# A bare block id, optionally with a block-state suffix.
BLOCK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\[[a-z0-9_=,]+\])?$")


def _block_ids_in_guide() -> set[str]:
    """Every plausible block ID referenced in the guide."""
    text = load_style_guide()
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


@pytest.mark.parametrize("version", sorted(versions.SUPPORTED_VERSIONS))
def test_guide_block_ids_valid_on_every_version(version):
    unknown = versions.validate_block_ids(sorted(_block_ids_in_guide()), version)
    assert not unknown, f"invalid for {version}: {', '.join(unknown)}"


def test_checklist_stays_compact():
    # Ships in every tool listing, so it must not bloat the context.
    assert len(STYLE_CHECKLIST) < 1500
    assert "50/30/20" in STYLE_CHECKLIST
    assert "get_build_style_guide" in STYLE_CHECKLIST


def test_guide_is_cached():
    assert load_style_guide() is load_style_guide()
