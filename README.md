# Minecraft Builder MCP Server

[![CI](https://github.com/JesperMorais/minecraft-builder-claude-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/JesperMorais/minecraft-builder-claude-mcp-server/actions/workflows/ci.yml)

An MCP (Model Context Protocol) server that enables Claude to generate Minecraft structures from natural language descriptions. Describe what you want to build, and Claude will create a `.schem` file that you can import into Minecraft.

## Features

- Natural language to Minecraft structure conversion
- **Shape primitives** (cuboid, hollow box, sphere, cylinder, cone, dome,
  ellipsoid, torus, line, pyramid) so large builds are a handful of operations
  instead of thousands of blocks
- **Build style guide** served to Claude as a tool, so structures come out
  looking designed rather than merely valid — palettes, depth, proportion,
  roof pitch, lighting (see [Build quality](#build-quality))
- MCP integration for Claude Desktop and Claude Code
- **3D viewer in your browser** — see the build as it is generated, and watch it
  change as you ask for revisions (see [3D viewer](#3d-viewer))
- **Chat from the viewer** — type a build request in the browser and it reaches
  your Claude Code session, with replies coming back in the same window. Works
  via plain polling (no flags, no org permission) or via channels (see
  [Chatting from the viewer](#chatting-from-the-viewer))
- **Point at what's wrong** — click a block or box a region in the viewer, attach
  a note, and Claude edits the *operation* that built it rather than regenerating
  the whole structure (see [Marking up a build](#marking-up-a-build))
- **Claude can see its own builds** — `render_structure` screenshots the viewer
  headlessly and hands the images back to the model, so it can review its work
  and fix what looks wrong before you have to say so (see
  [Seeing the build](#seeing-the-build))
- WorldEdit-compatible `.schem` and Litematica-native `.litematic` output, so a
  build can be pasted instantly *or* built by hand in survival against a
  hologram (see [Importing into Minecraft](#importing-into-minecraft))
- Support for block states (e.g. `oak_log[axis=y]`) and negative coordinates
- Automatic folder opening in the OS file manager (Windows/macOS/Linux)
- Support for structures from simple platforms to complex buildings
- No API costs - works with your Claude subscription

## Installation

### Prerequisites

- Python 3.10 or higher
- Claude Desktop or Claude Code

### Setup

1. Clone or download this repository

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install the package:
   ```bash
   pip install -e .
   ```

4. Register the server with your client.

   **Claude Code** reads `.mcp.json` from the project root. That file is *not*
   checked in — its `command` is an absolute path to an interpreter on one
   specific machine, so a committed copy breaks everyone else. Copy the example
   and edit it:

   ```bash
   cp .mcp.json.example .mcp.json      # Windows: copy .mcp.json.example .mcp.json
   ```

   ```json
   {
     "mcpServers": {
       "minecraft-builder": {
         "command": "/path/to/minecraft-builder-claude-mcp-server/.venv/bin/python",
         "args": ["-m", "minecraft_builder"],
         "timeout": 600000
       }
     }
   }
   ```

   **`command` must be a Python that can import this package.** On Windows that
   is `...\.venv\Scripts\python.exe`. A bare `python` commonly cannot — the
   system `python3` often has no access to the project virtualenv — and this is
   the most frequent setup failure. Check before you go further:

   ```bash
   /path/to/.venv/bin/python -c "import minecraft_builder"
   ```

   The first session in the project asks for consent — *"New MCP server found in
   this project: minecraft-builder"*. Choose **Use this MCP server**. Verify with
   `claude mcp list`; the server must appear as **Connected** before anything
   below will work, and it is required for
   [chat from the viewer](#chatting-from-the-viewer).

   **Claude Desktop** uses its own config file instead:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

   Use the same `mcpServers` block as above.

5. Restart Claude Desktop/Code completely

## Usage

Once installed, chat with Claude and describe structures. Claude will ask where to save the files.

### Simple Examples

```
Create a 5x5 stone platform
```

```
Build a wooden door frame using oak planks
```

```
Make a campfire area with logs arranged in a circle
```

### Complex Examples

```
Build a medieval cottage: 8x6 blocks, oak planks walls, stone foundation, glass windows, 6 blocks tall
```

```
Create a lighthouse tower with a circular stone base (7 blocks diameter), 25 blocks tall, stone for bottom 20 blocks, glass for top 5 blocks
```

```
Design a garden with a cobblestone path down the middle (10 blocks long), dirt blocks on sides for planting
```

See `examples/PROMPTS.md` for more detailed examples and tips.

### How It Works

1. You describe a structure to Claude
2. Claude generates a JSON definition with block coordinates
3. Claude asks where to save the .schem file
4. The tool converts JSON to Sponge Schematic v2 format
5. Claude can open the folder in your OS file manager

### Tools Available

**create_minecraft_structure** - Converts structure definitions to schematic files
- Accepts shape `operations` (cuboid, sphere, cylinder, ...) and/or explicit `blocks`
- Supports direct JSON input for small/medium structures
- Supports file-based input for large structures (see LARGE_STRUCTURE_GUIDE.md)
- `output_formats` selects which files to write: `schem` (WorldEdit),
  `litematic` (Litematica), or both. Defaults to `["schem"]`
- `mc_version` selects the target version — any release from `1.13` to `26.2`
  (default `1.19.4`); see [Version support](#version-support)
- Block IDs are validated against that version; unknown blocks are diagnosed as
  a typo, too-new, or renamed (set `strict: true` to fail instead of warn)

**show_structure** - Renders a structure in a 3D viewer in your browser
- Opens a local viewer at `http://127.0.0.1:8791/` (loopback only) and draws the
  build there; saves nothing to disk
- The page picks up new versions by itself, so leave the tab open and watch a
  build change as you ask for revisions
- Orbit/pan/zoom, a block legend, and a **colour by operation** toggle that
  shows which shape operation placed each block
- Blocks are flat colours, not Minecraft textures (see [3D viewer](#3d-viewer))

**render_structure** - Screenshots the build and hands the pictures to Claude
- The only tool whose output is *for the model*: `show_structure` shows the user,
  this one lets Claude see what it made and fix what is wrong
- Five 800x600 PNGs by default — four isometric corners and one level elevation
- Angles are compass bearings for where the camera stands (0 north, 90 east),
  matching Minecraft's own compass; pass `count` or explicit `angles`
- Drives the real viewer headlessly, so the pictures are what you would see; it
  never changes the version on your screen
- Needs the optional render extra (see [Seeing the build](#seeing-the-build))

**reply** - Sends a message back to the viewer's chat
- Used when a prompt arrived from the browser rather than the terminal
- Pairs with either chat mode (see
  [Chatting from the viewer](#chatting-from-the-viewer))

**await_prompt** - Waits for the next prompt typed in the viewer's chat
- Long-polls the prompt queue (default 240 s per call) and returns the oldest
  pending prompt; Claude calls it in a loop to keep listening
- This is the chat path that needs **no flag and no org permission** — see
  [Chatting from the viewer](#chatting-from-the-viewer)

**get_annotations** - Reads the notes you marked on the build in the viewer
- Each note names the **operation index** that placed what you clicked, resolved
  against the version you were looking at — so Claude edits the roof, not a guess
- See [Marking up a build](#marking-up-a-build)

**patch_operations** - Edits individual operations of the build on screen
- `replace` / `insert` / `delete` by index; every index in one call refers to the
  structure *before* any of them apply, so a batch cannot shift its own targets
- Re-shows the build itself, so no follow-up `show_structure` is needed
- "Make the roof steeper" costs one edit instead of a 200-operation rewrite

**resolve_annotations** - Marks notes as dealt with, clearing the viewer's tray
- Omit `ids` to close everything open, or pass ids to close only what was handled

**open_output_folder** - Opens the output location in the OS file manager
- Works on Windows (Explorer), macOS (Finder), and Linux (xdg-open)
- Highlights the created file on Windows/macOS
- (`open_folder_in_explorer` still works as a backwards-compatible alias)

**get_build_style_guide** - Returns the build style guide (no arguments)
- Claude should call this before designing anything larger than a few dozen blocks

**preview_structure** - Renders an ASCII preview of a structure without saving
- Top-down layer slices + block legend + stats (size, solid/air, fill ratio)
- Lets Claude sanity-check geometry (doorways, roundness, hollowness) first
- Takes the same input as `create_minecraft_structure`

## Build quality

A structure can be perfectly valid and still look like a beginner threw it
together. Because Claude never sees the generated build — there is no render and
no feedback loop — quality has to come from rules applied *before* the JSON is
emitted.

Two mechanisms handle that:

- A **compact checklist** is embedded in the `create_minecraft_structure`
  description, so the non-negotiables (3–5 block palette, no flat walls, real
  roof pitch, lighting) always apply.
- The **full guide** lives in
  [`src/minecraft_builder/data/style_guide.md`](src/minecraft_builder/data/style_guide.md)
  and is served on demand by `get_build_style_guide`. It covers themed block
  palettes, depth techniques, proportion and roof-pitch numbers, silhouette,
  lighting, ground transitions, a cookbook of shape-operation recipes, common
  anti-patterns, and a pre-flight checklist.

The guide is **tested, not just written**: `tests/test_style.py` validates every
block ID it mentions against each version registry in the guide's target range,
builds every cookbook recipe through the real conversion pipeline, and checks the
guide's version tables against the block index. A palette that goes stale, a
recipe that stops working, or a wrong version claim fails CI.

## Version support

Any release from **1.13** (the flattening) to **26.2** can be targeted via
`mc_version`; the default is `1.19.4`. Newer versions unlock newer blocks —
copper and tuff in 1.20.3, pale oak in 1.21.3, resin in 1.21.4, copper lighting
and shelves in 1.21.9, sulfur and cinnabar in 26.2.

Blocks are tracked as **version spans** (added-in, removed-after) in
[`data/block_versions.tsv`](src/minecraft_builder/data/block_versions.tsv) —
1200 blocks across 46 releases in one file. Spans matter because five blocks were
*renamed*, not merely added, so a first-seen version alone would mark them valid
forever:

| Old ID | New ID | Renamed in |
|---|---|---|
| `chain` | `iron_chain` | 1.21.9 |
| `grass` | `short_grass` | 1.20.3 |
| `grass_path` | `dirt_path` | 1.17 |
| `sign` | `oak_sign` | 1.14 |
| `wall_sign` | `oak_wall_sign` | 1.14 |

Validation uses this to diagnose rather than just reject:

```
- `copper_lantern` — added in 1.21.9 — target that version or newer to use it
- `chain` — renamed to `iron_chain` after 1.21.8
- `oak_plank` — did you mean: oak_planks, pale_oak_planks, dark_oak_planks?
```

Two caveats:

- **`mcschematic`'s version enum stops at 1.21.5.** Its `save()` only reads
  `version.value`, so newer releases are targeted by supplying the `DataVersion`
  directly. The schematic is written correctly; whether your WorldEdit build
  accepts it is a separate question.
- **`26.x` block lists are provisional.** Minecraft moved to a year-based scheme
  and the upstream registry (PrismarineJS) stops at 1.21.11, so 26.1/26.2 blocks
  come from the wiki and may be incomplete.

Regenerate the index with `python scripts/regen_block_data.py` (idempotent).

### Importing into Minecraft

Two formats are available, chosen with `output_formats` (defaults to `["schem"]`).
Which one you want depends on how you intend to build:

| You want to… | Format | Mod |
|---|---|---|
| Drop the finished build into the world instantly | `schem` | WorldEdit |
| Build it yourself in survival, following a hologram | `litematic` | Litematica |

**WorldEdit (`.schem`)** — needs creative mode or operator rights:

1. Copy the `.schem` file to your WorldEdit schematics folder:
   - Server: `[world]/plugins/WorldEdit/schematics/`
   - Client (Forge/Fabric): `.minecraft/config/worldedit/schematics/`

2. In-game commands:
   ```
   //schem load <filename>
   //paste
   ```

**Litematica (`.litematic`)** — works in survival:

1. Copy the `.litematic` file to `.minecraft/schematics/`
2. Open the Litematica menu (`M` by default), load the schematic and create a
   **placement**. The build appears as a translucent hologram you construct
   block by block.
3. `Material List` lists every block you need to gather.

Litematica can also load `.schem` on 1.17+, but that path is a stopgap in the
mod and is absent on 1.13–1.16, so prefer `litematic` when you want a blueprint.

Alternatively, use **MCEdit**, **Amulet Editor**, or other schematic tools.

### 3D viewer

Ask Claude to *show* you a build and it calls `show_structure`, which starts a
local viewer and prints a link:

```
Build a small stone cottage and show it to me
```

Open `http://127.0.0.1:8791/` once and leave the tab open. Each time Claude
revises the build, the page picks up the new version on its own — no reload.

- **Orbit** drag · **Zoom** scroll · **Pan** right-drag or two-finger drag
- **Colour by operation** recolours every block by which shape operation placed
  it, which makes "the roof is too steep" easy to point at
- The legend lists visible blocks with counts

Two things to know about what you are looking at:

- **Colours are flat, not Minecraft textures.** Minecraft's textures are Mojang's
  and cannot be redistributed, so each block is drawn as a representative colour.
  Shape, proportion and material choice read clearly; surface detail does not.
- **Enclosed blocks are not drawn.** A block with all six neighbours filled can
  never be seen, so it is skipped. The header shows the split, e.g.
  `528 blocks (409 visible, 119 enclosed)`.

The viewer binds `127.0.0.1` only, so nothing outside your machine can reach it.
It needs an internet connection on first load, because three.js is fetched from a
CDN; to run fully offline, vendor `three.module.js` and `OrbitControls.js` next to
`web/static/index.html` and point its import map at them.

### Seeing the build

The 3D viewer shows *you* the build. `render_structure` shows **Claude** the
build: it drives that same viewer in a headless Chromium, screenshots it from
several angles and returns the PNGs as images, so the model can look at its own
work and revise it.

```
Build a windmill, then render it and tell me what you got wrong
```

Five 800x600 views by default — four isometric corners and one level elevation —
written to a temp folder and handed back inline. Ask for `count` if you want
fewer, or specific `angles` (`azimuth` is a compass bearing for where the camera
stands, `elevation` is degrees above the horizon). Rendering is read-only: it
serves the structure straight to the headless page, so the version you have on
screen and any notes you have not applied are left alone.

It is an optional extra, because it brings a browser with it:

```bash
pip install -e ".[render]"
playwright install chromium
```

Without it every other tool works as before and `render_structure` returns those
two commands instead of a picture. Rendering needs network access on first load
for the same reason the viewer does — three.js comes from a CDN.

### Chatting from the viewer

The viewer has a chat box. Anything you type there is delivered to the Claude Code
session the MCP server is attached to, and Claude's answers come back in the same
box — so you can drive a build entirely from the browser while watching it change.

Two delivery mechanisms exist, and the browser needs no configuration for either:

| Mode | How prompts reach Claude | Needs |
|---|---|---|
| **Polling** | Claude calls the `await_prompt` tool in a loop | Nothing — works everywhere |
| **Channels** | The server pushes events into the session | Research-preview flag + org permission |

**Polling (recommended):** just tell Claude, in the terminal, something like
*"listen to the viewer"* or *"wait for prompts from the browser"*. Claude calls
`await_prompt`, which blocks until you type in the browser, handles the prompt,
replies, and calls it again. No startup flag, no admin approval, and it works on
Bedrock/Vertex/Foundry too. The trade-off: the terminal session is occupied by
the listening loop while it runs, and each wait round is a tool call.

**Channels** push prompts into the session instead, so Claude stays free between
messages. They are a research preview, so they need two
things: the server registered under that exact name, and a session started with
the channel enabled.

**First check the server is registered.** `server:minecraft-builder` names an entry
in your MCP config — with no such entry the flag has nothing to attach to, and
Claude Code starts normally with no error and no channel:

```bash
claude mcp list        # minecraft-builder must be listed and Connected
```

If it is missing, go back to [Setup step 4](#setup). Then:

```bash
claude --dangerously-load-development-channels server:minecraft-builder
```

Confirm the warning dialog, and look for a line under the startup banner saying
messages from `server:minecraft-builder` inject directly into the session. Then
run any build request to start the viewer, and the chat box goes live.

Requirements and limits, all imposed by the preview:

- Channels need Anthropic authentication (a claude.ai account or a Console API
  key). They are not available on Bedrock, Google Cloud or Microsoft Foundry.
- A channel cannot be enabled mid-session — it has to be there at startup.
- Custom channels are not on Anthropic's approved list, so the
  `--dangerously-load-development-channels` flag is required rather than
  `--channels`. Neither flag appears in `claude --help`.
- On a Team or Enterprise plan, channels are **blocked by default** and the flag
  reports `blocked by org policy` at startup. An org Owner can enable them at
  claude.ai → Admin settings → Claude Code by setting `channelsEnabled: true`
  in managed settings. A local `managed-settings.json` cannot override this —
  server-delivered policy wins. If you can't (or don't want to) change org
  policy, use polling instead; that is exactly what it is for.

**Everything else keeps working without the flag.** Start Claude Code normally and
all the tools behave as documented — including polling-mode chat. The dot in the
chat header shows which state you are in:

| Dot | Meaning |
|---|---|
| green — "Claude is listening" | An `await_prompt` call is waiting right now; delivery is certain |
| green — "Claude is busy, still listening" | Between `await_prompt` rounds — building or replying. It will be back |
| green — "connected to Claude" | A channel event has come back answered, so the channel demonstrably works |
| **amber** — "attached, but delivery unproven" | An MCP session exists, and that is all anyone knows. See below |
| red | Nothing is listening — no session, or the loop has stopped |

**Green means proven, amber means unknown.** That distinction is the whole point,
because channel events are **not acknowledged**: a session with channels blocked
by org policy or simply not enabled accepts the event and discards it in silence,
which from the server looks exactly like success. So an attached session on its
own earns amber, never green — hover the dot for what to do about it.

Amber is not a failure state and does not cost you anything. Prompts are queued
as well as pushed until the channel proves itself, so an amber prompt is still
waiting to be collected: tell Claude in the terminal to *"listen to the viewer"*
and it arrives. Once a reply has come back over the channel the dot goes green
and stays green for the session. Queued prompts hold up to 64, oldest dropped
first.

### Marking up a build

Describing what's wrong with a build in words is the slow way. Tick **Mark up the
build** in the panel and point at it instead:

- **Click a block** to mark that block.
- **Shift-click two blocks** to mark the box between them.
- Type what's wrong, press **Add note**. Repeat as many times as you like.
- Press **Apply notes**, and Claude reads them and revises the build.
- <kbd>Esc</kbd> cancels a half-made selection. **×** deletes a note.

Marking mode shares the left mouse button with orbiting: dragging still rotates
the view, and only a click that barely moves counts as a mark.

**Why this beats typing "the roof is too steep":** a note records which
*operation* built what you clicked, not just a coordinate. Claude receives
*"operation #4 (pyramid centre=[8,5,8] base=6): too steep"* and edits that one
operation. Ask in prose and it usually regenerates the whole structure, quietly
changing the parts you were happy with.

A region resolves to the operation that owns most of it — a box drawn round a
roof always clips a wall — and Claude is told the coverage share and what else the
box touched, so it can tell "mostly the roof" from a genuine 50/50.

Notes are resolved **when you make them**, against the version on screen. If the
build is revised before Claude reads them, they still point at what you marked,
and Claude is warned that the index may have moved. Notes live in memory for the
session; they are not saved to disk.

## JSON Structure Format

A structure is defined by a `name` plus any mix of **`operations`** (declarative
shapes) and **`blocks`** (explicit per-voxel placements). Prefer operations —
they are far more compact and never truncate on large builds.

### Operations (recommended)

Operations apply **in order**, and a later placement overwrites an earlier one
at the same coordinate. This lets you fill a solid wall and then carve a window
out of it with `air`:

```json
{
  "name": "stone_hut",
  "description": "Hollow stone hut with a doorway",
  "operations": [
    {"op": "hollow_box", "start": [0, 0, 0], "end": [6, 4, 6], "block": "stone", "ceiling": false},
    {"op": "cuboid", "start": [3, 1, 0], "end": [3, 3, 0], "block": "air"}
  ]
}
```

Available operations (every op takes a `block`, except `replace`):

| op | Shape | Key fields |
|----|-------|-----------|
| `cuboid` | Solid box | `start`, `end` |
| `hollow_box` | Box shell | `start`, `end`, `walls`, `floor`, `ceiling` |
| `sphere` | Sphere / shell | `center`, `radius`, `hollow` |
| `cylinder` | Cylinder / tube | `center`, `radius`, `height`, `axis`, `hollow` |
| `line` | 3D line | `start`, `end` |
| `pyramid` | Step pyramid | `center`, `base`, `axis`, `hollow` |
| `dome` | Hemisphere (open-based when hollow) | `center`, `radius`, `axis`, `hollow` |
| `cone` | Base→apex taper (spires, roofs) | `center`, `radius`, `height`, `axis`, `hollow` |
| `ellipsoid` | Sphere with independent radii | `center`, `rx`, `ry`, `rz`, `hollow` |
| `torus` | Ring | `center`, `major_radius`, `minor_radius`, `axis`, `hollow` |
| `block` | Single block | `pos` |
| `replace` | Swap blocks in a region | `start`, `end`, `from_block`, `to_block` |

Coordinates are `[x, y, z]` integer lists and may be negative — the structure is
re-centred automatically on export.

### Explicit blocks

Still supported for scattered detail a shape can't express:

```json
{
  "name": "my_structure",
  "blocks": [
    {"x": 0, "y": 0, "z": 0, "block_type": "minecraft:stone"},
    {"x": 1, "y": 0, "z": 0, "block_type": "oak_planks"}
  ]
}
```

**Block IDs:**
- Full format: `minecraft:stone`, `minecraft:oak_planks`
- Short format: `stone`, `oak_planks` (auto-prefixed with `minecraft:`)
- With block state: `oak_log[axis=y]`, `oak_stairs[facing=north]`

**Coordinates:**
- X: Width, Y: Height, Z: Length

## Compatibility

- Schematic formats: Sponge Schematic v2 (`.schem`), Litematica (`.litematic`)
- Selectable target versions: any release from 1.13 to 26.2 (default 1.19.4) via
  `mc_version` — see [Version support](#version-support)
- WorldEdit 7.x required to import `.schem`; Litematica to import `.litematic`

## Project Structure

```
minecraft-builder-claude-mcp-server/
├── src/minecraft_builder/
│   ├── __main__.py          # MCP server entry point
│   ├── server.py            # MCP server and tool definitions
│   ├── schema.py            # Pydantic models + shape operations
│   ├── shapes.py            # Pure geometry generators
│   ├── converter.py         # JSON to .schem / .litematic converters
│   ├── versions.py          # Version support + block-ID validation
│   ├── colors.py            # Flat display colours for the 3D viewer
│   ├── style.py             # Style guide loader + compact checklist
│   ├── lint.py              # Style guide as programmatic checks
│   ├── patches.py           # Targeted edits to a structure's operations
│   ├── preview.py           # ASCII preview + structure stats
│   ├── paths.py             # Path resolution and file-manager opening
│   ├── web/                 # Local 3D viewer + chat
│   │   ├── app.py           # localhost HTTP server (stdlib only)
│   │   ├── state.py         # Current structure + version history
│   │   ├── payload.py       # Compact JSON for the browser
│   │   ├── channel.py       # Pushes browser prompts into the session
│   │   ├── prompts.py       # Prompt queue for polling mode (await_prompt)
│   │   ├── annotations.py   # Build markup, resolved to operations
│   │   ├── chat.py          # Transcript + SSE event bus
│   │   ├── render.py        # Headless screenshots of the viewer

│   │   ├── __main__.py      # Run the viewer standalone
│   │   └── static/          # index.html, viewer.js, style.css
│   └── data/
│       ├── style_guide.md   # The build style guide
│       ├── block_versions.tsv  # Block -> version span index (1200 blocks)
│       └── mc_versions.json    # Releases + their NBT DataVersion
├── scripts/
│   └── regen_block_data.py  # Rebuilds the block/version index
├── tests/
├── examples/
│   ├── example_structures.json
│   ├── japanese_pagoda.json
│   └── PROMPTS.md
├── requirements.txt
├── pyproject.toml
├── README.md
└── LARGE_STRUCTURE_GUIDE.md
```

## Troubleshooting

**MCP server not appearing:**
- Does `.mcp.json` exist? It is gitignored, so a fresh clone has only
  `.mcp.json.example` — copy it (see [Setup step 4](#setup)).
- Completely restart Claude Desktop
- Verify config file location and syntax
- Run `claude mcp list` (Claude Code) — the server must show as **Connected**
- Check the `command` in your config is a Python that can import the package:
  `<that python> -c "import minecraft_builder"`. A bare `python` often is not.
- Ensure package is installed: `pip list | grep minecraft-builder`

**Dot is amber — "attached, but delivery unproven":**

Expected, not broken. It means an MCP session exists but nothing has confirmed it
receives channel events, which is undetectable until one comes back answered. Your
prompt is queued regardless, so the fix is to give it a collector: tell Claude in
the terminal to *"listen to the viewer"*. The dot goes green and the queued prompt
is picked up. If you want channel delivery instead, work through the list below —
and note that on a Team/Enterprise plan amber is the normal steady state until an
admin enables channels.

**Chat box says "no Claude session listening":**

The quickest fix is to skip channels entirely: tell Claude in the terminal to
*"listen to the viewer"* — it calls `await_prompt` and the dot flips to
"Claude is listening". If you specifically want channel delivery instead,
channel events are unacknowledged, so every cause looks identical from the
browser. Work through it in this order:

1. **Is the server registered?** `claude mcp list` must show `minecraft-builder`
   as Connected. `--dangerously-load-development-channels server:minecraft-builder`
   refers to that entry by name; with no entry, Claude Code starts with no error
   and no channel. This is the most common cause.
2. **Was the flag passed?** It cannot be enabled mid-session. On startup, a dim
   line under the banner should say messages from `server:minecraft-builder`
   inject directly into this session. No line means no channel.
3. **Did you accept the consent prompt?** The first session in a new project asks
   before using a server from `.mcp.json`.
4. **Check the name matches.** The part after `server:` is the key in
   `mcpServers`, not the package or directory name.
5. **Org policy**, on Team/Enterprise plans — an admin must enable channels. A
   startup warning names this if it applies.
6. **Check the debug log** at `~/.claude/debug/<session-id>.txt` for the server's
   stderr if it failed to start.

**Installation errors:**
- Use Python 3.10 or higher
- Install all dependencies: `pip install -r requirements.txt`
- Try: `pip install -e . --force-reinstall`

**Structure won't import in Minecraft:**
- Verify .schem file was created
- Check WorldEdit is installed (version 7.x+)
- Confirm Minecraft version is 1.13 or newer
- Use `//schem list` in-game to verify file is detected

**Large structures truncated:**
- See `LARGE_STRUCTURE_GUIDE.md` for handling complex structures
- For 300+ blocks, ask Claude to write JSON to file first

**Path issues:**
- Use paths native to wherever the server runs: `C:\Users\name\Desktop` on
  Windows, `/home/name/Desktop` on Linux/macOS.
- The shortcuts `desktop`, `documents`, and `downloads` work on every OS.
- Running under WSL, `/mnt/c/Users/...` paths work as-is (the server only
  rewrites them to `C:\...` when it is running on native Windows).

## Development

### Running locally

```bash
cd src
python -m minecraft_builder
```

The server runs in stdio mode for MCP communication.

### Testing and linting

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src/minecraft_builder
```

## Dependencies

- **mcp** (>=0.9.0) - MCP Python SDK
- **mcschematic** (>=11.0.0) - `.schem` (Sponge Schematic v2) writing
- **litemapy** (>=0.11.0b0,<0.12) - `.litematic` (Litematica) writing
- **pydantic** (>=2.0.0) - Data validation

Optional, in the `render` extra:

- **playwright** (>=1.40) - Headless Chromium for `render_structure`. Also needs
  `playwright install chromium`; nothing else depends on it

## Contributing

Contributions welcome:
- Additional output formats (`.nbt` vanilla structure blocks; `.schem` and
  `.litematic` are supported)
- NBT data / block-entity support (chests, signs)
- More shape primitives — an `arch`, a `roof` op, and a `stairs` helper
  (these need block-state `[facing=]`/`[half=]` handling to look right)
- Transform wrappers (`repeat` / `mirror` / `rotate`)
- More example structures

## License

MIT License

## Credits

Built using:
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) by Anthropic
- [mcschematic](https://github.com/Sloimayyy/mcschematic) for schematic file handling
- [Pydantic](https://docs.pydantic.dev/) for data validation
