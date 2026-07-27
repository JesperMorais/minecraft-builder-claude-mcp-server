"""Flat display colours for Minecraft blocks, for the 3D viewer.

Minecraft's own textures are Mojang's and cannot be redistributed, so the viewer
renders each block as a flat colour instead. For judging a build — is the
silhouette right, is the roof the wrong material, does the palette clash — shape
plus colour carries almost all of the signal a texture would.

Colours are resolved in four escalating steps, so a small table covers the whole
block set including blocks that do not exist yet:

1. ``_EXACT`` — a curated colour for a specific block.
2. Dyed families — the 16 dye colours crossed with a material modifier, which
   covers wool, concrete, terracotta, stained glass, carpets and friends without
   listing 200 entries.
3. Structural rules — wood families by suffix (log vs leaves vs planks), then
   shape suffixes (``_stairs``, ``_slab``, ``_wall``, ...) stripped and retried,
   so ``polished_andesite_stairs`` inherits from ``polished_andesite``.
4. A deterministic hash, kept in a muted range. Stable across runs and processes
   (``hash()`` is not), so an unrecognised or modded block always renders the
   same colour rather than flickering between sessions.

Deliberately not generated from the vendored block registry: nothing here needs
to know which blocks exist in which version, and keeping it independent means the
viewer can colour a modded or newly-added block sensibly instead of failing.
"""

from __future__ import annotations

import zlib
from typing import Dict, Iterable, Tuple

from .preview import is_air
from .versions import base_block_id

RGB = Tuple[int, int, int]

# Rendered when a block resolves to nothing at all. Should never be reached.
FALLBACK: RGB = (154, 154, 154)


# --------------------------------------------------------------------------- #
# Dyed families: 16 colours x a handful of material modifiers
# --------------------------------------------------------------------------- #

_DYES: Dict[str, RGB] = {
    "white": (233, 236, 236),
    "orange": (240, 118, 19),
    "magenta": (189, 68, 179),
    "light_blue": (58, 175, 217),
    "yellow": (248, 198, 39),
    "lime": (112, 185, 25),
    "pink": (237, 141, 172),
    "gray": (62, 68, 71),
    "light_gray": (142, 142, 134),
    "cyan": (21, 137, 145),
    "purple": (121, 42, 172),
    "blue": (53, 57, 157),
    "brown": (114, 71, 40),
    "green": (84, 109, 27),
    "red": (160, 39, 34),
    "black": (20, 21, 25),
}

# Base tone that terracotta blends toward, which is what makes the dyed
# terracottas read as muted earth tones rather than as bright wool.
_TERRACOTTA_BASE: RGB = (152, 94, 67)

# Suffix -> how to shift the dye colour for that material.
_DYED_MATERIALS = {
    "wool": lambda c: c,
    "carpet": lambda c: c,
    "concrete": lambda c: _scale(c, 0.92),
    "concrete_powder": lambda c: _lighten(c, 0.14),
    "terracotta": lambda c: _blend(c, _TERRACOTTA_BASE, 0.45),
    "glazed_terracotta": lambda c: _lighten(_blend(c, _TERRACOTTA_BASE, 0.2), 0.08),
    "stained_glass": lambda c: _lighten(c, 0.12),
    "stained_glass_pane": lambda c: _lighten(c, 0.12),
    "shulker_box": lambda c: _scale(c, 0.85),
    "banner": lambda c: c,
    "bed": lambda c: c,
    "candle": lambda c: _lighten(c, 0.1),
}


# --------------------------------------------------------------------------- #
# Wood families
# --------------------------------------------------------------------------- #

# wood type -> (plank/processed colour, bark colour, leaf colour)
_WOODS: Dict[str, Tuple[RGB, RGB, RGB]] = {
    "oak": ((162, 130, 78), (108, 85, 51), (72, 112, 40)),
    "spruce": ((114, 84, 48), (58, 39, 20), (56, 84, 56)),
    "birch": ((196, 179, 123), (216, 215, 210), (128, 167, 85)),
    "jungle": ((160, 115, 80), (85, 67, 25), (58, 122, 24)),
    "acacia": ((168, 90, 50), (103, 96, 86), (105, 143, 54)),
    "dark_oak": ((66, 43, 20), (60, 46, 26), (56, 100, 32)),
    "mangrove": ((117, 54, 48), (84, 60, 47), (99, 141, 51)),
    "cherry": ((226, 178, 170), (86, 49, 60), (234, 175, 200)),
    "pale_oak": ((226, 219, 202), (145, 138, 122), (135, 165, 100)),
    "bamboo": ((196, 178, 76), (140, 152, 60), (108, 156, 60)),
    "crimson": ((109, 58, 85), (92, 25, 29), (122, 15, 33)),
    "warped": ((58, 110, 110), (56, 87, 88), (20, 143, 138)),
}

