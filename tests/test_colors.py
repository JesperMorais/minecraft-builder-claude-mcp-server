"""Tests for block display colours used by the 3D viewer."""

import subprocess
import sys

import pytest

from minecraft_builder.colors import (
    _DYES,
    _EXACT,
    _WOODS,
    block_color,
    block_hex,
    is_visible,
    palette,
)


def test_exact_match_wins():
    assert block_color("stone") == _EXACT["stone"]


def test_namespace_and_block_state_are_ignored():
    assert block_color("minecraft:stone") == block_color("stone")
    assert block_color("oak_log[axis=y]") == block_color("oak_log")
    assert block_color("minecraft:oak_stairs[facing=north,half=top]") == block_color("oak_stairs")


# --------------------------------------------------------------------------- #
# Dyed families
# --------------------------------------------------------------------------- #

def test_wool_uses_the_dye_colour_directly():
    assert block_color("lime_wool") == _DYES["lime"]


def test_light_blue_is_not_shadowed_by_blue():
    # "blue" is a prefix-compatible dye name, so a naive scan would mis-resolve
    # every light_blue block.
    assert block_color("light_blue_wool") == _DYES["light_blue"]
    assert block_color("light_blue_wool") != block_color("blue_wool")


def test_terracotta_is_muted_relative_to_wool():
    wool = block_color("red_wool")
    terracotta = block_color("red_terracotta")
    assert wool != terracotta
    # Blended toward the terracotta base, so it must be less saturated: the gap
    # between the strongest and weakest channel shrinks.
    assert (max(terracotta) - min(terracotta)) < (max(wool) - min(wool))


@pytest.mark.parametrize("material", ["wool", "concrete", "terracotta", "carpet",
                                      "stained_glass", "concrete_powder", "shulker_box"])
def test_every_dye_resolves_for_every_material(material):
    colours = {block_color(f"{dye}_{material}") for dye in _DYES}
    # All 16 dyes must give distinct colours, otherwise a build would render
    # with two different wools looking identical.
    assert len(colours) == len(_DYES)


# --------------------------------------------------------------------------- #
# Wood families
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("wood", sorted(_WOODS))
def test_planks_bark_and_leaves_differ_per_wood(wood):
    planks = block_color(f"{wood}_planks")
    log = block_color(f"{wood}_log")
    leaves = block_color(f"{wood}_leaves")
    assert planks != log
    assert log != leaves


def test_dark_oak_is_not_resolved_as_oak():
    assert block_color("dark_oak_planks") != block_color("oak_planks")


def test_stripped_and_infixed_wood_names_resolve_to_bark():
    # "stripped_oak_log" neither starts nor ends with the wood name.
    assert block_color("stripped_oak_log") == block_color("oak_log")
    assert block_color("stripped_dark_oak_wood") == block_color("dark_oak_log")


# --------------------------------------------------------------------------- #
# Shape suffixes inherit from their material
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("variant,base", [
    ("oak_stairs", "oak_planks"),
    ("oak_slab", "oak_planks"),
    ("oak_fence", "oak_planks"),
    ("oak_trapdoor", "oak_planks"),
    ("polished_andesite_stairs", "polished_andesite"),
    ("deepslate_brick_wall", "deepslate_bricks"),
    ("nether_brick_fence", "nether_bricks"),
    ("stone_brick_stairs", "stone_bricks"),
    ("red_sandstone_slab", "red_sandstone"),
    ("prismarine_brick_slab", "prismarine_bricks"),
])
def test_shape_variant_inherits_material_colour(variant, base):
    assert block_color(variant) == block_color(base)


# --------------------------------------------------------------------------- #
# Fallback
# --------------------------------------------------------------------------- #

def test_unknown_block_gets_a_colour_rather_than_failing():
    assert len(block_color("definitely_not_a_real_block")) == 3


def test_modded_namespace_is_handled():
    assert len(block_color("createmod:brass_casing")) == 3


def test_unknown_block_colour_is_stable_across_processes():
    # zlib.crc32 rather than hash(): the built-in is salted per process, so an
    # unknown block would change colour on every viewer restart.
    code = (
        "from minecraft_builder.colors import block_color;"
        "print(block_color('some_unknown_modded_block'))"
    )
    runs = [
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       check=True).stdout.strip()
        for _ in range(2)
    ]
    assert runs[0] == runs[1]
    assert runs[0] == str(block_color("some_unknown_modded_block"))


# --------------------------------------------------------------------------- #
# Output shape
# --------------------------------------------------------------------------- #

_SAMPLE_BLOCKS = [
    "stone", "oak_planks", "lime_concrete", "unknown_thing", "modded:thing",
    "glass", "water", "dark_oak_log", "cherry_leaves", "deepslate_tiles",
]


@pytest.mark.parametrize("block", _SAMPLE_BLOCKS)
def test_channels_are_in_range(block):
    assert all(0 <= channel <= 255 for channel in block_color(block))


@pytest.mark.parametrize("block", _SAMPLE_BLOCKS)
def test_hex_format(block):
    value = block_hex(block)
    assert len(value) == 7 and value.startswith("#")
    int(value[1:], 16)  # must parse


def test_air_variants_are_not_drawn():
    assert not is_visible("air")
    assert not is_visible("minecraft:cave_air")
    assert not is_visible("void_air")
    assert is_visible("stone")


def test_palette_dedupes_and_preserves_order():
    result = palette(["stone", "oak_planks", "stone", "glass"])
    assert list(result) == ["stone", "oak_planks", "glass"]
    assert result["stone"] == block_hex("stone")
