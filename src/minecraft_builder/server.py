"""MCP Server for Minecraft structure generation."""

import json
import sys
import traceback
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent, Icon
from pydantic import ValidationError

from .schema import MinecraftStructure
from .converter import SchematicConverter
from .preview import render_preview, stats_summary
from .style import STYLE_CHECKLIST, load_style_guide
from .paths import (
    open_in_file_manager,
    resolve_input_path,
    resolve_output_directory,
)
from .versions import (
    DEFAULT_VERSION,
    SUPPORTED_VERSIONS,
    normalize_version,
    validate_block_ids,
)


# Initialize MCP server
app = Server("minecraft-builder")


def _log(message: str) -> None:
    """Log to stderr — stdout is reserved for the MCP stdio transport."""
    print(message, file=sys.stderr)


def _load_structure(arguments: Any) -> MinecraftStructure:
    """Parse a MinecraftStructure from structure_json or json_file_path.

    Shared by create_minecraft_structure and preview_structure. Raises
    ValueError if neither input is provided (and lets json/file/validation
    errors propagate to the caller's handlers).
    """
    if arguments.get("json_file_path"):
        # WSL->Windows conversion only applies on native Windows.
        json_file = resolve_input_path(arguments["json_file_path"])
        with open(json_file, "r") as f:
            structure_data = json.load(f)
    elif arguments.get("structure_json"):
        structure_data = json.loads(arguments["structure_json"])
    else:
        raise ValueError("Must provide either structure_json or json_file_path")
    return MinecraftStructure(**structure_data)