# Suffixes that mean "the bark/stem of this wood" rather than processed wood.
_BARK_SUFFIXES = ("_log", "_wood", "_stem", "_hyphae")


# --------------------------------------------------------------------------- #
# Curated colours for specific blocks
# --------------------------------------------------------------------------- #

_EXACT: Dict[str, RGB] = {
    # Air is never drawn, but keep it resolvable rather than special-cased away.
    "air": (0, 0, 0),
    "cave_air": (0, 0, 0),
    "void_air": (0, 0, 0),
    # Stone family
    "stone": (125, 125, 125),
    "cobblestone": (127, 127, 127),
    "mossy_cobblestone": (109, 121, 90),
    "stone_bricks": (122, 122, 122),
    "mossy_stone_bricks": (115, 121, 105),
    "cracked_stone_bricks": (118, 117, 117),
    "chiseled_stone_bricks": (118, 118, 118),
    "smooth_stone": (159, 159, 159),
    "andesite": (136, 136, 137),
    "polished_andesite": (132, 136, 136),
    "diorite": (188, 188, 189),
    "polished_diorite": (192, 193, 195),
    "granite": (149, 103, 85),
    "polished_granite": (154, 106, 88),
    "calcite": (223, 223, 218),
    "tuff": (108, 109, 102),
    "dripstone_block": (134, 107, 92),
    "deepslate": (77, 77, 80),
    "cobbled_deepslate": (77, 77, 80),
    "polished_deepslate": (72, 72, 74),
    "deepslate_bricks": (71, 71, 73),
    "deepslate_tiles": (54, 54, 56),
    "blackstone": (42, 36, 41),
    "polished_blackstone": (53, 48, 56),
    "polished_blackstone_bricks": (48, 42, 49),
    "basalt": (80, 80, 86),
    "polished_basalt": (99, 98, 96),
    "smooth_basalt": (72, 72, 80),
    "obsidian": (20, 18, 30),
    "crying_obsidian": (32, 10, 60),
    "bedrock": (85, 85, 85),
    # Ground
    "dirt": (134, 96, 67),
    "coarse_dirt": (119, 85, 59),
    "rooted_dirt": (144, 103, 76),
    "grass_block": (95, 159, 53),
    "podzol": (91, 63, 24),
    "mycelium": (111, 99, 100),
    "mud": (60, 55, 59),
    "clay": (160, 166, 179),
    "gravel": (131, 127, 126),
    "sand": (219, 207, 163),
    "red_sand": (190, 102, 33),
    "sandstone": (216, 203, 155),
    "smooth_sandstone": (224, 213, 165),
    "chiseled_sandstone": (216, 203, 155),
    "red_sandstone": (186, 99, 29),
    "smooth_red_sandstone": (181, 97, 31),
    "snow": (249, 254, 254),
    "snow_block": (249, 254, 254),
    "ice": (145, 183, 253),
    "packed_ice": (141, 180, 250),
    "blue_ice": (116, 167, 253),
    "powder_snow": (248, 253, 253),
    # Liquids
    "water": (63, 118, 228),
    "lava": (217, 96, 22),
    # Bricks and ceramics
    "bricks": (150, 97, 83),
    "mud_bricks": (137, 105, 78),
    "packed_mud": (150, 103, 76),
    "nether_bricks": (44, 21, 26),
    "red_nether_bricks": (69, 6, 8),
    "terracotta": _TERRACOTTA_BASE,
    "quartz_block": (235, 229, 222),
    "smooth_quartz": (236, 230, 224),
    "quartz_bricks": (234, 227, 219),
    "chiseled_quartz_block": (232, 226, 218),
    "purpur_block": (169, 125, 169),
    "purpur_pillar": (171, 128, 171),
    "end_stone": (219, 222, 158),
    "end_stone_bricks": (218, 224, 162),
    "prismarine": (99, 156, 151),
    "prismarine_bricks": (99, 171, 158),
    "dark_prismarine": (51, 91, 75),
    "sea_lantern": (172, 199, 190),
    # Metals and gems
    "iron_block": (220, 220, 220),
    "gold_block": (249, 236, 78),
    "diamond_block": (98, 237, 228),
    "emerald_block": (42, 203, 87),
    "netherite_block": (66, 57, 58),
    "lapis_block": (30, 67, 140),
    "redstone_block": (175, 24, 5),
    "coal_block": (16, 15, 15),
    "amethyst_block": (134, 102, 189),
    "copper_block": (192, 107, 79),
    "exposed_copper": (161, 125, 103),
    "weathered_copper": (108, 153, 111),
    "oxidized_copper": (82, 162, 132),
    "raw_iron_block": (166, 135, 107),
    "raw_gold_block": (221, 169, 46),
    "raw_copper_block": (154, 96, 67),
    # Light
    "glowstone": (171, 131, 84),
    "shroomlight": (240, 146, 70),
    "torch": (255, 200, 100),
    "wall_torch": (255, 200, 100),
    "lantern": (240, 180, 100),
    "soul_lantern": (100, 200, 210),
    "soul_torch": (100, 200, 210),
    "campfire": (200, 120, 60),
    "redstone_lamp": (95, 59, 32),
    "jack_o_lantern": (213, 145, 47),
    "froglight": (240, 235, 190),
    # Nether
    "netherrack": (97, 38, 38),
    # Nylium is ground, not wood, so it needs to beat the crimson/warped rule.
    "crimson_nylium": (130, 31, 31),
    "warped_nylium": (43, 114, 101),
    "quartz_pillar": (235, 229, 222),
    "soul_sand": (81, 62, 50),
    "soul_soil": (75, 57, 46),
    "magma_block": (142, 63, 31),
    "glowstone_dust": (171, 131, 84),
    # Plants and organics
    "moss_block": (89, 109, 45),
    "moss_carpet": (89, 109, 45),
    "hay_block": (166, 138, 21),
    "bone_block": (209, 206, 179),
    "melon": (112, 146, 30),
    "pumpkin": (196, 116, 22),
    "carved_pumpkin": (196, 116, 22),
    "vine": (60, 90, 30),
    "sponge": (196, 192, 74),
    "wet_sponge": (170, 182, 68),
    "sculk": (13, 39, 48),
    "mushroom_stem": (203, 196, 185),
    "brown_mushroom_block": (151, 108, 82),
    "red_mushroom_block": (200, 51, 48),
    "nether_wart_block": (114, 3, 3),
    "warped_wart_block": (22, 119, 121),
    "azalea_leaves": (109, 152, 60),
    "flowering_azalea_leaves": (128, 140, 70),
    "glass": (200, 226, 231),
    "glass_pane": (200, 226, 231),
    "tinted_glass": (44, 42, 47),
    "iron_bars": (120, 120, 120),
    "chain": (67, 71, 80),
    "scaffolding": (176, 137, 78),
    "ladder": (137, 106, 61),
    # Utility blocks that show up in builds
    "crafting_table": (137, 91, 51),
    "furnace": (110, 110, 110),
    "chest": (162, 124, 60),
    "barrel": (127, 100, 57),
    "bookshelf": (154, 122, 74),
    "cauldron": (63, 63, 63),
    "anvil": (69, 69, 69),
    "note_block": (98, 66, 46),
    "jukebox": (100, 68, 49),
    "loom": (139, 114, 74),
    "beehive": (159, 125, 72),
    "target": (219, 194, 178),
    "white_glazed_terracotta": (226, 226, 219),
}


