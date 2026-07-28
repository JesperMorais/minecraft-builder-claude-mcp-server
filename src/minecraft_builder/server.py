"""MCP Server for Minecraft structure generation."""

import base64
import json
import sys
import traceback
from typing import Any

from mcp.server import Server
from mcp.types import Icon, ImageContent, TextContent, Tool
from pydantic import ValidationError

from .converter import DEFAULT_FORMATS, OUTPUT_FORMATS, SchematicConverter
from .lint import format_report, lint_structure
from .patches import PatchError, apply_patches
from .paths import (
    open_in_file_manager,
    resolve_input_path,
    resolve_output_directory,
)
from .preview import render_preview, stats_summary
from .schema import MinecraftStructure, StructureTooLargeError
from .style import STYLE_CHECKLIST, load_style_guide
from .versions import (
    DEFAULT_VERSION,
    LATEST_VERSION,
    explain_unknown,
    normalize_version,
    supported_versions,
    validate_block_ids,
)
from .web import STATE as viewer_state
from .web import ensure_running as start_viewer
from .web.annotations import ANNOTATIONS as viewer_annotations
from .web.channel import BRIDGE as channel_bridge
from .web.chat import CHAT as viewer_chat
from .web.prompts import PROMPTS as viewer_prompts
from .web.render import (
    DEFAULT_HEIGHT,
    DEFAULT_VIEWS,
    DEFAULT_WIDTH,
    MAX_DIMENSION,
    MIN_DIMENSION,
    RenderedView,
    RenderError,
    default_output_directory,
    render_views,
    select_views,
)

# Added to Claude's system prompt when this server is loaded. It is the only
# place Claude learns what a <channel> event from the viewer means and how to
# answer it, so the workflow lives here rather than being re-explained by the
# user every session.
CHANNEL_INSTRUCTIONS = """\
This server also runs a browser-based build viewer that can act as a chat window.

Prompts typed into it arrive as <channel source="minecraft-builder" chat_id="...">
events. Treat them as build requests from the user, exactly as if they had typed
them in the terminal.

When you handle one:
1. Call show_structure to render the build. The user is looking at the viewer, so
   showing beats describing — and the page updates itself, so they see each
   revision without reloading.
2. Call reply with a short sentence saying what you did, passing back the chat_id
   from the event. Without a reply the browser shows nothing, so always send one,
   including when you hit an error or need a clarification.

Prefer shape operations over per-block lists. Only write files (.schem /
.litematic) when the user asks for one; showing a build saves nothing to disk.

Channels are a gated research preview and are often unavailable (org policy,
Bedrock/Vertex/Foundry, or no startup flag). The same chat then works by
polling: when the user wants to drive builds from the browser, call
await_prompt to wait for their next message, handle it exactly as above
(show_structure, then reply), and call await_prompt again. Keep the loop going
— a timeout round just means the user is thinking; only stop when they tell you
to in the terminal.

The viewer also lets the user mark up a build: click a block, drag a box, or
select an operation, and attach a note. When they ask you to apply their notes:

1. Call get_annotations. Every note names the operation index that placed what
   they clicked, resolved against the version they were looking at.
2. Call patch_operations on those indices. Edit the operation they complained
   about; do NOT regenerate the whole structure, because that quietly changes
   the parts they were happy with. All indices in one call refer to the
   structure as it is before any of them apply.
3. patch_operations shows the result itself, so do not follow it with
   show_structure.
4. Call resolve_annotations to close the notes you handled, then reply saying
   what you changed. Leave a note open if you did not address it, and say so.
"""

# Initialize MCP server
app = Server("minecraft-builder", instructions=CHANNEL_INSTRUCTIONS)

# await_prompt wait bounds, in seconds. The ceiling stays comfortably under the
# 600s client timeout in .mcp.json so a full wait returns a result instead of
# the client killing the call.
DEFAULT_AWAIT_SECONDS = 240.0
MAX_AWAIT_SECONDS = 540.0
MIN_AWAIT_SECONDS = 5.0


def _log(message: str) -> None:
    """Log to stderr — stdout is reserved for the MCP stdio transport."""
    print(message, file=sys.stderr)


def _structure_name() -> str:
    """Name of whatever the viewer is showing, for messages about it."""
    structure = viewer_state.current()
    return structure.name if structure is not None else "the build"


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
    for block_id in unknown:
        lines.append(f"- `{block_id}` — {explain_unknown(block_id, mc_version)}")
    lines.append("")
    return "\n".join(lines)


