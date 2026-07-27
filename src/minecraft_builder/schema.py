"""JSON schema definitions for Minecraft structures.

A structure can be described three ways, freely mixed:

* ``blocks`` — explicit per-voxel placements (the original format).
* ``operations`` — declarative shape primitives (cuboid, sphere, ...) that the
  server expands into blocks. This is dramatically more token-efficient: a solid
  wall is one operation instead of hundreds of block entries.

Operations and blocks are applied in order, and later placements overwrite
earlier ones at the same coordinate — so you can fill a solid wall and then
carve a window out of it with ``air``.
"""

from typing import Dict, List, Literal, Optional, Tuple, Union
from typing_extensions import Annotated

from pydantic import BaseModel, Field

from . import shapes

# An [x, y, z] coordinate. A list (not a model) keeps the JSON compact for the LLM.
Vec3 = Annotated[List[int], Field(min_length=3, max_length=3)]

# The running block map an operation reads from and writes to.
BlockMap = Dict[Tuple[int, int, int], str]


class BlockData(BaseModel):
    """Represents a single block in the structure."""
    x: int = Field(..., description="X coordinate (relative to structure origin)")
    y: int = Field(..., description="Y coordinate (relative to structure origin)")
    z: int = Field(..., description="Z coordinate (relative to structure origin)")
    block_type: str = Field(..., description="Minecraft block ID (e.g., 'minecraft:stone', 'oak_planks')")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "examples": [
                {"x": 0, "y": 0, "z": 0, "block_type": "minecraft:stone"},
                {"x": 1, "y": 0, "z": 0, "block_type": "oak_planks"},
            ]
        },
    }


class StructureSize(BaseModel):
    """Dimensions of the structure."""
    width: int = Field(..., ge=0, description="Width (X axis)")
    height: int = Field(..., ge=0, description="Height (Y axis)")
    length: int = Field(..., ge=0, description="Length (Z axis)")


# --------------------------------------------------------------------------- #
# Shape operations
# --------------------------------------------------------------------------- #

class _Operation(BaseModel):
    """Base class: every operation mutates a shared block map in place."""

    def apply(self, blocks: BlockMap) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class CuboidOp(_Operation):
    op: Literal["cuboid"]
    start: Vec3 = Field(..., description="One corner [x, y, z]")
    end: Vec3 = Field(..., description="Opposite corner [x, y, z] (inclusive)")
    block: str = Field(..., description="Block ID to fill with")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.cuboid(tuple(self.start), tuple(self.end)):
            blocks[c] = self.block


class HollowBoxOp(_Operation):
    op: Literal["hollow_box"]
    start: Vec3 = Field(..., description="One corner [x, y, z]")
    end: Vec3 = Field(..., description="Opposite corner [x, y, z] (inclusive)")
    block: str = Field(..., description="Block ID for the shell")
    walls: bool = Field(True, description="Include the four vertical sides")
    floor: bool = Field(True, description="Include the bottom face")
    ceiling: bool = Field(True, description="Include the top face")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.hollow_box(
            tuple(self.start), tuple(self.end),
            walls=self.walls, floor=self.floor, ceiling=self.ceiling,
        ):
            blocks[c] = self.block


class SphereOp(_Operation):
    op: Literal["sphere"]
    center: Vec3 = Field(..., description="Centre [x, y, z]")
    radius: int = Field(..., ge=0, description="Radius in blocks")
    block: str = Field(..., description="Block ID to fill with")
    hollow: bool = Field(False, description="Only the outer shell if true")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.sphere(tuple(self.center), self.radius, hollow=self.hollow):
            blocks[c] = self.block


class CylinderOp(_Operation):
    op: Literal["cylinder"]
    center: Vec3 = Field(..., description="Centre of the base cap [x, y, z]")
    radius: int = Field(..., ge=0, description="Radius in blocks")
    height: int = Field(..., ge=1, description="Length along the axis in blocks")
    axis: Literal["x", "y", "z"] = Field("y", description="Axis the cylinder extends along")
    block: str = Field(..., description="Block ID to fill with")
    hollow: bool = Field(False, description="Open tube (ring wall) if true")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.cylinder(
            tuple(self.center), self.radius, self.height,
            axis=self.axis, hollow=self.hollow,
        ):
            blocks[c] = self.block


