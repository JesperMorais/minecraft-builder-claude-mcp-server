"""Converts JSON structure definitions to Minecraft schematic files."""

from pathlib import Path
from typing import Dict
from mcschematic import MCSchematic, MCStructure, Version

from .schema import MinecraftStructure, BlockData


class SchematicConverter:
    """Converts MinecraftStructure to .schem format (Sponge Schematic v2)."""

    # Common block mappings (simplified namespace handling)
    BLOCK_NAMESPACE_MAP = {
        "stone": "minecraft:stone",
        "dirt": "minecraft:dirt",
        "grass_block": "minecraft:grass_block",
        "oak_planks": "minecraft:oak_planks",
        "oak_log": "minecraft:oak_log",
        "glass": "minecraft:glass",
        "cobblestone": "minecraft:cobblestone",
        "air": "minecraft:air",
    }

    @staticmethod
    def normalize_block_id(block_id: str) -> str:
        """Ensure block ID has minecraft: namespace."""
        if ":" not in block_id:
            return SchematicConverter.BLOCK_NAMESPACE_MAP.get(block_id, f"minecraft:{block_id}")
        return block_id

    @staticmethod
    def to_schematic(structure: MinecraftStructure, output_path: str) -> str:
        """Convert MinecraftStructure to .schem file.

        Args:
            structure: The structure to convert
            output_path: Path where the .schem file will be saved

        Returns:
            Absolute path to the created file
        """
        # Ensure size is calculated
        if not structure.size:
            structure.size = structure.calculate_size()

        size = structure.size

        # Create MC structure
        mc_structure = MCStructure()

        # Place blocks
        for block in structure.blocks:
            if 0 <= block.x < size.width and 0 <= block.y < size.height and 0 <= block.z < size.length:
                normalized_id = SchematicConverter.normalize_block_id(block.block_type)
                # mcschematic uses setBlock((x, y, z), block_id)
                mc_structure.setBlock((block.x, block.y, block.z), normalized_id)

        # Wrap in schematic
        schem = MCSchematic(mc_structure)

        # Ensure output directory exists
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Save the schematic (schemName should be without .schem extension)
        schem_name = output_file.stem  # filename without extension
        schem.save(outputFolderPath=str(output_file.parent), schemName=schem_name, version=Version.JE_1_19_4)

        return str(output_file.absolute())