def _format_block_warnings(unknown: dict, mc_version: str) -> str:
    """Render unknown-block warnings (with suggestions) as a message block.

    Returns an empty string when nothing is unknown, so it can be dropped into
    the success message unconditionally.
    """
    if not unknown:
        return ""
    lines = [f"\n⚠️  **Unrecognised block IDs for {mc_version}** "
             "(built anyway — check these if the import looks wrong):"]
    for block_id, suggestions in unknown.items():
        hint = f" — did you mean: {', '.join(suggestions)}?" if suggestions else ""
        lines.append(f"- `{block_id}`{hint}")
    lines.append("")
    return "\n".join(lines)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="create_minecraft_structure",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzMiAzMiI+PHJlY3QgZmlsbD0iIzU0MzIxYiIgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIi8+PHJlY3QgZmlsbD0iIzZkNDIyZSIgeD0iMCIgeT0iMCIgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2Ii8+PHJlY3QgZmlsbD0iIzZkNDIyZSIgeD0iMTYiIHk9IjE2IiB3aWR0aD0iMTYiIGhlaWdodD0iMTYiLz48L3N2Zz4=", mimeType="image/svg+xml")],
            description="""Creates a Minecraft structure file (.schem) from a JSON structure definition.

PREFER SHAPE OPERATIONS over listing blocks one by one. Describing a wall as a
single "cuboid" operation instead of hundreds of block entries is far more
compact and avoids truncation on large builds. Use raw "blocks" only for
scattered details a shape can't express.

A structure has: name, optional description, and any mix of "operations" and
"blocks". Operations and blocks apply IN ORDER, and later placements overwrite
earlier ones at the same coordinate — so you can fill a solid wall, then carve
a window out of it by placing "air" over part of it.

Coordinates are [x, y, z] integer lists. X=width, Y=height (up), Z=length.
They may be negative; the tool re-centres the structure automatically.

OPERATIONS (each needs an "op" and a "block"):
- cuboid:     solid box.  {"op":"cuboid","start":[x,y,z],"end":[x,y,z],"block":"stone"}
- hollow_box: box shell.  {"op":"hollow_box","start":[..],"end":[..],"block":"oak_planks","walls":true,"floor":true,"ceiling":false}
- sphere:     {"op":"sphere","center":[x,y,z],"radius":5,"block":"glass","hollow":true}
- cylinder:   {"op":"cylinder","center":[x,y,z],"radius":3,"height":10,"axis":"y","block":"stone","hollow":false}
- line:       {"op":"line","start":[..],"end":[..],"block":"glowstone"}
- pyramid:    {"op":"pyramid","center":[x,y,z],"base":6,"axis":"y","block":"sandstone","hollow":false}
- block:      single block.  {"op":"block","pos":[x,y,z],"block":"torch"}
- replace:    swap blocks in a region.  {"op":"replace","start":[..],"end":[..],"from_block":"stone","to_block":"air"}

Block IDs may include states, e.g. "oak_log[axis=y]", "oak_stairs[facing=north]".
The "minecraft:" namespace is added automatically if omitted. Block IDs are
validated against the target version's registry; unknown vanilla blocks produce
a warning with suggestions (set "strict" to make them an error instead).

Example — a hollow stone hut with a doorway:
{
  "name": "stone_hut",
  "operations": [
    {"op": "hollow_box", "start": [0,0,0], "end": [6,4,6], "block": "stone", "ceiling": false},
    {"op": "cuboid", "start": [3,1,0], "end": [3,3,0], "block": "air"}
  ]
}

INPUT METHODS:
- Small/medium builds: provide the JSON directly in structure_json.
- Very large builds: write the JSON to a file and pass json_file_path instead.

""" + STYLE_CHECKLIST + """

Before calling this tool, ask the user where they would like to save the .schem file.""",
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
                    },
                    "mc_version": {
                        "type": "string",
                        "enum": sorted(SUPPORTED_VERSIONS),
                        "description": "Target Minecraft version for the .schem. Defaults to " + DEFAULT_VERSION + "."
                    },
                    "strict": {
                        "type": "boolean",
                        "description": "If true, unrecognised block IDs cause an error instead of a warning. Default false."
                    }
                },
                "required": ["output_directory"]
            }
        ),
        Tool(
            name="open_output_folder",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmYzEwNyIgZD0iTTIwIDZoLThsLTItMkg0Yy0xLjEgMC0xLjk5LjktMS45OSAyTDIgMThjMCAxLjEuOSAyIDIgMmgxNmMxLjEgMCAyLS45IDItMlY4YzAtMS4xLS45LTItMi0yeiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Opens a folder in the operating system's file manager, optionally selecting a specific file.

Works on Windows (Explorer), macOS (Finder) and Linux (xdg-open). File
highlighting is supported on Windows/macOS; on Linux the containing folder is
opened. Use this after creating a Minecraft structure to help the user find the
file easily.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Full path to the folder to open (e.g., '/home/user/Desktop' or 'C:\\Users\\josh\\Desktop')"
                    },
                    "select_file": {
                        "type": "string",
                        "description": "Optional: Full path to a file to select/highlight in the folder (Windows/macOS only)"
                    }
                },
                "required": ["folder_path"]
            }
        ),
        Tool(
            name="get_build_style_guide",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHJlY3QgZmlsbD0iIzhkOGQ4ZCIgeD0iMSIgeT0iNCIgd2lkdGg9IjciIGhlaWdodD0iMTYiLz48cmVjdCBmaWxsPSIjOWM2YjNmIiB4PSI4IiB5PSI0IiB3aWR0aD0iNyIgaGVpZ2h0PSIxNiIvPjxyZWN0IGZpbGw9IiM0YTY3NDEiIHg9IjE1IiB5PSI0IiB3aWR0aD0iOCIgaGVpZ2h0PSIxNiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Returns the Minecraft build style guide: how to make a structure look GOOD, not just valid.

Call this BEFORE designing any build larger than a few dozen blocks. You cannot
see the generated structure — there is no render or feedback loop — so build
quality is decided entirely by the rules you apply before emitting JSON.

Covers: block palettes (3-5 blocks at 50/30/20, with ready-made themed palettes
for medieval, castle, cottage, modern, japanese, desert, nordic, industrial,
fantasy and nether), depth techniques that stop walls reading as flat, roof pitch
and proportion numbers, silhouette, lighting, ground transitions, a cookbook of
shape-operation recipes (gable roof, round tower, arch, battlements, plinth and
cornice), anti-patterns, and a pre-flight checklist to run before building.

Takes no arguments.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="preview_structure",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHJlY3QgZmlsbD0iIzMzMyIgd2lkdGg9IjI0IiBoZWlnaHQ9IjI0Ii8+PHRleHQgeD0iMyIgeT0iMTciIGZpbGw9IiM1ZjUiIGZvbnQtZmFtaWx5PSJtb25vc3BhY2UiIGZvbnQtc2l6ZT0iMTMiPiZndDtfPC90ZXh0Pjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Renders an ASCII preview of a structure WITHOUT saving a file.

You cannot see the generated build, so use this to sanity-check geometry before
calling create_minecraft_structure: is the doorway where you meant it, did the
sphere come out round, is the interior actually hollow? Returns per-layer top-
down slices (one grid per Y level, rows=Z, cols=X), a block legend, and stats
(size, solid/air counts, fill ratio, most-common blocks).

Takes the same structure input as create_minecraft_structure (structure_json or
json_file_path). Large footprints show stats only.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure_json": {
                        "type": "string",
                        "description": "JSON string defining the structure (same format as create_minecraft_structure)."
                    },
                    "json_file_path": {
                        "type": "string",
                        "description": "Path to a .json structure file (alternative to structure_json)."
                    }
                }
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""

    if name == "get_build_style_guide":
        return [TextContent(type="text", text=load_style_guide())]

    if name == "preview_structure":
        try:
            structure = _load_structure(arguments)
            return [TextContent(type="text", text=render_preview(structure))]
        except (json.JSONDecodeError, FileNotFoundError, ValidationError, ValueError) as e:
            return [TextContent(type="text", text=f"❌ Error: could not preview structure - {str(e)}")]
        except Exception as e:
            _log(f"preview_structure failed: {traceback.format_exc()}")
            return [TextContent(type="text", text=f"❌ Error previewing structure: {type(e).__name__}: {str(e)}")]

    # "open_folder_in_explorer" kept as a backwards-compatible alias.
    if name in ("open_output_folder", "open_folder_in_explorer"):
        folder_path = arguments["folder_path"]
        select_file = arguments.get("select_file")

        try:
            message = open_in_file_manager(folder_path, select_file)
            return [TextContent(type="text", text=f"✓ {message}")]
        except FileNotFoundError:
            return [
                TextContent(
                    type="text",
                    text="❌ Error opening folder: no file-manager command found "
                         "(expected explorer/open/xdg-open on this system)."
                )
            ]
        except Exception as e:
            _log(f"open_output_folder failed: {traceback.format_exc()}")
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error opening folder: {str(e)}"
                )
            ]

    if name != "create_minecraft_structure":
        raise ValueError(f"Unknown tool: {name}")

    try:
        # Parse the structure (from structure_json or json_file_path)
        structure = _load_structure(arguments)
        block_map = structure.expand()

        if not block_map:
            return [
                TextContent(
                    type="text",
                    text="❌ Error: Structure is empty - provide at least one block or operation."
                )
            ]

        # Resolve and validate the target Minecraft version
        try:
            mc_version = normalize_version(arguments.get("mc_version") or DEFAULT_VERSION)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ Error: {str(e)}")]

        # Validate block IDs against the version's registry
        unknown = validate_block_ids(block_map.values(), mc_version)
        warning_text = _format_block_warnings(unknown, mc_version)

        if unknown and arguments.get("strict"):
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error: unrecognised block IDs (strict mode)\n{warning_text}"
                )
            ]

        # Resolve output directory (friendly shortcuts + XDG on Linux)
        output_dir = resolve_output_directory(arguments["output_directory"])

        # Determine output filename
        output_filename = arguments.get("output_filename") or structure.name
        if not output_filename.endswith(".schem"):
            output_filename += ".schem"

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename

        # Convert to schematic
        result_path = SchematicConverter.to_schematic(structure, str(output_path), mc_version)

        return [
            TextContent(
                type="text",
                text=f"""✓ Successfully created Minecraft structure!

📁 **File saved to:**
{result_path}

📊 **Structure Info:**
- Name: {structure.name}
- Target version: {mc_version}
{stats_summary(block_map)}
{warning_text}
🎮 **Import to Minecraft:**
- WorldEdit: `//schem load {output_filename.replace('.schem', '')}`

💡 **Tip:** I can open this folder in your file manager for you if you'd like!
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
    except ValueError as e:
        # e.g. missing structure input from _load_structure
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
    except Exception as e:
        # stderr only — stdout carries the MCP protocol.
        _log(f"create_minecraft_structure failed: {traceback.format_exc()}")
        return [
            TextContent(
                type="text",
                text=f"❌ Error creating structure: {type(e).__name__}: {str(e)}"
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
