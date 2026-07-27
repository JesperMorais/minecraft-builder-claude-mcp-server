# Minecraft Builder MCP Server

[![CI](https://github.com/JesperMorais/minecraft-builder-claude-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/JesperMorais/minecraft-builder-claude-mcp-server/actions/workflows/ci.yml)

An MCP (Model Context Protocol) server that enables Claude to generate Minecraft structures from natural language descriptions. Describe what you want to build, and Claude will create a `.schem` file that you can import into Minecraft.

## Features

- Natural language to Minecraft structure conversion
- **Shape primitives** (cuboid, hollow box, sphere, cylinder, line, pyramid) so
  large builds are a handful of operations instead of thousands of blocks
- MCP integration for Claude Desktop and Claude Code
- WorldEdit-compatible `.schem` file generation
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

4. Configure Claude Desktop or Claude Code:

   Edit your config file:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

   Add this configuration:
   ```json
   {
     "mcpServers": {
       "minecraft-builder": {
         "command": "python",
         "args": ["-m", "minecraft_builder"]
       }
     }
   }
   ```

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

**create_minecraft_structure** - Converts structure definitions to .schem files
- Accepts shape `operations` (cuboid, sphere, cylinder, ...) and/or explicit `blocks`
- Supports direct JSON input for small/medium structures
- Supports file-based input for large structures (see LARGE_STRUCTURE_GUIDE.md)
- `mc_version` selects the target version (`1.19.4`, `1.20.4`, `1.21.4`; default `1.19.4`)
- Block IDs are validated against that version; unknown vanilla blocks are
  reported with "did you mean" suggestions (set `strict: true` to fail instead)

**open_output_folder** - Opens the output location in the OS file manager
- Works on Windows (Explorer), macOS (Finder), and Linux (xdg-open)
- Highlights the created file on Windows/macOS
- (`open_folder_in_explorer` still works as a backwards-compatible alias)

### Importing into Minecraft

The generated `.schem` files work with **WorldEdit**:

1. Copy the `.schem` file to your WorldEdit schematics folder:
   - Server: `[world]/plugins/WorldEdit/schematics/`
   - Client (Forge/Fabric): `.minecraft/config/worldedit/schematics/`

2. In-game commands:
   ```
   //schem load <filename>
   //paste
   ```

Alternatively, use **MCEdit**, **Amulet Editor**, or other schematic tools.

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

- Schematic format: Sponge Schematic v2
- Selectable target versions: 1.19.4 (default), 1.20.4, 1.21.4 (via `mc_version`)
- WorldEdit 7.x required for import

## Project Structure

```
llm-minecraft-builds/
├── src/minecraft_builder/
│   ├── __init__.py
│   ├── __main__.py       # MCP server entry point
│   ├── server.py          # MCP server and tool definitions
│   ├── schema.py          # Pydantic data models
│   └── converter.py       # JSON to .schem converter
├── examples/
│   ├── example_structures.json
│   └── PROMPTS.md
├── requirements.txt
├── pyproject.toml
├── README.md
├── CLAUDE.md              # Instructions for Claude Code
└── LARGE_STRUCTURE_GUIDE.md
```

## Troubleshooting

**MCP server not appearing:**
- Completely restart Claude Desktop
- Verify config file location and syntax
- Check Python is accessible: `python --version`
- Ensure package is installed: `pip list | grep minecraft-builder`

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

### Testing

```bash
pip install -e ".[dev]"
pytest
```

## Dependencies

- **mcp** (>=0.9.0) - MCP Python SDK
- **mcschematic** (>=11.0.0) - Minecraft schematic file handling
- **pydantic** (>=2.0.0) - Data validation

## Contributing

Contributions welcome:
- Additional output formats (.nbt, .litematic)
- NBT data / block-entity support (chests, signs)
- More shape primitives (torus, ellipsoid, arch, stairs)
- Cross-platform folder opening (macOS/Linux)
- More example structures

## License

MIT License

## Credits

Built using:
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) by Anthropic
- [mcschematic](https://github.com/Sloimayyy/mcschematic) for schematic file handling
- [Pydantic](https://docs.pydantic.dev/) for data validation
