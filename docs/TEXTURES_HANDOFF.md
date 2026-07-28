# Real-texture resolver — handoff to the viewer/renderer track

A self-contained resolver that turns a **bring-your-own** resource pack into a
block → face-textures atlas + the referenced PNGs. It does **not** touch
`viewer.js` / `payload.py` — wiring it into the renderer is the viewer track's
call. Built on the `.schem`/build side and handed over.

## Where it is
- `src/minecraft_builder/web/textures.py` — the resolver (stdlib only).

## What it does
`Pack(zip)` + `resolve(pack, block_id)` walks the pack's blockstate → model →
parent chain the way the game does and returns:

```python
{
  "archetype": "cube_column",
  "faces": {"down": "spruce_log", "up": "spruce_log",
            "north": "spruce_log_top", ...},   # convenience, orientation-baked
  "roles": {"side": "spruce_log", "end": "spruce_log_top"},  # orientation-free
}
```

CLI to generate the atlas + extract only the referenced PNGs:

```bash
python -m minecraft_builder.web.textures <pack.zip> --all --out texturepack_out
# -> texturepack_out/atlas.json  (block -> {archetype, faces, roles})
# -> texturepack_out/textures/*.png
```

Verified against the 26.2.x pack: **1195 blocks resolved, 960 textures**; only
`air`/`cave_air`/`void_air` are unresolved (correct — they're empty).

## Legal — important
The PNGs and atlas are **Mojang assets**. Ship only `textures.py` (code). The
output dir is gitignored (`texturepack_out/`); never commit textures. The user
points the resolver at their own pack and the output is generated locally.

## Wiring into viewer.js (your part)
Today `colors.py` gives a flat RGB and `viewer.js` builds a tinted luminance
CanvasTexture. To use real textures, per material / instanced mesh:
1. `atlas[base_block_id]` → load `faces[<face>].png` as a `THREE.Texture`
   (NearestFilter, no mipmaps — keep it pixelated).
2. Full cube → 6-material array; logs/pillars pick end vs side from `axis`;
   stairs/slabs use `roles` on the geometry you already draw.
3. Keep the flat colour as a fallback for anything not in the atlas.

## Gotchas that will bite if skipped
- **Biome tint**: `grass_block_top`, `grass_block_side` overlay, `*_leaves`,
  `vine`, `fern`, `*_grass`, `water`, `sugar_cane`, `lily_pad` textures are
  GRAYSCALE — multiply by the existing `colors.py` tint or they render white.
- **Animated** (a `.mcmeta` exists next to the PNG): `lantern`, `sea_lantern`,
  `campfire`, fire, water, portals are vertical frame strips — use the top
  16×16 (first frame) or animate.
- **Transparency**: glass, panes, leaves, `iron_bars`, `*_door` need an
  alpha-tested / transparent material (you already do glass translucency —
  extend the set).
- **Doors**: `faces` shows only the bottom; use `roles["bottom"]` + `roles["top"]`
  for the two halves. (Also: the viewer currently doesn't render the door block
  at all — surfaced while building; worth a look independent of textures.)
