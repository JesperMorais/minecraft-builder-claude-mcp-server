# Building Large/Complex Structures

## First: use shape operations

Most "large structure" pain disappears if you describe the build with **shape
operations** instead of listing every block. A solid 20×20×20 stone cube is one
`cuboid` operation (~60 characters) rather than 8,000 block entries. See the
"JSON Structure Format" section in the README for the full operation list.

Reach for the file-based workflow below only when even the *operation* JSON is
large — e.g. a build with thousands of individually-placed detail blocks that no
primitive can express.

## The Problem

When creating complex structures with many explicit blocks, the JSON can become too large to fit in a single response, causing it to be truncated mid-generation.

## The Solution ✅

The tool now supports **two methods** for providing structure data:

### Method 1: Direct JSON (Small/Medium Structures)
Use `structure_json` parameter for structures with ~100-200 blocks or fewer.

**Example:**
```
Create a simple 5x5 stone platform on Desktop
```

Claude will generate the JSON inline and call the tool directly.

---

### Method 2: File-Based (Large/Complex Structures)
For structures with hundreds or thousands of blocks, use this workflow:

1. **Claude writes JSON to a file** using the Write tool
2. **Claude calls the tool** with `json_file_path` parameter pointing to that file
3. **Tool reads and converts** the JSON file to `.schem`

**Example Prompt:**
```
Design a 3-tier Japanese pagoda with all the details I described.
Since this will be a large structure, please:
1. Write the complete JSON to a file on my Desktop called "pagoda_structure.json"
2. Then convert that JSON file to a .schem file
3. Save the .schem to Desktop
4. Open the folder when done
```

## Workflow for Large Structures

**Step-by-step:**

1. **You:** Request a complex structure
   ```
   Build a detailed medieval castle with towers, walls, and interior rooms.
   This will be large, so save the JSON to Desktop as castle.json first,
   then convert it to .schem. Save both to Desktop.
   ```

2. **Claude:** Uses Write tool to create `castle.json` on Desktop

3. **Claude:** Calls `create_minecraft_structure` with:
   ```json
   {
     "json_file_path": "C:\\Users\\josh\\Desktop\\castle.json",
     "output_directory": "C:\\Users\\josh\\Desktop"
   }
   ```

4. **Result:** Both files on your Desktop:
   - `castle.json` - The full structure definition (you can keep or delete)
   - `castle.schem` - The Minecraft schematic file

## Benefits of File-Based Method

✅ **No size limit** - JSON can be arbitrarily large
✅ **No truncation** - Complete structure always generated
✅ **Inspectable** - You can view/edit the JSON if needed
✅ **Reusable** - Keep the JSON to regenerate or modify later
✅ **Debuggable** - If conversion fails, you still have the JSON

## When to Use Each Method

| Structure Complexity | Blocks | Method | Example |
|---------------------|--------|---------|---------|
| Simple | <100 | Direct JSON | Platform, small house |
| Medium | 100-300 | Direct JSON | Tower, bridge |
| Complex | 300-1000 | **File-based** | Multi-story building |
| Very Complex | 1000+ | **File-based** | Castle, pagoda, village |

## Example: The Japanese Pagoda

**Your Prompt:**
```
Design a detailed 3-tier Japanese pagoda as I described earlier.
This is complex, so:
1. Write the complete JSON structure to Desktop/japanese_pagoda.json
2. Convert that JSON to japanese_pagoda.schem on Desktop
3. Open the folder when done
```

**What Claude Will Do:**
1. Generate the full structure with all tiers, roofs, decorative elements
2. Write complete JSON to `C:\Users\josh\Desktop\japanese_pagoda.json`
3. Read that JSON and convert to `japanese_pagoda.schem`
4. Open Windows Explorer showing both files

**Result:**
- ✅ Complete, untruncated structure
- ✅ Both JSON and .schem files available
- ✅ Folder automatically opened

## Tips

- Always mention "save JSON to file first" for complex structures
- Specify both the JSON filename and output filename if you want them named differently
- You can keep the JSON files to build a library of structures
- If conversion fails, you can manually edit the JSON and try again

## Troubleshooting

**Problem:** "Continue" creates a new structure instead of finishing the old one

**Solution:** Use the file-based method! Tell Claude explicitly:
```
This will be large - please write the JSON to a file first,
then convert that file to .schem
```

**Problem:** JSON file exists but tool can't find it

**Solution:** Make sure to provide the full absolute path:
- ✅ `C:\Users\josh\Desktop\structure.json`
- ❌ `Desktop\structure.json`
- ❌ `structure.json`
