"""JSON schema definitions for Minecraft structures."""

from typing import List, Optional
from pydantic import BaseModel, Field


class BlockData(BaseModel):
    """Represents a single block in the structure."""
    x: int = Field(..., description="X coordinate (relative to structure origin)")
    y: int = Field(..., description="Y coordinate (relative to structure origin)")
    z: int = Field(..., description="Z coordinate (relative to structure origin)")
    block_type: str = Field(..., description="Minecraft block ID (e.g., 'minecraft:stone', 'oak_planks')")

    class Config:
        # Allow both 'block_type' and 'type' as field names
        populate_by_name = True
        json_schema_extra = {
            "examples": [
                {"x": 0, "y": 0, "z": 0, "block_type": "minecraft:stone"},
                {"x": 1, "y": 0, "z": 0, "block_type": "oak_planks"}
            ]
        }


class StructureSize(BaseModel):
    """Dimensions of the structure."""
    width: int = Field(..., gt=0, description="Width (X axis)")
    height: int = Field(..., gt=0, description="Height (Y axis)")
    length: int = Field(..., gt=0, description="Length (Z axis)")


class MinecraftStructure(BaseModel):
    """Complete Minecraft structure definition."""
    name: str = Field(..., description="Name of the structure")
    blocks: List[BlockData] = Field(..., description="List of all blocks in the structure")
    size: Optional[StructureSize] = Field(None, description="Structure dimensions (auto-calculated if not provided)")
    description: Optional[str] = Field(None, description="Optional description of the structure")

    def calculate_size(self) -> StructureSize:
        """Calculate the bounding box size from blocks."""
        if not self.blocks:
            return StructureSize(width=0, height=0, length=0)

        max_x = max(block.x for block in self.blocks) + 1
        max_y = max(block.y for block in self.blocks) + 1
        max_z = max(block.z for block in self.blocks) + 1

        return StructureSize(width=max_x, height=max_y, length=max_z)

    class Config:
        json_schema_extra = {
            "examples": [{
                "name": "simple_house",
                "description": "A small wooden cottage",
                "blocks": [
                    {"x": 0, "y": 0, "z": 0, "block_type": "minecraft:oak_planks"},
                    {"x": 1, "y": 0, "z": 0, "block_type": "minecraft:oak_planks"}
                ]
            }]
        }