# --------------------------------------------------------------------------- #
# Colour maths
# --------------------------------------------------------------------------- #

def _clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _scale(color: RGB, factor: float) -> RGB:
    return (_clamp(color[0] * factor), _clamp(color[1] * factor), _clamp(color[2] * factor))


def _lighten(color: RGB, amount: float) -> RGB:
    return tuple(_clamp(c + (255 - c) * amount) for c in color)  # type: ignore[return-value]


def _blend(a: RGB, b: RGB, weight: float) -> RGB:
    """Blend ``a`` toward ``b``; weight 0 keeps ``a``, weight 1 gives ``b``."""
    return tuple(_clamp(a[i] * (1 - weight) + b[i] * weight) for i in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

# Shape variants inherit their material's colour, so stripping the suffix and
# resolving again covers hundreds of blocks with no table entries.
_SHAPE_SUFFIXES = (
    "_stairs", "_slab", "_wall", "_fence_gate", "_fence", "_door", "_trapdoor",
    "_pressure_plate", "_button", "_hanging_sign", "_wall_sign", "_sign",
    "_pane", "_bars", "_pillar",
)


def _contains_token(name: str, token: str) -> bool:
    """True if ``token`` appears in ``name`` on underscore boundaries.

    Substring matching alone would let "oak" match "oakleaf_something"; this
    keeps it to whole underscore-delimited runs, while still matching a token
    that itself contains underscores such as "dark_oak" or "light_blue".
    """
    return (
        name == token
        or name.startswith(token + "_")
        or name.endswith("_" + token)
        or ("_" + token + "_") in name
    )


def _dyed(name: str) -> RGB | None:
    """Resolve a ``<colour>_<material>`` block such as ``lime_concrete``."""
    # Longest dye name first, so "light_blue" is tried before "blue" regardless
    # of how _DYES happens to be ordered.
    for dye in sorted(_DYES, key=len, reverse=True):
        prefix = dye + "_"
        if not name.startswith(prefix):
            continue
        material = name[len(prefix):]
        modifier = _DYED_MATERIALS.get(material)
        if modifier is not None:
            return modifier(_DYES[dye])
    return None


def _wood(name: str) -> RGB | None:
    """Resolve a wood-family block, distinguishing bark, leaves and planks."""
    # Longest wood name first so "dark_oak" wins over "oak".
    for wood in sorted(_WOODS, key=len, reverse=True):
        if not _contains_token(name, wood):
            continue
        planks, bark, leaves = _WOODS[wood]
        remainder = name.replace(wood, "", 1)
        if remainder.endswith("_leaves") or remainder == "_leaves":
            return leaves
        if any(remainder.endswith(s) for s in _BARK_SUFFIXES):
            return bark
        return planks
    return None


def _hashed(name: str) -> RGB:
    """Deterministic muted colour for a block we have no rule for.

    crc32 rather than ``hash()``: the built-in is salted per process, which would
    make an unknown block change colour every time the viewer restarted.
    """
    digest = zlib.crc32(name.encode("utf-8"))
    hue = digest % 360
    # Fixed mid saturation and value, so unknown blocks read as plausible
    # building materials rather than neon.
    return _hsv_to_rgb(hue / 360.0, 0.32, 0.62)


def _hsv_to_rgb(h: float, s: float, v: float) -> RGB:
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [
        (v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)
    ][i % 6]
    return (_clamp(r * 255), _clamp(g * 255), _clamp(b * 255))


def block_color(block_id: str) -> RGB:
    """Flat display colour for a block ID.

    Accepts any form the schema allows — ``stone``, ``minecraft:stone``,
    ``oak_log[axis=y]`` — and always returns a colour, falling back to a stable
    hash for blocks with no rule (including modded ones).
    """
    name = base_block_id(block_id)
    if ":" in name:
        # A foreign namespace: nothing to pattern-match, so hash the whole id.
        return _hashed(name)

    seen = set()
    while name and name not in seen:
        seen.add(name)

        exact = _EXACT.get(name)
        if exact is not None:
            return exact

        dyed = _dyed(name)
        if dyed is not None:
            return dyed

        wood = _wood(name)
        if wood is not None:
            return wood

        # Strip a shape suffix and try again; retry the plural form too, so
        # "stone_brick_stairs" reaches "stone_bricks".
        stripped = None
        for suffix in _SHAPE_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                stripped = name[: -len(suffix)]
                break
        if stripped is None:
            break
        if stripped not in _EXACT and (stripped + "s") in _EXACT:
            stripped += "s"
        name = stripped

    return _hashed(base_block_id(block_id))


def block_hex(block_id: str) -> str:
    """Flat display colour as ``#rrggbb``, which is what the viewer consumes."""
    r, g, b = block_color(block_id)
    return f"#{r:02x}{g:02x}{b:02x}"


def is_visible(block_id: str) -> bool:
    """False for blocks the viewer should not draw at all (any air variant)."""
    return not is_air(block_id)


def palette(block_ids: Iterable[str]) -> Dict[str, str]:
    """Map each distinct block ID to its hex colour, preserving first-seen order."""
    return {b: block_hex(b) for b in dict.fromkeys(block_ids)}
