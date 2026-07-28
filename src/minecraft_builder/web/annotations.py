"""User markup on a build, resolved to the operation that produced it.

The point of this module is one transformation. A click in the viewer gives a
coordinate, and a coordinate is nearly useless feedback — "the block at
[7, 4, 3] is wrong" tells Claude to guess which of forty operations to edit.
``expand_with_provenance()`` knows which operation last wrote every coordinate,
so the same click becomes *"operation #4, the roof pyramid, is too steep"*, which
is a targeted edit.

**Resolution happens when the annotation is created, not when it is read.** The
user marked what was on screen, and by the time Claude asks, the structure may
have been revised — resolving late would silently point at whatever occupies that
coordinate now. So the version on screen is captured and resolved against
immediately, and the recorded ``op_index`` refers to *that* version. An
annotation whose version is no longer in history is still readable; it just
carries the label it was born with.

Threading matches the rest of ``web/``: annotations are created on the HTTP
thread and read from the MCP server's executor thread, so every access takes a
lock.
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field
from typing_extensions import Annotated

from ..schema import MinecraftStructure

Vec3 = Annotated[List[int], Field(min_length=3, max_length=3)]

# A long session accumulates markup; keep the newest. Old resolved notes are the
# least useful thing in memory.
MAX_ANNOTATIONS = 200

# How many operations a region annotation reports as also-covered. The dominant
# one is what Claude should edit; the rest are context for "and it overlaps these".
MAX_ALSO_COVERED = 4


class Annotation(BaseModel):
    """One note the user attached to a build."""

    id: int
    structure_version: int
    kind: Literal["point", "region", "operation", "global"]
    note: str
    pos: Optional[Vec3] = None
    start: Optional[Vec3] = None
    end: Optional[Vec3] = None
    # Resolved at creation. None for a global note, or a point that hit nothing.
    op_index: Optional[int] = None
    op_summary: Optional[str] = None
    # Other operations present in a region, dominant first, excluding op_index.
    also_covered: List[int] = Field(default_factory=list)
    # How many voxels of the region the dominant operation accounts for, so
    # "mostly the roof" can be told from "a 50/50 split".
    covered_voxels: int = 0
    region_voxels: int = 0
    status: Literal["open", "resolved"] = "open"

    def describe(self) -> str:
        """One line for Claude. Leads with the operation, since that is the edit."""
        where = {
            "point": lambda: f"block {self.pos}",
            "region": lambda: f"region {self.start}..{self.end}",
            "operation": lambda: "operation",
            "global": lambda: "the whole build",
        }[self.kind]()

        if self.op_index is None:
            target = "no specific operation"
        else:
            target = f"operation #{self.op_index}"
            if self.op_summary:
                target += f" ({self.op_summary})"

        line = f"[{self.id}] {where} -> {target}: {self.note}"

        if self.kind == "region" and self.region_voxels:
            share = 100 * self.covered_voxels // self.region_voxels
            line += f"\n     covers {share}% of the selection"
            if self.also_covered:
                others = ", ".join(f"#{i}" for i in self.also_covered)
                line += f"; also touches {others}"
        return line


def _box(start: Sequence[int], end: Sequence[int]):
    """Inclusive coordinate box, tolerating corners given in any order."""
    low = [min(start[i], end[i]) for i in range(3)]
    high = [max(start[i], end[i]) for i in range(3)]
    for x in range(low[0], high[0] + 1):
        for y in range(low[1], high[1] + 1):
            for z in range(low[2], high[2] + 1):
                yield (x, y, z)


def resolve_target(
    structure: MinecraftStructure,
    kind: str,
    pos: Optional[Sequence[int]] = None,
    start: Optional[Sequence[int]] = None,
    end: Optional[Sequence[int]] = None,
    op_index: Optional[int] = None,
) -> Dict:
    """Work out which operation an annotation is really about.

    Returns the resolution fields for ``Annotation``. A point resolves to its
    last writer; a region to the operation owning the most voxels in it, because
    a box drawn round a roof inevitably clips a wall and the roof is still what
    the user meant.
    """
    total_ops = len(structure.blocks) + len(structure.operations)

    def label(index: Optional[int]) -> Optional[str]:
        if index is None or not (0 <= index < total_ops):
            return None
        return structure.describe_operation(index)

    if kind == "global":
        return {"op_index": None, "op_summary": None}

    if kind == "operation":
        if op_index is None or not (0 <= op_index < total_ops):
            raise ValueError(
                f"op_index must be in 0..{total_ops - 1}, got {op_index!r}"
            )
        return {"op_index": op_index, "op_summary": label(op_index)}

    _block_map, origin = structure.expand_with_provenance()

    if kind == "point":
        if pos is None:
            raise ValueError("a point annotation needs pos")
        index = origin.get((pos[0], pos[1], pos[2]))
        return {"op_index": index, "op_summary": label(index)}

    if kind == "region":
        if start is None or end is None:
            raise ValueError("a region annotation needs start and end")
        # Walk the box rather than the block map: a selection is usually far
        # smaller than the build, and this way an empty selection is obvious.
        tally: Counter = Counter()
        for coord in _box(start, end):
            index = origin.get(coord)
            if index is not None:
                tally[index] += 1
        if not tally:
            return {"op_index": None, "op_summary": None, "region_voxels": 0}
        # Count descending, then *later* operation first. Ties are common — a box
        # round a roof catches exactly as much ceiling as roof — and the later
        # operation is the one drawn on top, so it is what the user was looking at
        # when they dragged the box. Relying on Counter's insertion order here
        # would make the answer depend on iteration order of the block map.
        ranked = sorted(tally.items(), key=lambda item: (-item[1], -item[0]))
        dominant, count = ranked[0]
        return {
            "op_index": dominant,
            "op_summary": label(dominant),
            "also_covered": [index for index, _ in ranked[1:1 + MAX_ALSO_COVERED]],
            "covered_voxels": count,
            "region_voxels": sum(tally.values()),
        }

    raise ValueError(f"unknown annotation kind: {kind!r}")


class AnnotationStore:
    """Thread-safe collection of annotations for the current session."""

    def __init__(self, max_annotations: int = MAX_ANNOTATIONS) -> None:
        self._lock = threading.Lock()
        self._items: List[Annotation] = []
        self._max = max_annotations
        self._next_id = 1

    def add(
        self,
        structure: MinecraftStructure,
        structure_version: int,
        kind: str,
        note: str,
        pos: Optional[Sequence[int]] = None,
        start: Optional[Sequence[int]] = None,
        end: Optional[Sequence[int]] = None,
        op_index: Optional[int] = None,
    ) -> Annotation:
        """Resolve and store one annotation. Raises ValueError on bad input."""
        note = note.strip()
        if not note:
            raise ValueError("an annotation needs a note")
        resolved = resolve_target(
            structure, kind, pos=pos, start=start, end=end, op_index=op_index
        )
        with self._lock:
            annotation = Annotation(
                id=self._next_id,
                structure_version=structure_version,
                kind=kind,  # type: ignore[arg-type]
                note=note,
                pos=list(pos) if pos is not None else None,
                start=list(start) if start is not None else None,
                end=list(end) if end is not None else None,
                **resolved,
            )
            self._next_id += 1
            self._items.append(annotation)
            if len(self._items) > self._max:
                del self._items[0]
            return annotation

    def open(self) -> List[Annotation]:
        """Unresolved annotations, oldest first — the order the user wrote them."""
        with self._lock:
            return [a for a in self._items if a.status == "open"]

    def all(self) -> List[Annotation]:
        with self._lock:
            return list(self._items)

    def resolve(self, ids: Optional[Sequence[int]] = None) -> List[int]:
        """Mark annotations resolved. ``None`` resolves every open one.

        Returns the ids actually changed, so a caller can tell "resolved 3" from
        "those were already resolved, or never existed".
        """
        with self._lock:
            wanted = None if ids is None else set(ids)
            changed = []
            for annotation in self._items:
                if annotation.status != "open":
                    continue
                if wanted is None or annotation.id in wanted:
                    annotation.status = "resolved"
                    changed.append(annotation.id)
            return changed

    def remove(self, annotation_id: int) -> bool:
        """Delete one annotation outright — the tray's "x" button."""
        with self._lock:
            for i, annotation in enumerate(self._items):
                if annotation.id == annotation_id:
                    del self._items[i]
                    return True
            return False

    def counts(self) -> Tuple[int, int]:
        """(open, total). Cheap enough for the status endpoint to include."""
        with self._lock:
            return sum(1 for a in self._items if a.status == "open"), len(self._items)

    def clear(self) -> None:
        """Drop everything, ids included. Mainly for tests.

        Unlike ``resolve()`` this resets the id counter, so a fresh store starts
        at 1 again. Nothing in a real session calls it.
        """
        with self._lock:
            self._items.clear()
            self._next_id = 1


# Process-wide store, written from the HTTP thread and read by the MCP tools.
ANNOTATIONS = AnnotationStore()