class LineOp(_Operation):
    op: Literal["line"]
    start: Vec3 = Field(..., description="Start point [x, y, z]")
    end: Vec3 = Field(..., description="End point [x, y, z]")
    block: str = Field(..., description="Block ID to fill with")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.line(tuple(self.start), tuple(self.end)):
            blocks[c] = self.block


class PyramidOp(_Operation):
    op: Literal["pyramid"]
    center: Vec3 = Field(..., description="Centre of the base layer [x, y, z]")
    base: int = Field(..., ge=0, description="Half-width of the base (apex height = base)")
    axis: Literal["x", "y", "z"] = Field("y", description="Axis the pyramid narrows along")
    block: str = Field(..., description="Block ID to fill with")
    hollow: bool = Field(False, description="Only the perimeter of each layer if true")

    def apply(self, blocks: BlockMap) -> None:
        for c in shapes.pyramid(
            tuple(self.center), self.base, axis=self.axis, hollow=self.hollow,
        ):
            blocks[c] = self.block


class BlockOp(_Operation):
    op: Literal["block"]
    pos: Vec3 = Field(..., description="Position [x, y, z]")
    block: str = Field(..., description="Block ID to place")

    def apply(self, blocks: BlockMap) -> None:
        blocks[tuple(self.pos)] = self.block


class ReplaceOp(_Operation):
    op: Literal["replace"]
    start: Vec3 = Field(..., description="One corner of the region [x, y, z]")
    end: Vec3 = Field(..., description="Opposite corner [x, y, z] (inclusive)")
    from_block: str = Field(..., description="Block ID to look for")
    to_block: str = Field(..., description="Block ID to swap it to ('air' to remove)")

    def apply(self, blocks: BlockMap) -> None:
        target = _match_key(from_block := self.from_block)
        for c in shapes.cuboid(tuple(self.start), tuple(self.end)):
            existing = blocks.get(c)
            if existing is not None and _match_key(existing) == target:
                blocks[c] = self.to_block


def _match_key(block_id: str) -> str:
    """Normalise a block id for equality checks in replace.

    Compares on the namespaced id but ignores block-state suffixes so that
    ``oak_log`` matches ``minecraft:oak_log[axis=y]``.
    """
    base = block_id.split("[", 1)[0]
    if ":" not in base:
        base = f"minecraft:{base}"
    return base


# Discriminated union — pydantic routes on the ``op`` field.
Operation = Annotated[
    Union[
        CuboidOp, HollowBoxOp, SphereOp, CylinderOp,
        LineOp, PyramidOp, BlockOp, ReplaceOp,
    ],
    Field(discriminator="op"),
]


class MinecraftStructure(BaseModel):
    """Complete Minecraft structure definition."""
    name: str = Field(..., description="Name of the structure")
    blocks: List[BlockData] = Field(default_factory=list, description="Explicit per-voxel blocks")
    operations: List[Operation] = Field(default_factory=list, description="Declarative shape primitives")
    size: Optional[StructureSize] = Field(None, description="Structure dimensions (auto-calculated)")
    description: Optional[str] = Field(None, description="Optional description of the structure")

    def expand(self) -> BlockMap:
        """Resolve blocks + operations, in order, into a coordinate->block map.

        Later placements overwrite earlier ones at the same coordinate, so
        operations can layer (fill a wall, then carve windows with ``air``).
        """
        block_map: BlockMap = {}
        for b in self.blocks:
            block_map[(b.x, b.y, b.z)] = b.block_type
        for operation in self.operations:
            operation.apply(block_map)
        return block_map

    def calculate_size(self) -> StructureSize:
        """Bounding-box size from the fully expanded block map."""
        block_map = self.expand()
        if not block_map:
            return StructureSize(width=0, height=0, length=0)
        xs = [c[0] for c in block_map]
        ys = [c[1] for c in block_map]
        zs = [c[2] for c in block_map]
        return StructureSize(
            width=max(xs) - min(xs) + 1,
            height=max(ys) - min(ys) + 1,
            length=max(zs) - min(zs) + 1,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "simple_hut",
                "description": "A hollow oak box with a window",
                "operations": [
                    {"op": "hollow_box", "start": [0, 0, 0], "end": [4, 3, 4],
                     "block": "oak_planks", "ceiling": False},
                    {"op": "block", "pos": [4, 2, 2], "block": "glass"},
                ],
            }]
        }
    }
