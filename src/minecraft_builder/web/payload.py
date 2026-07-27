"""Builds the JSON the 3D viewer consumes.

Three things shape this format:

* **Flat arrays, not objects.** One JSON object per block would dominate the
  payload; a flat ``voxels`` array with a fixed stride keeps a 50k-block build in
  the low megabytes and needs no parsing in the browser beyond indexing.
* **Occluded voxels are dropped.** A voxel with all six neighbours filled can
  never be seen, so it is omitted. A solid 20x20x20 cuboid goes from 8000 voxels
  to 2168 — the interior is what makes naive voxel rendering slow.
* **Provenance travels with every voxel.** Each voxel carries the index of the
  operation that placed it, which is what lets the viewer colour by operation
  and, later, turn a click into "operation #4, the roof pyramid".

Coordinates are the structure's own authoring coordinates, negatives included.
The export-time shift to a zero origin stays inside the converter, so an index
into ``operations`` means the same thing here as it does in the source JSON.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..colors import block_hex, is_visible
from ..schema import BlockMap, MinecraftStructure

# Values per voxel in the flat array: x, y, z, palette index, operation index.
VOXEL_STRIDE = 5

_NEIGHBOURS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def _is_occluded(coord: Tuple[int, int, int], solid: set) -> bool:
    """True if every face of this voxel is against another solid voxel."""
    x, y, z = coord
    return all((x + dx, y + dy, z + dz) in solid for dx, dy, dz in _NEIGHBOURS)


def visible_coords(block_map: BlockMap, include_interior: bool = False) -> List[Tuple[int, int, int]]:
    """Drawable coordinates: solid blocks, minus fully enclosed ones.

    Air is not "transparent" here, it is absent — an air block in the map is
    empty space, so it both goes undrawn and leaves its neighbours' faces
    exposed.
    """
    solid = {c for c, block in block_map.items() if is_visible(block)}
    if include_interior:
        return sorted(solid)
    return sorted(c for c in solid if not _is_occluded(c, solid))


def build_payload(
    structure: MinecraftStructure,
    version: int = 1,
    include_interior: bool = False,
) -> Dict:
    """Render ``structure`` into the viewer's JSON payload."""
    block_map, origin = structure.expand_with_provenance()
    coords = visible_coords(block_map, include_interior=include_interior)

    # Palette indices, assigned in first-seen order for stable diffs between
    # versions of the same build.
    palette_index: Dict[str, int] = {}
    voxels: List[int] = []
    for coord in coords:
        block = block_map[coord]
        index = palette_index.setdefault(block, len(palette_index))
        voxels.extend((coord[0], coord[1], coord[2], index, origin.get(coord, -1)))

    total_operations = len(structure.blocks) + len(structure.operations)
    return {
        "name": structure.name,
        "description": structure.description or "",
        "version": version,
        "bounds": _bounds(block_map),
        "palette": [
            {"block": block, "color": block_hex(block)} for block in palette_index
        ],
        "operations": [
            {"index": i, "label": structure.describe_operation(i)}
            for i in range(total_operations)
        ],
        "stride": VOXEL_STRIDE,
        "voxels": voxels,
        "counts": {
            "drawn": len(coords),
            "total": len(block_map),
            "hidden": len(block_map) - len(coords),
        },
    }


def _bounds(block_map: BlockMap) -> Dict[str, List[int]]:
    """Bounding box in authoring coordinates, for camera framing."""
    if not block_map:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "size": [0, 0, 0]}
    xs = [c[0] for c in block_map]
    ys = [c[1] for c in block_map]
    zs = [c[2] for c in block_map]
    low = [min(xs), min(ys), min(zs)]
    high = [max(xs), max(ys), max(zs)]
    return {
        "min": low,
        "max": high,
        "size": [high[i] - low[i] + 1 for i in range(3)],
    }