def _import_instructions(written: dict, stem: str) -> str:
    """Per-format instructions for getting the written files into the game."""
    lines = []
    if "schem" in written:
        lines.append(
            f"- **WorldEdit** (instant paste, needs creative/op): copy the .schem to "
            f"`plugins/WorldEdit/schematics/` (server) or "
            f"`.minecraft/config/worldedit/schematics/` (client), then "
            f"`//schem load {stem}` and `//paste`."
        )
    if "litematic" in written:
        lines.append(
            f"- **Litematica** (hologram to build by hand in survival): copy the "
            f"`.litematic` to `.minecraft/schematics/`, then open the Litematica menu "
            f"(`M` by default), load `{stem}` and create a placement. `Material List` "
            f"shows everything you need to gather."
        )
    return "\n".join(lines) + "\n"


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
- dome:       hemisphere.  {"op":"dome","center":[x,y,z],"radius":6,"axis":"y","block":"glass","hollow":true}
- cone:       base->apex taper (spires, round-tower roofs).  {"op":"cone","center":[x,y,z],"radius":6,"height":7,"axis":"y","block":"dark_oak_planks","hollow":true}
- ellipsoid:  sphere with independent radii (eggs, blobs).  {"op":"ellipsoid","center":[x,y,z],"rx":5,"ry":7,"rz":5,"block":"quartz_block","hollow":true}
- torus:      ring.  {"op":"torus","center":[x,y,z],"major_radius":6,"minor_radius":2,"axis":"y","block":"prismarine"}
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
                    "output_formats": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(OUTPUT_FORMATS)},
                        "description": (
                            "Which file formats to write. Defaults to [\"schem\"]. "
                            "Use \"schem\" for WorldEdit (instant //paste, needs creative/op). "
                            "Use \"litematic\" for Litematica, which shows the build as a "
                            "hologram to construct by hand in survival with a material list. "
                            "Ask for both if the user hasn't said how they intend to build it."
                        )
                    },
                    "mc_version": {
                        "type": "string",
                        # Registry order, not string order — "1.21.10" sorts before "1.21.2".
                        "enum": list(supported_versions()),
                        "description": (
                            "Target Minecraft version for the .schem. Defaults to "
                            + DEFAULT_VERSION + "; newest available is " + LATEST_VERSION
                            + ". Block IDs are validated against the chosen version, and "
                            "newer versions unlock newer blocks — see the style guide's "
                            "version table."
                        )
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
        ),
        Tool(
            name="reply",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iIzYyZGQ5NSIgZD0iTTIwIDJINGEyIDIgMCAwMC0yIDJ2MTJhMiAyIDAgMDAyIDJoNGw0IDQgNC00aDRhMiAyIDAgMDAyLTJWNGEyIDIgMCAwMC0yLTJ6Ii8+PC9zdmc+", mimeType="image/svg+xml")],
            description="""Sends a message back to the build viewer's chat.

Use this to answer a prompt that arrived as a <channel source="minecraft-builder">
event, passing back the chat_id from that event. The user typed in the browser and
is watching it, not the terminal, so a reply is the only thing they see — send one
even when the answer is an error or a question.

Keep it to a sentence or two; the build itself is shown with show_structure.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The message to show in the viewer's chat."
                    },
                    "chat_id": {
                        "type": "string",
                        "description": "The chat_id attribute from the inbound <channel> event."
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="await_prompt",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2IwOGRmZiIgZD0iTTEyIDJhMTAgMTAgMCAxMDAgMjAgMTAgMTAgMCAwMDAtMjB6bTEgNWgtMnY2bDUgMyAxLTEuNy00LTIuM3oiLz48L3N2Zz4=", mimeType="image/svg+xml")],
            description="""Waits for the next prompt typed into the build viewer's chat and returns it.

This is the chat path that works WITHOUT channels — no startup flag, no org
policy, works on Bedrock. Use it whenever the user wants to drive builds from
the browser and channel events are not arriving.

Run it as a loop:
1. Call await_prompt. It blocks until the user types in the viewer (or times out).
2. Handle the returned prompt like any build request: show_structure for builds,
   then reply with a short answer — the user is watching the browser, not the
   terminal.
3. Call await_prompt again to keep listening.

A timeout is not an error — the user is just thinking. Call it again. Stop the
loop only when the user asks you to in the terminal. Prompts typed while you were
building are queued and returned by the next call, oldest first. Starts the
viewer if it is not already running.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout_seconds": {
                        "type": "number",
                        "description": (
                            "How long to wait before giving this round up. "
                            "Default 240, clamped to 5-540 (the ceiling keeps a "
                            "full wait inside the MCP client's own timeout)."
                        )
                    }
                }
            }
        ),
        Tool(
            name="get_annotations",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmYzE1NyIgZD0iTTQgM2gxNGwyIDJ2MTZsLTQtMy00IDMtNC0zLTQgM3oiLz48L3N2Zz4=", mimeType="image/svg+xml")],
            description="""Reads the notes the user has attached to the build in the viewer.

Call this when the user says something like "apply my notes", "I've marked some
things", or when a prompt arrives asking you to act on annotations.

Each note names the **operation index** it refers to, resolved server-side from
the coordinate the user clicked against the version they were looking at. That is
the point: prefer editing that one operation with patch_operations over
regenerating the whole structure, which throws away the parts they liked.

Notes stay open until you call resolve_annotations, so finish the edit first.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_resolved": {
                        "type": "boolean",
                        "description": "Also list notes already dealt with. Default false."
                    }
                }
            }
        ),
        Tool(
            name="patch_operations",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmOGE2NSIgZD0iTTE0IDJsOCA4LTQgMS0xIDQtOC04IDEtNHptLTMgOWw2IDYtNyA3LTYtNnoiLz48L3N2Zz4=", mimeType="image/svg+xml")],
            description="""Edits individual operations of the structure on screen, in place.

Use this instead of re-sending a whole structure when the user wants a change to
part of a build. "Make the roof steeper" is one replace, not a 200-operation
rewrite — and a rewrite tends to quietly change the parts they were happy with.

Indices are the same ones get_annotations reports, and the same ones the viewer's
"colour by operation" toggle shows. **They all refer to the structure as it is
now, before any of these patches apply**, so a batch of edits is written against
what the user saw rather than against each other.

- `replace` — swap the operation at that index
- `insert`  — add before that index (index == count appends)
- `delete`  — remove it

Shows the result automatically, so the user sees the revision without you calling
show_structure again.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "patches": {
                        "type": "array",
                        "description": "Edits to apply. All indices refer to the pre-patch structure.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {
                                    "type": "integer",
                                    "description": "Which entry to act on, as reported by get_annotations."
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["replace", "insert", "delete"],
                                    "description": "What to do at that index."
                                },
                                "operation": {
                                    "type": "object",
                                    "description": "The new operation, same format as create_minecraft_structure's operations. Required for replace and insert."
                                }
                            },
                            "required": ["index", "action"]
                        }
                    }
                },
                "required": ["patches"]
            }
        ),
        Tool(
            name="resolve_annotations",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iIzYyZGQ5NSIgZD0iTTkgMTYuMkw0LjggMTJsLTEuNCAxLjRMOSAxOSAyMSA3bC0xLjQtMS40eiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Marks the user's notes as dealt with, clearing them from the viewer's tray.

Call this after you have actually applied the notes — it is what tells the user
which of their objections you addressed. With no ids, every open note is closed;
pass ids to close only some, which is the honest thing to do when you handled part
of the batch and want to leave the rest open.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Note ids to close. Omit to close all open notes."
                    }
                }
            }
        ),
        Tool(
            name="show_structure",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iIzdmYjNmZiIgZD0iTTEyIDJsOSA1LjJ2OS42TDEyIDIyIDMgMTYuOFY3LjJMMTIgMnoiLz48cGF0aCBmaWxsPSIjNGE4MmQ2IiBkPSJNMTIgMTJsOS00Ljh2OS42TDEyIDIyeiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Displays a structure in a 3D viewer in the user's browser.

Opens (or reuses) a local viewer at http://127.0.0.1:8791/ and renders the
structure there, so the USER can see the build — this is for them, not for you.
Use preview_structure when you need to check the geometry yourself.

Show a build before writing a file whenever the user is likely to want a look
first, and show it again after each revision: the page picks up new versions on
its own, so the user watches the build change without reloading anything.

Blocks are drawn as flat colours, not Minecraft textures. Shape, proportion and
material choice come through; surface detail does not.

Takes the same structure input as create_minecraft_structure (structure_json or
json_file_path). Saves nothing to disk.""",
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
        ),
        Tool(
            name="render_structure",
            icons=[Icon(src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHJlY3QgZmlsbD0iIzNhNDI1MCIgeD0iMSIgeT0iNiIgd2lkdGg9IjIyIiBoZWlnaHQ9IjE0IiByeD0iMiIvPjxwYXRoIGZpbGw9IiMzYTQyNTAiIGQ9Ik04IDNoOGwxLjUgM2gtMTF6Ii8+PGNpcmNsZSBmaWxsPSIjN2ZiM2ZmIiBjeD0iMTIiIGN5PSIxMyIgcj0iNC41Ii8+PGNpcmNsZSBmaWxsPSIjMGQxMTE3IiBjeD0iMTIiIGN5PSIxMyIgcj0iMiIvPjwvc3ZnPg==", mimeType="image/svg+xml")],
            description="""Photographs the build from several angles and hands you the pictures. THIS ONE IS FOR YOU.

Every other feedback path in this server describes a build in words. This one
shows it. show_structure puts a 3D view in front of the *user*; preview_structure
gives you ASCII slices that flatten a roof into a rectangle. render_structure
screenshots the real viewer and returns the images, so you can look at what you
actually made.

Use it after building anything whose appearance matters, before you tell the user
you are done. Then look, honestly: does the roof sit on the walls or float above
them, do the windows line up, is the silhouette a shape or a box, are the
proportions what you intended? When something is wrong, fix that one operation
with patch_operations rather than regenerating — a rewrite quietly changes the
parts that were fine.

Five 800x600 views by default: four isometric corners and one level elevation.
Angles are compass bearings for where the CAMERA STANDS, matching Minecraft's
compass (0 = north = -Z, 90 = east = +X), so the "southeast" view is the one
that shows you the south and east faces.

With no structure argument it renders whatever show_structure last displayed,
which is usually what you want mid-revision. It never changes what the user is
looking at — taking a picture does not bump the version or disturb their notes.

Needs the optional render extra (Playwright + headless Chromium). If it is not
installed the tool says so and names the command; nothing else in this server is
affected.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "structure_json": {
                        "type": "string",
                        "description": "JSON string defining the structure (same format as create_minecraft_structure). Omit to render what show_structure last displayed."
                    },
                    "json_file_path": {
                        "type": "string",
                        "description": "Path to a .json structure file (alternative to structure_json)."
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "description": (
                            "How many angles to render. Default " + str(len(DEFAULT_VIEWS))
                            + ". Fewer is a prefix of the standard set, best first: 1 is the "
                            "isometric corner the user's viewer opens at, 2 adds the level "
                            "elevation, 3 shows the back. Past the named set the extra angles "
                            "are an even orbit. Every image costs you tokens, so ask for what "
                            "you need to judge the build and no more."
                        )
                    },
                    "angles": {
                        "type": "array",
                        "description": "Specific camera angles, overriding count. Use when you want to look at one part of the build.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "azimuth": {
                                    "type": "number",
                                    "description": "Compass bearing for where the camera stands: 0 north, 90 east, 180 south, 270 west."
                                },
                                "elevation": {
                                    "type": "number",
                                    "description": "Degrees above the horizon, -89 to 89. 0 is a level look; 30 is the standard isometric."
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Label for this angle, also used in its filename. Defaults to the bearing."
                                }
                            },
                            "required": ["azimuth", "elevation"]
                        }
                    },
                    "width": {
                        "type": "integer",
                        "minimum": MIN_DIMENSION,
                        "maximum": MAX_DIMENSION,
                        "description": f"Image width in pixels. Default {DEFAULT_WIDTH}."
                    },
                    "height": {
                        "type": "integer",
                        "minimum": MIN_DIMENSION,
                        "maximum": MAX_DIMENSION,
                        "description": f"Image height in pixels. Default {DEFAULT_HEIGHT}."
                    },
                    "output_directory": {
                        "type": "string",
                        "description": "Where to write the PNGs. Defaults to a temp folder, since these are working images from a review loop; pass a directory only if the user wants to keep them."
                    }
                }
            }
        )
    ]


