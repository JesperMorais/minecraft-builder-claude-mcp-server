"""Converts JSON structure definitions to Minecraft schematic files."""

from pathlib import Path
from typing import Tuple

from mcschematic import MCSchematic, MCStructure, Version

from .schema import MinecraftStructure, StructureSize


class SchematicConverter:
    """Converts a MinecraftStructure to .schem format (Sponge Schematic v2)."""

    @staticmethod
    def normalize_block_id(block_id: str) -> str:
        """Ensure a block ID has the ``minecraft:`` namespace.

        Block-state suffixes are preserved, e.g. ``oak_log[axis=y]`` becomes
        ``minecraft:oak_log[axis=y]`` while ``minecraft:stone`` is untouched.
        """
        base = block_id.split("[", 1)[0]
        if ":" in base:
            return block_id
        return f"minecraft:{block_id}"

    @staticmethod
    def to_schematic(structure: MinecraftStructure, output_path: str) -> str:
        """Convert a MinecraftStructure to a .schem file.

        The full block map (explicit blocks + expanded shape operations) is
        translated so that its minimum corner sits at the origin. This preserves
        blocks placed at negative coordinates instead of silently dropping them.

        Args:
            structure: The structure to convert.
            output_path: Path where the .schem file will be saved.

        Returns:
            Absolute path to the created file.
        """
        block_map = structure.expand()

        mc_structure = MCStructure()
        if block_map:
            min_x = min(c[0] for c in block_map)
            min_y = min(c[1] for c in block_map)
            min_z = min(c[2] for c in block_map)
            for (x, y, z), block_type in block_map.items():
                normalized_id = SchematicConverter.normalize_block_id(block_type)
                mc_structure.setBlock(
                    (x - min_x, y - min_y, z - min_z), normalized_id
                )

        schem = MCSchematic(mc_structure)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # schemName should be without the .schem extension.
        schem_name = output_file.stem
        schem.save(
            outputFolderPath=str(output_file.parent),
            schemName=schem_name,
            version=Version.JE_1_19_4,
        )

        return str(output_file.absolute())
