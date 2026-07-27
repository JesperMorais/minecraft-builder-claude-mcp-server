"""Text preview and statistics for a structure.

Claude can't see the generated schematic, so this renders the expanded block
map as ASCII layer slices plus summary stats — enough for the model to sanity-
check geometry (is the doorway where I meant? did the sphere come out round?)
before writing the file. Pure functions over a block map, so they're easy to
test and reused by both the preview tool and the create-tool result summary.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict

from .schema import BlockMap, MinecraftStructure
from .versions import base_block_id


class Stats(TypedDict):
    """Summary numbers for a block map."""
    empty: bool
    width: int
    height: int
    length: int
    placed: int
    solid: int
    air: int
    fill_ratio: float
    counts: Dict[str, int]

# Characters assigned to block types, most-common first. Air renders as '.'.
_LEGEND_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789#@%&$*+=<>?"
)
AIR_CHAR = "."

# Guard rails so a huge build can't dump megabytes of text at the model.
MAX_FOOTPRINT_DIM = 48   # widest X or Z we'll draw a grid for
MAX_LAYERS = 24          # most Y layers we'll print in full


def is_air(block_id: str) -> bool:
    """True for any air variant (air, cave_air, void_air), with/without state."""
    return base_block_id(block_id).endswith("air")


def structure_stats(block_map: BlockMap) -> Stats:
    """Summarise a block map: bounds, counts, per-type tally and fill ratio."""
    if not block_map:
        return {
            "empty": True, "width": 0, "height": 0, "length": 0,
            "placed": 0, "solid": 0, "air": 0, "fill_ratio": 0.0, "counts": {},
        }

    xs = [c[0] for c in block_map]
    ys = [c[1] for c in block_map]
    zs = [c[2] for c in block_map]
    width = max(xs) - min(xs) + 1
    height = max(ys) - min(ys) + 1
    length = max(zs) - min(zs) + 1

    counts: Dict[str, int] = {}
    solid = 0
    for block_id in block_map.values():
        base = base_block_id(block_id)
        counts[base] = counts.get(base, 0) + 1
        if not base.endswith("air"):
            solid += 1

    bbox = width * height * length
    return {
        "empty": False,
        "width": width, "height": height, "length": length,
        "placed": len(block_map),
        "solid": solid,
        "air": len(block_map) - solid,
        "fill_ratio": solid / bbox if bbox else 0.0,
        "counts": counts,
    }


def build_legend(counts: Dict[str, int]) -> Dict[str, str]:
    """Map each non-air block base name to a legend char, common-first."""
    ranked = sorted(
        (b for b in counts if not b.endswith("air")),
        key=lambda b: (-counts[b], b),
    )
    legend: Dict[str, str] = {}
    for i, base in enumerate(ranked):
        legend[base] = _LEGEND_CHARS[i] if i < len(_LEGEND_CHARS) else "?"
    return legend


def _layer_indices(min_y: int, max_y: int) -> List[int]:
    """Y levels to draw — all of them, or an evenly-sampled subset if too tall."""
    height = max_y - min_y + 1
    if height <= MAX_LAYERS:
        return list(range(min_y, max_y + 1))
    step = (height - 1) / (MAX_LAYERS - 1)
    return sorted({round(min_y + i * step) for i in range(MAX_LAYERS)})


def render_preview(structure: MinecraftStructure) -> str:
    """Render an ASCII preview of the structure: header, legend, layer slices."""
    block_map = structure.expand()
    stats = structure_stats(block_map)

    lines: List[str] = [f"Preview: {structure.name}"]
    if stats["empty"]:
        lines.append("(empty — no blocks or operations)")
        return "\n".join(lines)

    lines.append(
        f"Size {stats['width']}x{stats['height']}x{stats['length']} (WxHxL) · "
        f"{stats['placed']} blocks ({stats['solid']} solid, {stats['air']} air) · "
        f"fill {stats['fill_ratio'] * 100:.0f}%"
    )
    lines.append(_counts_line(stats["counts"]))

    min_x = min(c[0] for c in block_map)
    max_x = max(c[0] for c in block_map)
    min_y = min(c[1] for c in block_map)
    max_y = max(c[1] for c in block_map)
    min_z = min(c[2] for c in block_map)
    max_z = max(c[2] for c in block_map)

    if stats["width"] > MAX_FOOTPRINT_DIM or stats["length"] > MAX_FOOTPRINT_DIM:
        lines.append(
            f"\n(Footprint {stats['width']}x{stats['length']} is too large to draw "
            f"as a grid; showing stats only. Preview a sub-region if you need slices.)"
        )
        return "\n".join(lines)

    legend = build_legend(stats["counts"])
    lines.append("\nLegend: " + ", ".join(f"{ch}={base}" for base, ch in
                                          sorted(legend.items(), key=lambda kv: kv[1])))
    lines.append(f"        {AIR_CHAR}=air/empty   (each slice: rows=Z north→south, cols=X west→east)")

    layers = _layer_indices(min_y, max_y)
    if len(layers) < (max_y - min_y + 1):
        lines.append(f"\n(Structure is {stats['height']} tall; showing {len(layers)} "
                     f"sampled layers.)")

    for y in layers:  # bottom-up
        lines.append(f"\ny={y}:")
        for z in range(min_z, max_z + 1):
            row = []
            for x in range(min_x, max_x + 1):
                block_id = block_map.get((x, y, z))
                if block_id is None or is_air(block_id):
                    row.append(AIR_CHAR)
                else:
                    row.append(legend.get(base_block_id(block_id), "?"))
            lines.append("".join(row))

    return "\n".join(lines)


def _counts_line(counts: Dict[str, int], top: int = 6) -> str:
    """A compact 'most common block types' line for summaries."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ranked[:top]
    parts = [f"{base}×{n}" for base, n in shown]
    extra = len(ranked) - len(shown)
    if extra > 0:
        parts.append(f"+{extra} more")
    return "Blocks: " + ", ".join(parts)


def stats_summary(block_map: BlockMap) -> str:
    """One- or two-line stats block for the create-tool result."""
    stats = structure_stats(block_map)
    if stats["empty"]:
        return "empty"
    return (
        f"- Size: {stats['width']}x{stats['height']}x{stats['length']} blocks\n"
        f"- Blocks: {stats['placed']} placed ({stats['solid']} solid, "
        f"{stats['air']} air), fill {stats['fill_ratio'] * 100:.0f}%\n"
        f"- {_counts_line(stats['counts'])}"
    )
