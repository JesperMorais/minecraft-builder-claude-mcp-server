"""MCP Server for Minecraft structure generation."""

import json
import sys
import traceback
from typing import Any

from mcp.server import Server
from mcp.types import Icon, TextContent, Tool
from pydantic import ValidationError

from .converter import DEFAULT_FORMATS, OUTPUT_FORMATS, SchematicConverter
from .lint import format_report, lint_structure
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
from .web.channel import BRIDGE as channel_bridge
from .web.chat import CHAT as viewer_chat
from .web.prompts import PROMPTS as viewer_prompts

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
