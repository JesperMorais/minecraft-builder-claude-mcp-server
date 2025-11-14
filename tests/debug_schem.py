"""Debug script to inspect the generated schematic file."""

import sys
sys.path.insert(0, 'src')

from minecraft_builder.schema import MinecraftStructure, BlockData
from minecraft_builder.converter import SchematicConverter
import nbtlib

# Create a simple structure
structure = MinecraftStructure(
    name="debug_test",
    blocks=[
        BlockData(x=0, y=0, z=0, block_type="stone"),
        BlockData(x=1, y=0, z=0, block_type="stone"),
    ]
)

# Generate the schematic
output_path = "minecraft_structures/debug_test.schem"
SchematicConverter.to_schematic(structure, output_path)

# Read it back and inspect
print("Reading generated schematic...")
try:
    nbt_file = nbtlib.load(output_path)
    print("\nRoot keys:", list(nbt_file.keys()))
    print("\nRoot compound keys:", list(nbt_file[""].keys()))
    print("\nVersion:", nbt_file[""]["Version"])
    print("DataVersion:", nbt_file[""]["DataVersion"])
    print("Width:", nbt_file[""]["Width"])
    print("Height:", nbt_file[""]["Height"])
    print("Length:", nbt_file[""]["Length"])
    print("\nMetadata:", nbt_file[""]["Metadata"])
    print("\nPalette:", nbt_file[""]["Palette"])
    print("PaletteMax:", nbt_file[""]["PaletteMax"])
    print("\nBlockData length:", len(nbt_file[""]["BlockData"]))
    print("BlockData (first 20 bytes):", list(nbt_file[""]["BlockData"][:20]))
    print("\nOffset:", nbt_file[""]["Offset"])
except Exception as e:
    print(f"Error reading: {e}")
    import traceback
    traceback.print_exc()
