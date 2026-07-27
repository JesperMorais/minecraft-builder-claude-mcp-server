"""Pure geometry generators for Minecraft structure primitives.

Each function yields integer ``(x, y, z)`` voxel coordinates for a shape.
They know nothing about block types, schematics, or the MCP layer — this keeps
them trivially testable and reusable. Coordinates may be negative; the converter
handles offsetting to a valid schematic origin.
"""

from __future__ import annotations

from typing import Iterator, Tuple

Coord = Tuple[int, int, int]


def _bounds(a: int, b: int) -> Tuple[int, int]:
    """Return (low, high) so callers can pass corners in any order."""
    return (a, b) if a <= b else (b, a)


def cuboid(start: Coord, end: Coord) -> Iterator[Coord]:
    """Every voxel in the solid box between two (inclusive) corners."""
    x0, x1 = _bounds(start[0], end[0])
    y0, y1 = _bounds(start[1], end[1])
    z0, z1 = _bounds(start[2], end[2])
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                yield (x, y, z)


def hollow_box(
    start: Coord,
    end: Coord,
    walls: bool = True,
    floor: bool = True,
    ceiling: bool = True,
) -> Iterator[Coord]:
    """Shell of a box. Individual faces can be toggled.

    ``walls`` covers the four vertical sides, ``floor`` the bottom Y face and
    ``ceiling`` the top Y face. A voxel is emitted if it lies on any *enabled*
    boundary face, so edges/corners are included whenever an adjacent face is on.
    """
    x0, x1 = _bounds(start[0], end[0])
    y0, y1 = _bounds(start[1], end[1])
    z0, z1 = _bounds(start[2], end[2])
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                on_side = x in (x0, x1) or z in (z0, z1)
                on_floor = y == y0
                on_ceiling = y == y1
                if (walls and on_side) or (floor and on_floor) or (ceiling and on_ceiling):
                    yield (x, y, z)


def sphere(center: Coord, radius: int, hollow: bool = False) -> Iterator[Coord]:
    """Voxel sphere (or spherical shell) of the given radius.

    A voxel is *solid* when its offset from centre satisfies
    ``dx² + dy² + dz² <= radius²``. For a hollow sphere we keep only solid
    voxels that touch a non-solid 6-neighbour, yielding a clean 1-voxel shell.
    """
    cx, cy, cz = center
    r2 = radius * radius

    def solid(dx: int, dy: int, dz: int) -> bool:
        return dx * dx + dy * dy + dz * dz <= r2

    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if not solid(dx, dy, dz):
                    continue
                if hollow and all(
                    solid(dx + ox, dy + oy, dz + oz)
                    for ox, oy, oz in (
                        (1, 0, 0), (-1, 0, 0),
                        (0, 1, 0), (0, -1, 0),
                        (0, 0, 1), (0, 0, -1),
                    )
                ):
                    # Fully surrounded -> interior, skip for a shell.
                    continue
                yield (cx + dx, cy + dy, cz + dz)


def cylinder(
    center: Coord,
    radius: int,
    height: int,
    axis: str = "y",
    hollow: bool = False,
) -> Iterator[Coord]:
    """Cylinder of ``height`` voxels extending along ``axis`` from ``center``.

    ``center`` is the centre of the base cap. ``hollow`` produces an open tube
    (ring wall, no end caps); solid produces stacked filled disks.
    """
    axis = axis.lower()
    if axis not in ("x", "y", "z"):
        raise ValueError(f"axis must be one of x/y/z, got {axis!r}")
    r2 = radius * radius

    def in_disk(a: int, b: int) -> bool:
        return a * a + b * b <= r2

    def on_ring(a: int, b: int) -> bool:
        # Solid but with at least one non-solid 4-neighbour in the disk plane.
        if not in_disk(a, b):
            return False
        return not (
            in_disk(a + 1, b) and in_disk(a - 1, b)
            and in_disk(a, b + 1) and in_disk(a, b - 1)
        )

    cx, cy, cz = center
    for level in range(height):
        for a in range(-radius, radius + 1):
            for b in range(-radius, radius + 1):
                keep = on_ring(a, b) if hollow else in_disk(a, b)
                if not keep:
                    continue
                if axis == "y":
                    yield (cx + a, cy + level, cz + b)
                elif axis == "x":
                    yield (cx + level, cy + a, cz + b)
                else:  # z
                    yield (cx + a, cy + b, cz + level)


def line(start: Coord, end: Coord) -> Iterator[Coord]:
    """3D line between two points via a integer DDA (Bresenham) walk."""
    x0, y0, z0 = start
    x1, y1, z1 = end
    dx, dy, dz = abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    sz = 1 if z1 >= z0 else -1
    steps = max(dx, dy, dz)
    if steps == 0:
        yield (x0, y0, z0)
        return
    # Accumulate error along the dominant axis for each subordinate axis.
    x, y, z = x0, y0, z0
    ex = ey = ez = steps // 2
    for _ in range(steps):
        yield (x, y, z)
        ex -= dx
        if ex < 0:
            ex += steps
            x += sx
        ey -= dy
        if ey < 0:
            ey += steps
            y += sy
        ez -= dz
        if ez < 0:
            ez += steps
            z += sz
    yield (x1, y1, z1)


def pyramid(
    center: Coord,
    base: int,
    axis: str = "y",
    hollow: bool = False,
) -> Iterator[Coord]:
    """Stepped square pyramid of half-width ``base`` narrowing along ``axis``.

    ``center`` is the centre of the base layer. Each successive layer shrinks by
    one voxel per side until it reaches the apex. ``hollow`` keeps only the
    perimeter of each layer.
    """
    axis = axis.lower()
    if axis not in ("x", "y", "z"):
        raise ValueError(f"axis must be one of x/y/z, got {axis!r}")
    cx, cy, cz = center
    for level in range(base + 1):
        half = base - level
        for a in range(-half, half + 1):
            for b in range(-half, half + 1):
                if hollow and not (abs(a) == half or abs(b) == half):
                    continue
                if axis == "y":
                    yield (cx + a, cy + level, cz + b)
                elif axis == "x":
                    yield (cx + level, cy + a, cz + b)
                else:  # z
                    yield (cx + a, cy + b, cz + level)
