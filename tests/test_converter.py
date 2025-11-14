"""Simple test script for the Minecraft structure converter."""

import sys
sys.path.insert(0, 'src')

from minecraft_builder.schema import MinecraftStructure, BlockData
from minecraft_builder.converter import SchematicConverter

# Create a simple 3x3 stone platform
structure = MinecraftStructure(
    name="test_platform",
    description="A simple 3x3 stone platform for testing",
    blocks=[
        BlockData(x=0, y=0, z=0, block_type="stone"),
        BlockData(x=1, y=0, z=0, block_type="stone"),
        BlockData(x=2, y=0, z=0, block_type="stone"),
        BlockData(x=0, y=0, z=1, block_type="stone"),
        BlockData(x=1, y=0, z=1, block_type="stone"),
        BlockData(x=2, y=0, z=1, block_type="stone"),
        BlockData(x=0, y=0, z=2, block_type="stone"),
        BlockData(x=1, y=0, z=2, block_type="stone"),
        BlockData(x=2, y=0, z=2, block_type="stone"),
    ]
)

print("Testing Minecraft Structure Converter...")
print(f"Structure: {structure.name}")
print(f"Blocks: {len(structure.blocks)}")

# Convert to schematic
try:
    output_path = SchematicConverter.to_schematic(structure, "minecraft_structures/test_platform.schem")
    print(f"[OK] Successfully created schematic: {output_path}")

    # Check file exists
    import os
    if os.path.exists(output_path):
        file_size = os.path.getsize(output_path)
        print(f"[OK] File exists: {file_size} bytes")
    else:
        print("[FAIL] File was not created!")
        sys.exit(1)

    print("\n[OK] All tests passed!")

except Exception as e:
    print(f"[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
