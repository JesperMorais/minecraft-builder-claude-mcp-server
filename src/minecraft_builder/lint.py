"""Programmatic style checks, distilled from ``data/style_guide.md``.

The guide's pre-flight checklist is prose, which means it only helps when the
model reads it and remembers to apply it. This module encodes the checks that
can be decided from the expanded block map alone, so every build gets the same
review regardless of who or what produced the JSON.

Deliberately heuristic: the rules here flag the guide's *anti-patterns* (one
block dominating, zero lights, an unbroken flat wall) rather than trying to
prove a build is good. False negatives are fine — a clean report is not an
endorsement — but false positives erode trust, so each rule leans conservative
and structural guesses (which band of Y is "the roof") are reported as ``info``
rather than ``warn``.

Layering note: imports from ``web.payload`` for the occluder test rather than
duplicating the partial-block tables; ``web.payload`` only depends on schema
and colours, so this stays cycle-free.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .preview import is_air
from .schema import BlockMap, MinecraftStructure
from .versions import base_block_id
from .web.payload import occludes

Coord = Tuple[int, int, int]

# A face this long with no relief is what the guide calls a flat wall
# ("no unbroken flat face longer than 6-8 blocks") — flag from 9 up, and only
# when the flat area is at least 3 courses tall, so window bands and single
# ledger courses don't trip it.
FLAT_FACE_MIN_RUN = 9
FLAT_FACE_MIN_ROWS = 3

# Below this many blocks a build is a doodle; most rules stay quiet.
SMALL_BUILD = 64

# Flood-filling the bounding volume is O(volume); past this it costs more than
# the advice is worth.
MAX_ANALYSIS_VOLUME = 500_000

# Palette families with less than this share of the build are "detail" (the
# guide's trace tier: lights, plants, shutters) and don't count toward 3-5.
PALETTE_DETAIL_SHARE = 0.05

# The guide's anti-pattern threshold: its own worked example of a bad build
# has the primary at 59%; the prescribed split tops out at ~50.
PALETTE_DOMINANCE = 0.55

# Which slice of the height decides what the roof is made of.
ROOF_BAND = 0.72

# Walking that roof material back down to its eave needs two tolerances: it has
# to hold this share of a course to still count as the roof there, and this many
# consecutive courses may miss before the walk gives up. A ridge beam, a gable
# end and a chimney all put a course of something else inside a roof.
ROOF_COURSE_SHARE = 0.2
ROOF_WALK_TOLERANCE = 2

# Shape variants collapse into their material for palette purposes: a wall of
# oak planks trimmed with oak stairs and oak slabs is one palette entry.
_SHAPE_SUFFIXES = (
    "_stairs", "_slab", "_wall", "_fence_gate", "_fence", "_door", "_trapdoor",
    "_pressure_plate", "_button", "_pane", "_bars", "_carpet", "_gate",
)

_WOOD_SPECIES = frozenset({
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove",
    "cherry", "bamboo", "crimson", "warped", "pale_oak",
})

_LIGHT_EXACT = frozenset({
    "torch", "lantern", "glowstone", "shroomlight", "campfire", "soul_campfire",
    "end_rod", "candle", "redstone_lamp", "sea_lantern", "beacon",
})
_LIGHT_SUFFIXES = ("_torch", "_candle", "_froglight", "_lantern")

_NEIGHBOURS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


@dataclass(frozen=True)
class Finding:
    """One style-guide violation. ``warn`` is an anti-pattern from the guide's
    table; ``info`` is a softer heuristic that may misread the structure."""

    rule: str
    severity: str  # "warn" | "info"
    message: str


def family(block: str) -> str:
    """Palette family of a block: shape suffixes stripped, wood shapes folded
    into their plank family, singular/plural unified (brick == bricks)."""
    base = base_block_id(block)
    for suffix in _SHAPE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    if base in _WOOD_SPECIES:
        base = f"{base}_planks"
    # brick_stairs strips to "brick", the full block is "bricks"; unify. The
    # double-s guard keeps "glass" (and friends) intact.
    if base.endswith("s") and not base.endswith("ss"):
        base = base[:-1]
    return base


def is_light(block: str) -> bool:
    base = base_block_id(block)
    return base in _LIGHT_EXACT or base.endswith(_LIGHT_SUFFIXES)


def lint_structure(
    structure: MinecraftStructure,
    block_map: Optional[BlockMap] = None,
) -> List[Finding]:
    """Run every check against a structure. ``block_map`` may be passed when
    the caller already expanded it; otherwise it is expanded here."""
    if block_map is None:
        block_map = structure.expand()

    solid: Dict[Coord, str] = {c: b for c, b in block_map.items() if not is_air(b)}
    findings: List[Finding] = []
    if not solid:
        return findings

    total = len(solid)
    findings.extend(_check_palette(solid, total))
    findings.extend(_check_stairs_and_slabs(solid, total))
    findings.extend(_check_footprint(solid))
    findings.extend(_check_roof_contrast(solid))
    findings.extend(_check_block_spam(structure))

    bounds_volume = _bounding_volume(solid)
    if bounds_volume <= MAX_ANALYSIS_VOLUME:
        outside = _outside_cells(solid)
        findings.extend(_check_lighting(solid, total))
        findings.extend(_check_flat_faces(solid, outside))
        findings.extend(_check_interior(solid, bounds_volume))
    else:
        findings.append(Finding(
            "analysis-skipped", "info",
            f"build spans {bounds_volume:,} cells; the geometric checks "
            "(flat faces, interior) were skipped at this size",
        ))
        findings.extend(_check_lighting(solid, total))

    order = {"warn": 0, "info": 1}
    findings.sort(key=lambda f: (order.get(f.severity, 2), f.rule))
    return findings


def format_report(findings: Sequence[Finding]) -> str:
    """Human-readable report, one line per finding."""
    if not findings:
        return "Style check: clean — no guide violations detected."
    warns = sum(1 for f in findings if f.severity == "warn")
    infos = len(findings) - warns
    counts = " and ".join(
        part for part, n in ((f"{warns} warning(s)", warns), (f"{infos} note(s)", infos)) if n
    )
    lines = [f"Style check: {counts} (see get_build_style_guide):"]
    marker = {"warn": "⚠", "info": "·"}
    lines.extend(
        f"{marker.get(f.severity, '·')} [{f.rule}] {f.message}" for f in findings
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #

def _check_palette(solid: Dict[Coord, str], total: int) -> List[Finding]:
    if total < SMALL_BUILD:
        return []
    shares = Counter(
        family(block) for block in solid.values() if not is_light(block)
    )
    if not shares:
        return []
    main = [(f, n) for f, n in shares.most_common() if n / total >= PALETTE_DETAIL_SHARE]
    findings = []
    if len(main) < 3:
        names = ", ".join(f for f, _ in main)
        findings.append(Finding(
            "palette-size", "warn",
            f"only {len(main)} material(s) carry the build ({names}); the guide "
            "wants 3-5 in a ~50/30/20 split",
        ))
    elif len(main) > 5:
        findings.append(Finding(
            "palette-size", "info",
            f"{len(main)} materials each cover 5%+ of the build; more than 5 "
            "reads as patchwork rather than palette",
        ))
    top_family, top_count = shares.most_common(1)[0]
    if top_count / total > PALETTE_DOMINANCE:
        findings.append(Finding(
            "palette-dominance", "warn",
            f"{top_family} is {top_count / total:.0%} of the build; one block "
            "dominating over ~50% is the guide's #1 amateur tell",
        ))
    return findings


def _check_stairs_and_slabs(solid: Dict[Coord, str], total: int) -> List[Finding]:
    if total < 100:
        return []
    shaped = sum(
        1 for b in solid.values()
        if base_block_id(b).endswith(("_stairs", "_slab"))
    )
    if shaped == 0:
        return [Finding(
            "stairs-slabs", "warn",
            "no stairs or slabs anywhere; they are the detail workhorses for "
            "roofs, trim and sills",
        )]
    return []


def _check_lighting(solid: Dict[Coord, str], total: int) -> List[Finding]:
    if total < SMALL_BUILD:
        return []
    lights = sum(1 for b in solid.values() if is_light(b))
    if lights == 0:
        return [Finding(
            "lighting", "warn",
            "zero light sources; a build with no light looks dead (and spawns "
            "mobs) — one lantern per 6-8 blocks of facade, one per room",
        )]
    xs = [c[0] for c in solid]
    zs = [c[2] for c in solid]
    perimeter = 2 * ((max(xs) - min(xs) + 1) + (max(zs) - min(zs) + 1))
    if lights < perimeter / 16:
        return [Finding(
            "lighting", "info",
            f"{lights} light(s) for ~{perimeter} blocks of perimeter; the guide "
            "suggests one per 6-8 blocks of facade",
        )]
    return []


def _check_footprint(solid: Dict[Coord, str]) -> List[Finding]:
    xs = [c[0] for c in solid]
    zs = [c[2] for c in solid]
    width = max(xs) - min(xs) + 1
    length = max(zs) - min(zs) + 1
    short, long_ = sorted((width, length))
    if short >= 9 and long_ / short < 1.2:
        return [Finding(
            "footprint", "info",
            f"footprint {width}x{length} is nearly square; the guide suggests "
            "~1:1.5, or breaking the rectangle with a wing or bay",
        )]
    return []


def _check_roof_contrast(solid: Dict[Coord, str]) -> List[Finding]:
    ys = [c[1] for c in solid]
    low, high = min(ys), max(ys)
    span = high - low + 1
    if span < 6:
        return []

    courses: Dict[int, Counter] = {}
    for (_, y, _), block in solid.items():
        if not is_light(block):
            courses.setdefault(y, Counter())[family(block)] += 1

    def dominant(band: Iterable[int]) -> Optional[str]:
        tally: Counter = Counter()
        for y in band:
            tally.update(courses.get(y, ()))
        return tally.most_common(1)[0][0] if tally else None

    roof_from = low + int(span * ROOF_BAND)
    roof = dominant(range(roof_from, high + 1))
    if roof is None:
        return []

    # Follow the roof material down from its band to find the eave, rather than
    # sampling the walls at a fixed height. A steep roof occupies most of a
    # build, and its lower courses sit exactly where the walls were assumed to
    # be — which reads as a roof matching its walls when it is only the roof
    # matching itself.
    eave, misses = roof_from, 0
    for y in range(roof_from - 1, low - 1, -1):
        course = courses.get(y)
        if not course:
            continue  # a light-only course decides nothing either way
        if course[roof] >= sum(course.values()) * ROOF_COURSE_SHARE:
            eave, misses = y, 0
            continue
        misses += 1
        if misses > ROOF_WALK_TOLERANCE:
            break

    # The bottom course is the foundation, or the ground pad the build sits on,
    # rather than a wall; between that and the eave is the only band that is.
    walls = dominant(range(low + 1, eave))
    if walls is None:
        # The roof reaches the ground, so there is no wall band to compare
        # against. Only one reading of that is safe: the same material runs
        # from the ridge down, and it has to be most of the build for the
        # rule to say so — a roof that merely shares a block with the
        # foundation it stands on is not the anti-pattern.
        above_base: Counter = Counter()
        for y in range(low + 1, high + 1):
            above_base.update(courses.get(y, ()))
        if above_base[roof] * 2 <= sum(above_base.values()):
            return []
    elif walls != roof:
        return []

    return [Finding(
        "roof-contrast", "info",
        f"the top of the build is the same material as the wall below it "
        f"({roof}); a roof that matches the walls does not read as a roof",
    )]


def _check_block_spam(structure: MinecraftStructure) -> List[Finding]:
    if len(structure.blocks) > 200:
        return [Finding(
            "block-spam", "info",
            f"{len(structure.blocks)} explicit per-voxel blocks; walls and "
            "masses belong in cuboid/hollow_box ops, with block reserved for "
            "scatter and detail",
        )]
    return []


def _check_interior(solid: Dict[Coord, str], bounds_volume: int) -> List[Finding]:
    """Flags a solid mass with no carved space inside it.

    "Inside" is measured per column — empty cells between a column's lowest
    and highest solid block — rather than by flood-fill connectivity, because
    a real interior connects to the outside through its own doorway and would
    otherwise count as exterior.
    """
    if len(solid) < 200 or bounds_volume < 180:
        return []
    columns: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for x, y, z in solid:
        low, high = columns.get((x, z), (y, y))
        columns[(x, z)] = (min(low, y), max(high, y))
    sheltered = sum(
        1
        for (x, z), (low, high) in columns.items()
        for y in range(low + 1, high)
        if (x, y, z) not in solid
    )
    if sheltered == 0:
        return [Finding(
            "interior", "warn",
            "no carved interior space; hollow the mass with air, give rooms a "
            "floor and a light — the tool really does export carved space as "
            "empty",
        )]
    return []


def _check_flat_faces(solid: Dict[Coord, str], outside: Set[Coord]) -> List[Finding]:
    findings = []
    sides = {
        "+X": (1, 0, 0), "-X": (-1, 0, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1),
    }
    worst: Optional[Tuple[int, int, str]] = None  # (run, rows, side)
    for side, (dx, _, dz) in sides.items():
        rows_by_plane: Dict[int, Dict[int, Set[int]]] = {}
        for (x, y, z), block in solid.items():
            if not occludes(block):
                continue  # partial blocks *are* the relief the rule asks for
            neighbour = (x + dx, y, z + dz)
            if neighbour in solid or neighbour not in outside:
                continue  # covered, or an interior face
            plane = x if dx else z
            horizontal = z if dx else x
            rows_by_plane.setdefault(plane, {}).setdefault(y, set()).add(horizontal)
        for rows in rows_by_plane.values():
            panel = _largest_flat_panel(rows)
            if panel and (worst is None or panel > worst[:2]):
                worst = (*panel, side)
    if worst:
        run, depth, side = worst
        findings.append(Finding(
            "flat-face", "warn",
            f"an unbroken {run}x{depth} flat face on the {side} side; the guide "
            "wants no flat run past 6-8 blocks — add pillars (+1), inset "
            "windows (-1), a plinth or a cornice",
        ))
    return findings


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #

def _bounding_volume(solid: Dict[Coord, str]) -> int:
    xs = [c[0] for c in solid]
    ys = [c[1] for c in solid]
    zs = [c[2] for c in solid]
    return (
        (max(xs) - min(xs) + 1)
        * (max(ys) - min(ys) + 1)
        * (max(zs) - min(zs) + 1)
    )


def _outside_cells(solid: Dict[Coord, str]) -> Set[Coord]:
    """Empty cells reachable from beyond the build: flood fill over the
    bounding box inflated by one, seeded at its corner."""
    xs = [c[0] for c in solid]
    ys = [c[1] for c in solid]
    zs = [c[2] for c in solid]
    lo = (min(xs) - 1, min(ys) - 1, min(zs) - 1)
    hi = (max(xs) + 1, max(ys) + 1, max(zs) + 1)

    outside: Set[Coord] = set()
    queue: deque = deque([lo])
    outside.add(lo)
    while queue:
        x, y, z = queue.popleft()
        for dx, dy, dz in _NEIGHBOURS:
            cell = (x + dx, y + dy, z + dz)
            if cell in outside or cell in solid:
                continue
            if not all(lo[i] <= cell[i] <= hi[i] for i in range(3)):
                continue
            outside.add(cell)
            queue.append(cell)
    return outside


def _runs(cells: Set[int]) -> Iterable[Tuple[int, int]]:
    """Maximal consecutive runs (inclusive bounds) in a set of integers."""
    ordered = sorted(cells)
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        yield start, prev
        start = prev = value
    yield start, prev


def _clip(cells: Set[int], lo: int, hi: int) -> Optional[Tuple[int, int]]:
    """The largest run in ``cells`` clipped to [lo, hi], or None."""
    best = None
    for start, end in _runs(cells):
        start, end = max(start, lo), min(end, hi)
        if start > end:
            continue
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)
    return best


def _largest_flat_panel(
    rows: Dict[int, Set[int]],
    min_run: int = FLAT_FACE_MIN_RUN,
    min_rows: int = FLAT_FACE_MIN_ROWS,
) -> Optional[Tuple[int, int]]:
    """Largest (run length, row count) rectangle of exposed same-plane faces
    that stays at least ``min_run`` wide for ``min_rows`` stacked rows."""
    best: Optional[Tuple[int, int]] = None
    for y, cells in rows.items():
        for start, end in _runs(cells):
            if end - start + 1 < min_run:
                continue
            lo, hi = start, end
            depth = 1
            row = y + 1
            while row in rows:
                clipped = _clip(rows[row], lo, hi)
                if clipped is None or clipped[1] - clipped[0] + 1 < min_run:
                    break
                lo, hi = clipped
                depth += 1
                row += 1
            if depth >= min_rows:
                candidate = (hi - lo + 1, depth)
                if best is None or candidate > best:
                    best = candidate
    return best
