"""MCP Server for Minecraft structure generation."""

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent, EmbeddedResource, BlobResourceContents, Icon
from pydantic import ValidationError

from .schema import MinecraftStructure
from .converter import SchematicConverter


# Initialize MCP server
app = Server("minecraft-builder")

# Default output directory - use user's Desktop for easy access
import os
OUTPUT_DIR = Path(os.path.expanduser("~")) / "Desktop" / "minecraft_structures"


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="create_minecraft_structure",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzMiAzMiI+PHJlY3QgZmlsbD0iIzU0MzIxYiIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIi8+PHJlY3QgZmlsbD0iIzZkNDIyZSIgeD0iMCIgeT0iMCIgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2Ii8+PHJlY3QgZmlsbD0iIzZkNDIyZSIgeD0iMTYiIHk9IjE2IiB3aWR0aD0iMTYiIGhlaWdodD0iMTYiLz48L3N2Zz4=", mimeType="image/svg+xml")],
            description="""Creates a Minecraft structure file (.schem) from a JSON structure definition.

The JSON should define a 3D structure using blocks with coordinates. Each block has:
- x, y, z: Integer coordinates (relative to origin, starting from 0)
- block_type: Minecraft block ID (e.g., "stone", "oak_planks", "minecraft:glass")

Example structure:
{
  "name": "simple_tower",
  "description": "A small stone tower",
  "blocks": [
    {"x": 0, "y": 0, "z": 0, "block_type": "stone"},
    {"x": 1, "y": 0, "z": 0, "block_type": "stone"},
    {"x": 0, "y": 1, "z": 0, "block_type": "stone"},
    {"x": 1, "y": 1, "z": 0, "block_type": "stone"}
  ]
}

The structure will be saved as a .schem file that can be imported into Minecraft using WorldEdit or similar tools.

IMPORTANT:
- For small/medium structures (< 300 blocks): provide the JSON directly in structure_json
- For large structures (300-800 blocks): try structure_json first, if it gets truncated, create the JSON file and use json_file_path
- For very large structures (800+ blocks): the JSON might be too large for any method. Consider breaking into smaller pieces or simplifying.

PATH REQUIREMENTS:
- json_file_path must be a Windows path (e.g., C:\\Users\\josh\\Desktop\\file.json)
- If you create files in your workspace, ask the user to download the JSON and tell you where they saved it
- Before calling this tool, ask the user where they would like to save the .schem file.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure_json": {
                        "type": "string",
                        "description": "JSON string defining the Minecraft structure. Use this for small/medium structures. For large structures, use json_file_path instead."
                    },
                    "json_file_path": {
                        "type": "string",
                        "description": "Path to a .json file containing the structure definition. Use this for large/complex structures to avoid truncation. Provide either this OR structure_json, not both."
                    },
                    "output_directory": {
                        "type": "string",
                        "description": "Full path to the directory where the .schem file should be saved (e.g., 'C:\\Users\\josh\\Desktop' or 'C:\\Users\\josh\\Documents'). Ask the user for this before calling the tool."
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Optional custom filename (without extension). Defaults to the structure's name field."
                    }
                },
                "required": ["output_directory"]
            }
        ),
        Tool(
            name="open_folder_in_explorer",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmYzEwNyIgZD0iTTIwIDZoLThsLTItMkg0Yy0xLjEgMC0xLjk5LjktMS45OSAyTDIgMThjMCAxLjEuOSAyIDIgMmgxNmMxLjEgMCAyLS45IDItMlY4YzAtMS4xLS45LTItMi0yeiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Opens a folder in Windows Explorer, optionally selecting a specific file.

Use this after creating a Minecraft structure to help the user find the file easily.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Full path to the folder to open (e.g., 'C:\\Users\\josh\\Desktop')"
                    },
                    "select_file": {
                        "type": "string",
                        "description": "Optional: Full path to a file to select/highlight in the folder"
                    }
                },
                "required": ["folder_path"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""

    if name == "open_folder_in_explorer":
        import subprocess

        folder_path = arguments["folder_path"]
        select_file = arguments.get("select_file")

        try:
            if select_file:
                # Open explorer and select the specific file
                subprocess.run(['explorer', '/select,', select_file])
                return [
                    TextContent(
                        type="text",
                        text=f"✓ Opened Windows Explorer and selected:\n{select_file}"
                    )
                ]
            else:
                # Just open the folder
                subprocess.run(['explorer', folder_path])
                return [
                    TextContent(
                        type="text",
                        text=f"✓ Opened Windows Explorer at:\n{folder_path}"
                    )
                ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error opening folder: {str(e)}"
                )
            ]

    if name != "create_minecraft_structure":
        raise ValueError(f"Unknown tool: {name}")

    try:
        # Get JSON data - either from direct string or from file
        if "json_file_path" in arguments and arguments["json_file_path"]:
            # Read from file
            json_path = arguments["json_file_path"]

            # Try to handle WSL paths (convert to Windows paths)
            if json_path.startswith('/mnt/'):
                # WSL path like /mnt/c/Users/josh/Desktop/file.json
                # Convert to C:\Users\josh\Desktop\file.json
                parts = json_path.split('/')
                drive_letter = parts[2].upper()
                windows_path = drive_letter + ':' + '\\' + '\\'.join(parts[3:])
                json_file = Path(windows_path)
            else:
                json_file = Path(json_path)

            with open(json_file, 'r') as f:
                structure_data = json.load(f)
        elif "structure_json" in arguments and arguments["structure_json"]:
            # Parse from string
            structure_data = json.loads(arguments["structure_json"])
        else:
            return [
                TextContent(
                    type="text",
                    text="❌ Error: Must provide either structure_json or json_file_path"
                )
            ]

        structure = MinecraftStructure(**structure_data)

        # Get output directory from arguments and resolve shortcuts
        output_dir_str = arguments["output_directory"].strip().lower()

        # Handle common shortcuts
        if output_dir_str in ["desktop", "my desktop"]:
            output_dir = Path(os.path.expanduser("~")) / "Desktop"
        elif output_dir_str in ["documents", "my documents"]:
            output_dir = Path(os.path.expanduser("~")) / "Documents"
        elif output_dir_str in ["downloads"]:
            output_dir = Path(os.path.expanduser("~")) / "Downloads"
        else:
            output_dir = Path(arguments["output_directory"])

        # Determine output filename
        output_filename = arguments.get("output_filename") or structure.name
        if not output_filename.endswith(".schem"):
            output_filename += ".schem"

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        # Convert to schematic
        result_path = SchematicConverter.to_schematic(structure, str(output_path))

        # Calculate statistics
        block_count = len(structure.blocks)
        size = structure.size or structure.calculate_size()
        unique_blocks = len(set(block.block_type for block in structure.blocks))

        # Get just the folder path
        folder_path = str(output_dir.absolute())

        return [
            TextContent(
                type="text",
                text=f"""✓ Successfully created Minecraft structure!

📁 **File saved to:**
{result_path}

📊 **Structure Info:**
- Name: {structure.name}
- Size: {size.width}x{size.height}x{size.length} blocks
- Total blocks: {block_count}
- Unique block types: {unique_blocks}

🎮 **Import to Minecraft:**
- WorldEdit: `//schem load {output_filename.replace('.schem', '')}`

💡 **Tip:** I can open this folder in Windows Explorer for you if you'd like!
"""
            )
        ]

    except json.JSONDecodeError as e:
        return [
            TextContent(
                type="text",
                text=f"❌ Error: Invalid JSON structure - {str(e)}"
            )
        ]
    except FileNotFoundError as e:
        return [
            TextContent(
                type="text",
                text=f"❌ Error: JSON file not found - {str(e)}"
            )
        ]
    except ValidationError as e:
        return [
            TextContent(
                type="text",
                text=f"❌ Error: Structure validation failed - {str(e)}"
            )
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"❌ Error creating structure: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )
