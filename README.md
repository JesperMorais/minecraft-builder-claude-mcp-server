# Minecraft Builder MCP Server

An MCP (Model Context Protocol) server that enables Claude to generate Minecraft structures from natural language descriptions. Simply describe what you want to build, and Claude will create a `.schem` file that you can import into Minecraft!

## Features

- 🏗️ **Natural Language to Minecraft**: Describe structures in plain English
- 🔧 **MCP Integration**: Works with Claude Desktop, Claude Code, and other MCP clients
- 📦 **WorldEdit Compatible**: Generates `.schem` files for easy import
- 🎨 **Flexible JSON Format**: Claude works with simple JSON, converted automatically to schematic format
- 💰 **No API Costs**: Use your existing Claude subscription

## Installation

### Prerequisites

- Python 3.10 or higher
- Claude Desktop App or Claude Code

### Setup

1. **Clone or download this repository**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Claude Desktop** (or Claude Code):

   **For Claude Desktop:**

   Edit your Claude Desktop config file:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

   Add this MCP server configuration:
   ```json
   {
     "mcpServers": {
       "minecraft-builder": {
         "command": "python",
         "args": [
           "-m",
           "minecraft_builder",
           "-u"
         ],
         "cwd": "F:\\Projects\\Other\\llm-minecraft-builds\\src"
       }
     }
   }
   ```

   **For Claude Code:**

   Edit `~/.claude/claude_code_config.json` and add the same configuration under `mcpServers`.

4. **Restart Claude Desktop/Code** to load the MCP server

## Usage

Once installed, simply chat with Claude and describe what you want to build!

### Example Prompts

**Simple structures:**
```
"Create a small 3x3 stone platform"
"Build me a wooden door frame"
"Make a simple campfire area with logs arranged in a circle"
```

**Complex structures:**
```
"Build a small medieval cottage with oak planks walls, a stone foundation,
and glass windows. Make it 8 blocks wide and 6 blocks tall."

"Create a lighthouse tower: circular stone base (5 blocks diameter),
20 blocks tall, with a glass top section for the light"

"Design a simple garden with a cobblestone path, flower beds on each side,
and a small fountain in the center"
```

### How It Works

1. You describe a structure to Claude
2. Claude generates a JSON definition with block coordinates
3. Claude calls the `create_minecraft_structure` tool
4. The tool converts JSON to `.schem` format
5. The file is saved to `minecraft_structures/` folder

### Importing into Minecraft

The generated `.schem` files can be imported using **WorldEdit**:

1. Copy the `.schem` file to your WorldEdit schematics folder:
   - `[server/world]/plugins/WorldEdit/schematics/` (Bukkit/Spigot)
   - `.minecraft/config/worldedit/schematics/` (Forge/Fabric)

2. In-game commands:
   ```
   //schem load <filename>
   //paste
   ```

3. Or use tools like **MCEdit**, **Amulet Editor**, or **WorldEdit CUI**

## JSON Structure Format

The MCP tool accepts structures in this format:

```json
{
  "name": "my_structure",
  "description": "Optional description",
  "blocks": [
    {
      "x": 0,
      "y": 0,
      "z": 0,
      "block_type": "minecraft:stone"
    },
    {
      "x": 1,
      "y": 0,
      "z": 0,
      "block_type": "oak_planks"
    }
  ]
}
```

**Block IDs** can be:
- Full: `minecraft:stone`, `minecraft:oak_planks`
- Short: `stone`, `oak_planks` (automatically prefixed with `minecraft:`)

**Coordinates**:
- Start from `(0, 0, 0)`
- X: Width, Y: Height, Z: Length
- All coordinates are relative to the structure origin

## Supported Minecraft Versions

- Schematic format: **Sponge Schematic v2**
- Compatible with: **Minecraft 1.13+**
- WorldEdit 7.x required for import

## Development

### Project Structure

```
llm-minecraft-builds/
├── src/
│   └── minecraft_builder/
│       ├── __init__.py
│       ├── __main__.py       # MCP server entry point
│       ├── server.py          # MCP server implementation
│       ├── schema.py          # JSON structure definitions
│       └── converter.py       # JSON to .schem converter
├── minecraft_structures/      # Output directory (created automatically)
├── requirements.txt
├── pyproject.toml
└── README.md
```

### Running Locally

Test the server:
```bash
cd src
python -m minecraft_builder
```

The server communicates via stdio (standard input/output) using the MCP protocol.

## Troubleshooting

**MCP server not showing up in Claude:**
- Restart Claude Desktop completely
- Check the config file path is correct
- Verify Python path in config matches your installation
- Check that `cwd` points to the `src` directory

**Import errors:**
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Use Python 3.10+ (`python --version`)

**Structure not appearing in Minecraft:**
- Verify the .schem file was created in `minecraft_structures/`
- Make sure WorldEdit is installed on your server/client
- Check WorldEdit schematics folder location
- Use `//schem list` to see available schematics

**Blocks are wrong:**
- Claude might use incorrect block IDs - provide specific IDs in your prompt
- Check Minecraft version compatibility (1.13+ required)

## Contributing

Contributions welcome! Feel free to:
- Add support for more output formats (.nbt, .litematic)
- Improve block palette handling
- Add block states and NBT data support
- Enhance structure validation

## License

MIT License - feel free to use and modify as needed!

## Credits

Built using:
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) by Anthropic
- [nbtlib](https://github.com/vberlier/nbtlib) for NBT file handling
- [Pydantic](https://docs.pydantic.dev/) for data validation