def _render_result(
    structure: MinecraftStructure, rendered: list[RenderedView]
) -> list[TextContent | ImageContent]:
    """A summary, then each angle labelled and shown.

    Labels are interleaved with the images rather than listed up front. The
    content arrives as one flat sequence, so a legend at the top would have to be
    counted back against, and the entire point of the tool is that looking at the
    build should be effortless.
    """
    lines = [
        f"✓ Rendered **{structure.name}** from {len(rendered)} angle(s).",
        "",
        f"📁 Saved to: {rendered[0].path.parent}",
        "",
        "Now look at them. If something is off, edit the operation responsible "
        "with patch_operations — regenerating the whole structure would change "
        "the parts that came out right.",
    ]
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text="\n".join(lines))
    ]
    for index, shot in enumerate(rendered, start=1):
        content.append(TextContent(
            type="text",
            text=(
                f"**{index}. {shot.view.name}** — camera at bearing "
                f"{shot.view.azimuth:g}°, {shot.view.elevation:g}° above the "
                f"horizon · `{shot.path.name}`"
            ),
        ))
        content.append(ImageContent(
            type="image",
            data=base64.b64encode(shot.png).decode("ascii"),
            mimeType="image/png",
        ))
    return content


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent]:
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

    if name == "await_prompt":
        import asyncio

        try:
            timeout = float(arguments.get("timeout_seconds") or DEFAULT_AWAIT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_AWAIT_SECONDS
        timeout = max(MIN_AWAIT_SECONDS, min(timeout, MAX_AWAIT_SECONDS))

        # Make sure there is a page for the user to type into, and that its
        # status dot flips to "listening" for the duration of the wait.
        url = start_viewer()
        prompt = await asyncio.get_running_loop().run_in_executor(
            None, viewer_prompts.take, timeout
        )
        if prompt is None:
            return [TextContent(
                type="text",
                text=(
                    f"No prompt arrived within {timeout:.0f}s. The viewer is at "
                    f"{url}. Call await_prompt again to keep listening — a quiet "
                    "round is not an error."
                ),
            )]
        return [TextContent(
            type="text",
            text=(
                f"Prompt from the viewer:\n\n{prompt['text']}\n\n"
                "Handle it (show_structure for builds), answer with the reply "
                "tool, then call await_prompt again to keep listening."
            ),
        )]

    if name == "reply":
        text = str(arguments.get("text") or "").strip()
        if not text:
            return [TextContent(type="text", text="❌ Error: reply text is empty.")]
        viewer_chat.from_claude(text)
        # A reply is the one thing that proves the channel round trip closes.
        # Outbound events are unacknowledged, so nothing else can tell a delivered
        # push from one a policy-blocked client dropped. confirm() ignores this
        # unless an event was actually pushed first — Claude also calls reply from
        # ordinary terminal turns and from the await_prompt loop, neither of which
        # says anything about the channel.
        if channel_bridge.confirm():
            # Now that the channel is trusted, cancel the queued copies the HTTP
            # layer kept as insurance, so a later await_prompt does not hand back
            # a prompt that has just been answered.
            viewer_prompts.drop_pushed()
        if not viewer_chat.bus.subscriber_count:
            # Worth saying: the reply is recorded and will show up when the page
            # connects, but right now nobody is reading it.
            return [TextContent(
                type="text",
                text="✓ Reply recorded, but no viewer page is currently open."
            )]
        return [TextContent(type="text", text="✓ Sent to the viewer.")]

    if name == "get_annotations":
        include_resolved = bool(arguments.get("include_resolved"))
        notes = viewer_annotations.all() if include_resolved else viewer_annotations.open()
        if not notes:
            return [TextContent(
                type="text",
                text=(
                    "No notes on the build. The user marks blocks or regions in the "
                    "viewer; if they asked you to apply notes and there are none, "
                    "say so rather than guessing what they meant."
                ),
            )]
        current = viewer_state.version
        lines = []
        for note in notes:
            line = note.describe()
            if note.structure_version != current:
                # The index still means what it meant when marked; it may not
                # mean that now. Better to say so than to let Claude patch a
                # stale index silently.
                line += (
                    f"\n     ⚠ marked on version {note.structure_version}, "
                    f"now showing {current} — re-check this index before patching"
                )
            lines.append(line)
        body = "\n".join(lines)
        return [TextContent(
            type="text",
            text=(
                f"{len(notes)} note(s) on **{_structure_name()}** "
                f"(version {current}):\n\n{body}\n\n"
                "Each note names the operation that placed what the user clicked. "
                "Prefer patch_operations on that index over rebuilding the whole "
                "structure, then call resolve_annotations to close them."
            ),
        )]

    if name == "resolve_annotations":
        ids = arguments.get("ids")
        if ids is not None and not isinstance(ids, list):
            return [TextContent(type="text", text="❌ Error: ids must be a list of integers.")]
        try:
            wanted = None if ids is None else [int(i) for i in ids]
        except (TypeError, ValueError):
            return [TextContent(type="text", text="❌ Error: ids must be integers.")]
        closed = viewer_annotations.resolve(wanted)
        if not closed:
            return [TextContent(
                type="text",
                text="No open notes matched, so nothing changed.",
            )]
        remaining, _total = viewer_annotations.counts()
        tail = f" {remaining} still open." if remaining else " The tray is now clear."
        return [TextContent(
            type="text",
            text=f"✓ Closed note(s) {', '.join(str(i) for i in closed)}.{tail}",
        )]

    if name == "patch_operations":
        patches = arguments.get("patches")
        if not isinstance(patches, list) or not patches:
            return [TextContent(
                type="text",
                text="❌ Error: patches must be a non-empty list of edits."
            )]
        on_screen = viewer_state.current()
        if on_screen is None:
            return [TextContent(
                type="text",
                text=(
                    "❌ Error: nothing is on screen to patch. Call show_structure "
                    "with a structure first."
                ),
            )]
        try:
            patched = apply_patches(on_screen, patches)
        except PatchError as e:
            # Deliberately not a traceback: this text is what Claude reads to
            # correct itself, and the message already names the offending patch.
            return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
        except StructureTooLargeError as e:
            return [TextContent(
                type="text",
                text=f"❌ Error: those patches make the structure too large - {str(e)}"
            )]
        except ValidationError as e:
            return [TextContent(type="text", text=f"❌ Error: invalid patched structure - {str(e)}")]

        try:
            block_map = patched.expand()
        except StructureTooLargeError as e:
            return [TextContent(type="text", text=f"❌ Error: structure too large - {str(e)}")]
        if not block_map:
            return [TextContent(
                type="text",
                text="❌ Error: those patches leave nothing to draw — every block would be air."
            )]

        version = viewer_state.put(patched)
        url = start_viewer()
        viewer_chat.announce_structure(version, patched.name)
        size = patched.calculate_size()
        style_report = format_report(lint_structure(patched, block_map))
        applied = ", ".join(
            f"{p.get('action')} #{p.get('index')}" for p in patches
            if isinstance(p, dict)
        )
        return [TextContent(
            type="text",
            text=f"""✓ Patched **{patched.name}** and showed version {version}.

🔗 {url}

- Applied: {applied}
- Now: {len(patched.blocks) + len(patched.operations)} operations, \
{size.width}x{size.height}x{size.length} blocks

📐 {style_report}

The page has already updated, so do not call show_structure for this. If the
patches came from the user's notes, close them with resolve_annotations."""
        )]

    if name == "show_structure":
        try:
            structure = _load_structure(arguments)
            block_map = structure.expand()
            if not block_map:
                return [TextContent(
                    type="text",
                    text="❌ Error: Structure is empty - provide at least one block or operation."
                )]
            version = viewer_state.put(structure)
            url = start_viewer()
            # Nudge any open page to pull the new version immediately, instead of
            # waiting for its next poll.
            viewer_chat.announce_structure(version, structure.name)
            size = structure.calculate_size()
            # Reviewing in the viewer is exactly when style feedback is
            # actionable, so the checklist verdict rides along with every show.
            style_report = format_report(lint_structure(structure, block_map))
            return [TextContent(
                type="text",
                text=f"""✓ Showing **{structure.name}** in the 3D viewer (version {version}).

🔗 {url}

- Size: {size.width}x{size.height}x{size.length} blocks
- Operations: {len(structure.blocks) + len(structure.operations)}

📐 {style_report}

The page updates on its own, so tell the user to open that link once and leave it
open — later versions appear without a reload."""
            )]
        except StructureTooLargeError as e:
            return [TextContent(type="text", text=f"❌ Error: structure too large - {str(e)}")]
        except (json.JSONDecodeError, FileNotFoundError, ValidationError, ValueError) as e:
            return [TextContent(type="text", text=f"❌ Error: could not show structure - {str(e)}")]
        except OSError as e:
            _log(f"show_structure failed to start viewer: {traceback.format_exc()}")
            return [TextContent(
                type="text",
                text=f"❌ Error: could not start the viewer server - {str(e)}"
            )]
        except Exception as e:
            _log(f"show_structure failed: {traceback.format_exc()}")
            return [TextContent(
                type="text",
                text=f"❌ Error showing structure: {type(e).__name__}: {str(e)}"
            )]

    if name == "render_structure":
        import asyncio

        if arguments.get("structure_json") or arguments.get("json_file_path"):
            try:
                structure = _load_structure(arguments)
            except (json.JSONDecodeError, FileNotFoundError, ValidationError, ValueError) as e:
                return [TextContent(
                    type="text",
                    text=f"❌ Error: could not render structure - {str(e)}"
                )]
        else:
            # Defaulting to what is on screen is what makes this callable bare in
            # the middle of a revision, which is when it is wanted most.
            on_screen = viewer_state.current()
            if on_screen is None:
                return [TextContent(
                    type="text",
                    text=(
                        "❌ Error: nothing to render. Pass structure_json, or call "
                        "show_structure first and then call this with no arguments."
                    ),
                )]
            structure = on_screen

        try:
            views = select_views(arguments.get("count"), arguments.get("angles"))
            output_dir = (
                resolve_output_directory(arguments["output_directory"])
                if arguments.get("output_directory")
                else default_output_directory()
            )
            # A browser is neither fast nor async, and the stdio loop has to stay
            # answerable while it works — the viewer's own HTTP server is serving
            # the page being photographed from this same process.
            rendered = await asyncio.to_thread(
                render_views,
                structure,
                output_dir,
                views=views,
                width=int(arguments.get("width") or DEFAULT_WIDTH),
                height=int(arguments.get("height") or DEFAULT_HEIGHT),
            )
        except RenderError as e:
            # Already written for a reader who has to act on it; a traceback here
            # would bury the install command that fixes the common case.
            return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
        except StructureTooLargeError as e:
            return [TextContent(type="text", text=f"❌ Error: structure too large - {str(e)}")]
        except Exception as e:
            _log(f"render_structure failed: {traceback.format_exc()}")
            return [TextContent(
                type="text",
                text=f"❌ Error rendering structure: {type(e).__name__}: {str(e)}"
            )]

        return _render_result(structure, rendered)

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

        # Filename stem, minus any extension the caller included for us.
        stem = arguments.get("output_filename") or structure.name
        for extension in OUTPUT_FORMATS.values():
            if stem.endswith(extension):
                stem = stem[: -len(extension)]
                break

        formats = arguments.get("output_formats") or list(DEFAULT_FORMATS)
        written = SchematicConverter.write_formats(
            structure, output_dir, stem, mc_version, formats
        )

        saved = "\n".join(f"- `{fmt}`: {path}" for fmt, path in written.items())

        # The export is the last chance to catch a guide violation before the
        # build lands in a world, so the checklist verdict is part of the result.
        style_report = format_report(lint_structure(structure, block_map))

        return [
            TextContent(
                type="text",
                text=f"""✓ Successfully created Minecraft structure!

📁 **Files saved:**
{saved}

📊 **Structure Info:**
- Name: {structure.name}
- Target version: {mc_version}
{stats_summary(block_map)}
{warning_text}
📐 {style_report}

🎮 **Import to Minecraft:**
{_import_instructions(written, stem)}
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
    except StructureTooLargeError as e:
        # Refused before expansion allocated anything, so this is recoverable:
        # the model can fix the coordinates and call again.
        return [
            TextContent(
                type="text",
                text=f"❌ Error: structure too large - {str(e)}"
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
    import asyncio

    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        # Let the viewer push browser prompts into this session. The bridge needs
        # the write stream and the loop it belongs to, because it is called from
        # the HTTP server's thread. Declaring "claude/channel" is what makes
        # Claude Code listen for them; without the channel enabled at startup the
        # capability is simply ignored and the MCP tools behave as before.
        channel_bridge.attach(asyncio.get_running_loop(), write_stream)
        try:
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(
                    experimental_capabilities={"claude/channel": {}}
                ),
            )
        finally:
            channel_bridge.detach()
