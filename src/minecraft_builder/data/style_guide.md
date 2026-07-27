# Minecraft Build Style Guide

Rules for turning a correct structure into a **good-looking** one.

The `create_minecraft_structure` tool tells you what is *possible*. This guide
tells you what is *good*. Read it before designing any build larger than a few
dozen blocks.

You cannot see the result — there is no render, no screenshot, no feedback loop.
So the quality of a build is decided entirely by the rules you follow before
emitting JSON. Treat the [Pre-flight checklist](#pre-flight-checklist) as
mandatory.

---

## The one-paragraph version

Pick 3–5 blocks and stick to them. Never leave a wall face flat — break it with
pillars, insets, and a base/roof ledge every few blocks. Make the roof a
different material from the walls, pitch it properly, and overhang it 1–2 blocks.
Light it. Break the rectangle. Build the interior, not just the shell.

---

## 1. Palette: 3–5 blocks, in a 50/30/20 ratio

Using one block for a whole build is the single clearest marker of an amateur
build. Using twelve is the second clearest.

| Role | Share | Job |
|---|---|---|
| **Primary** | ~50% | Dominant wall / mass material |
| **Secondary** | ~30% | Different texture, *similar* tone — breaks up the primary |
| **Accent** | ~20% | Trim, corners, frames — the only high-contrast element |
| **Detail** | trace | Lights, plants, shutters, railings |

Two hard rules:

- **The roof is never the same material as the walls.** Contrast is what makes a
  roofline read as a roofline.
- **Secondary must be close in tone to primary, accent must be far.** Three
  equally-contrasting materials look like a patchwork, not a palette.

### Palette library

All IDs below are valid in **1.19.4** unless a version is noted. Percentages are
the primary/secondary/accent split.

**Medieval village** — `cobblestone` 50 · `oak_planks` 30 · `stone_bricks` 20
Trim: `stripped_oak_log[axis=y]` corner posts, `oak_stairs`, `cobblestone_wall`
Texture-mates for cobblestone: `mossy_cobblestone`, `andesite`, `gravel`
Roof: `dark_oak_stairs` or `deepslate_tile_stairs`

**Castle / fortress** — `stone_bricks` 50 · `cracked_stone_bricks` 30 · `polished_andesite` 20
Trim: `stone_brick_wall` battlements, `chiseled_stone_bricks` belt course, `dark_oak_trapdoor` arrow slits
Texture-mates: `mossy_stone_bricks`, `andesite`, `cobblestone`
Roof: `deepslate_tile_stairs`, `dark_oak_stairs`

**Cottage / storybook** — `oak_planks` 50 · `spruce_planks` 30 · `cobblestone` 20
Trim: `stripped_spruce_log`, `oak_fence`, `oak_trapdoor` shutters
Roof: `spruce_stairs` or `brick_stairs`; greenery `oak_leaves`, `flowering_azalea_leaves`

**Modern minimal** — `white_concrete` 50 · `light_gray_concrete` 30 · `glass` 20
Trim: `smooth_quartz`, `dark_oak_planks` warm panels, `iron_bars`
Roof: flat, `smooth_stone_slab[type=top]`; lights `sea_lantern`
Note: modern is the one style where a flat roof and hard symmetry are correct.

**Japanese / pagoda** — `dark_oak_planks` 40 · `smooth_stone` 30 · `white_terracotta` 20 · `stripped_dark_oak_log` 10
Trim: `dark_oak_fence` railings, `oak_trapdoor` shoji panels, `stone_brick_stairs` plinth
Roof: `deepslate_tile_stairs` with `dark_oak_slab` under-eaves, deep 2–3 block overhang
1.20.4+: swap accents to `cherry_planks`, `cherry_leaves`, `bamboo_planks`

**Desert / adobe** — `smooth_sandstone` 50 · `cut_sandstone` 30 · `terracotta` 20
Trim: `chiseled_sandstone`, `sandstone_stairs`, `orange_terracotta` bands
Roof: flat with `sandstone_slab`, or `brick_stairs` for Mediterranean

**Nordic / viking** — `spruce_planks` 50 · `stone_bricks` 30 · `stripped_spruce_log` 20
Trim: `spruce_stairs`, `spruce_fence`, `chain`
Roof: steep (63°) `dark_oak_stairs` with `moss_block` patches

**Industrial / brick** — `bricks` 50 · `deepslate_bricks` 30 · `dark_oak_planks` 20
Trim: `iron_bars`, `chain`, `polished_basalt` columns, `cut_copper` (1.17+)
Roof: `deepslate_tile_stairs`; lights `redstone_lamp`, `lantern`

**Fantasy / elven** — `calcite` 50 · `smooth_quartz` 30 · `warped_planks` 20
Trim: `end_rod`, `azalea_leaves`, `birch_fence`
Roof: `warped_stairs`; lights `sea_lantern`, `shroomlight`

**Nether / dark** — `polished_blackstone_bricks` 50 · `blackstone` 30 · `gilded_blackstone` 20
Trim: `chain`, `iron_bars`, `basalt` columns
Roof: `polished_blackstone_brick_stairs`; lights `shroomlight`, `soul_lantern`

---

## 2. Depth: never emit a flat wall

Flat walls are the #1 tell of a beginner build. Every exterior face needs its
surface broken so light casts shadows across it.

**Rule: no unbroken flat face longer than 6–8 blocks.** Apply at least three of:

| Technique | Offset | Recipe |
|---|---|---|
| **Pillars** | +1 out | Vertical column every 3–5 blocks along the facade |
| **Inset windows** | −1 in | Recess the window and its frame one block into the wall |
| **Base plinth** | +1 out | Bottom 1–2 courses wider by 1, capped with a slab or upside-down stairs |
| **Cornice** | +1 out | Course just under the roof pushed out 1, capped with stairs |
| **Column recess** | −1 in | Push a 2–3 wide panel back 1 between pillars |
| **Belt course** | +1 out | A single accent-block band at each floor line |

Depth is *cheap* here — a plinth is 1 extra `cuboid`, pillars are one `cuboid`
each. There is no excuse for a flat wall.

### Surface texture (the 60/30/10 scatter)

Within one material family, mix three related blocks so the texture has noise:
`stone_bricks` 60 / `cracked_stone_bricks` 30 / `mossy_stone_bricks` 10.

With the current op set there is no noise-fill, so:

1. Fill the whole wall in the primary with one `cuboid`.
2. Scatter **1 accent block per 8–10 wall blocks** as individual `block` ops.

A *sparse, irregular* scatter reads as weathering. Do not attempt to place every
block individually — 15–25 scattered `block` ops is enough for a whole facade,
and placing them in a regular grid looks worse than not doing it at all.

---

## 3. Proportion and scale

| Measure | Value |
|---|---|
| Interior headroom | **3 blocks** minimum |
| Floor-to-floor story height | **4–5 blocks** |
| Roof rise | **4–10 blocks (1–2 stories)**. A 45° gable rises half its own width, so anything wider than ~20 needs split sections or a mansard |
| Roof overhang past walls | **1–2 blocks** (2–3 for Japanese/alpine) |
| Exterior wall thickness | 1 is fine for small builds *if* pillars give apparent depth; 2+ for anything castle-scale |
| Doorway | 2 wide × 3 tall for a main entrance; 1 × 2 is a closet |
| Window | 2×2 or 2×3, sill 1–2 blocks above floor |
| Footprint | Avoid squares. Aim ~1:1.5 (e.g. 8×12, not 10×10) |

A 20-wide building with a single 45° gable produces a 10-block roof — 2+ stories
of roof, badly out of proportion. Fix by splitting into multiple roof sections of
5–7 block rise each, adding a mansard break, or adding a parapet walkway.

On a small cottage the opposite holds: a 45° roof taller than its 4-block walls
is correct and reads as charming. Judge the rise against the 4–10 block band, not
against the walls.

---

## 4. Roofs

Pitch is set by how far you step in per course:

| Angle | Rise : run | Build with |
|---|---|---|
| **63.4°** steep | 2 : 1 | Full blocks, 2 up per 1 in |
| **45°** standard | 1 : 1 | Stairs, 1 up per 1 in |
| **26.6°** shallow | 1 : 2 | Alternating `[type=top]` / `[type=bottom]` slabs |

Rules:

- Start the roof **1 block outside** the wall line so the eave overhangs.
- Cap the ridge with a full block or a `[type=bottom]` slab run — never leave two
  stair rows meeting raw.
- Add `*_slab[type=top]` under the eave for a soffit; it reads as thickness.
- For **non-axis-aligned** or curved roofs use slabs and full blocks — stairs get
  awkward and leave gaps.
- Flat roofs are for modern builds only, and still need a **1-block parapet** so
  the silhouette isn't a bare plane.

---

## 5. Silhouette: break the rectangle

Judged from a distance, only the outline matters.

- **Never a plain box.** Use an L, T, U or cross footprint, or bolt on a
  projecting bay, porch, wing, or tower.
- **Vary the massing.** One element noticeably taller than the main mass gives
  the build a focal point.
- **Break symmetry deliberately.** Perfect mirroring reads as machine-made. Put
  the chimney off-centre, make one wing shorter.
- **Add a vertical accent**: chimney, tower, spire, flagpole (`oak_fence` stack),
  `lightning_rod`.

---

## 6. Light it

A build with zero light sources looks dead and spawns mobs. This is the most
commonly forgotten pass.

- **One light per 6–8 blocks** of facade, plus at least one per interior room.
- **Prefer `lantern` over `torch`.** Torches read as cheap. Hang lanterns from
  `chain` for a 2–3 block drop.
- By theme: `lantern`/`soul_lantern` (medieval, nordic), `sea_lantern`
  (modern, elven), `shroomlight` (warm/nether), `redstone_lamp` (industrial),
  `campfire` (exterior focal), `candle` (interior atmosphere),
  `end_rod` (fantasy), `glowstone` (hidden behind trim).
- Put lights *in* the depth you created — inside window recesses, under the
  cornice, flanking the doorway.

---

## 7. Ground it

Builds that stop abruptly at their bottom course look pasted-on.

- Widen the bottom 1–2 courses by 1 block as a foundation plinth.
- Cap the plinth with a slab or upside-down stairs.
- Scatter `coarse_dirt`, `gravel`, `moss_block`, or `podzol` along the base edge
  to soften the ground line.
- Use stairs and slabs at the base corners as chamfers.

---

## 8. Build the inside

The tool writes `air` into the schematic, so carved space really is empty on
paste. Use that:

- Carve openings explicitly with `air` after filling walls — do not leave solid.
- Give every enclosed volume a floor (`*_planks`, `stone_bricks`) distinct from
  the walls, and a ceiling or exposed beam structure
  (`stripped_oak_log[axis=x]` runs every 3–4 blocks).
- One light per room, minimum.
- Multi-story builds need a real staircase — a diagonal run of `*_stairs`, not a
  ladder shaft, unless the theme wants one.

---

## 9. Version awareness

A palette that is perfect on 1.19.4 can fail outright on 1.21.9. The target is
set by `mc_version` (default 1.19.4), and every block is validated against that
version's registry — but validation only catches what you got wrong, so pick
deliberately.

### Renamed blocks — the trap

These IDs were replaced, not just deprecated. Using the old one on a newer
version fails, and vice versa.

| Old ID | New ID | Renamed in |
|---|---|---|
| `chain` | `iron_chain` | 1.21.9 |
| `grass` | `short_grass` | 1.20.3 |
| `grass_path` | `dirt_path` | 1.17 |

Palettes in this guide target the 1.19.4 default. On **1.21.9 or newer, swap
`chain` for `iron_chain`.**

### What each version gives you to build with

Only building-relevant additions are listed.

| Version | Notable new building blocks |
|---|---|
| 1.19.3 | `bamboo_planks`, `bamboo_mosaic`, `bamboo_door`, `chiseled_bookshelf` |
| 1.19.4 | `cherry_planks`, `cherry_log`, `cherry_leaves`, `pink_petals`, `decorated_pot` |
| 1.20.3 | The full **copper build set** — `copper_bulb`, `copper_grate`, `copper_door`, `chiseled_copper`, plus **tuff**: `tuff_bricks`, `polished_tuff`, `chiseled_tuff` |
| 1.20.5 | `vault`, `heavy_core` |
| 1.21.3 | **Pale oak** — `pale_oak_planks`, `pale_oak_log`, `pale_moss_block`, `pale_hanging_moss`, `creaking_heart` |
| 1.21.4 | **Resin** — `resin_bricks`, `resin_block`, `chiseled_resin_bricks` |
| 1.21.5 | Ground cover — `leaf_litter`, `wildflowers`, `bush`, `firefly_bush`, `short_dry_grass` |
| 1.21.9 | **Copper lighting and shelves** — `copper_lantern`, `copper_torch`, `copper_bars`, `copper_chain`, `copper_golem_statue`, and `*_shelf` for every wood |
| 26.1 | `golden_dandelion` |
| 26.2 | **Sulfur and cinnabar** stone families — `cinnabar_bricks`, `polished_cinnabar`, `sulfur_bricks`, `polished_sulfur`, `chiseled_sulfur` |

Two upgrades worth targeting a newer version for:

- **1.20.3+** gives copper and tuff, which fill the biggest gap in the vanilla
  palette: mid-tone warm metal and neutral grey-brown stone. `polished_tuff` and
  `chiseled_copper` slot straight into the medieval and industrial palettes.
- **1.21.9+** finally gives *coloured light* — `copper_lantern` and `copper_torch`
  are warmer than iron lanterns, and `copper_bars` beat `iron_bars` for windows
  in any warm-toned build.

> Anything numbered **26.x** is provisional: the upstream registry this server
> vendors stops at 1.21.11, so those block lists come from the wiki and may be
> incomplete. They validate leniently — an unrecognised block warns rather than
> fails.

---

## Op cookbook

Recipes for the techniques above using only the current op set.

**Wall with pillars and a recessed panel**
```json
{"op": "cuboid", "start": [0, 1, 0], "end": [11, 4, 0], "block": "stone_bricks"},
{"op": "cuboid", "start": [0, 1, 1], "end": [0, 4, 1], "block": "stripped_oak_log[axis=y]"},
{"op": "cuboid", "start": [4, 1, 1], "end": [4, 4, 1], "block": "stripped_oak_log[axis=y]"},
{"op": "cuboid", "start": [8, 1, 1], "end": [8, 4, 1], "block": "stripped_oak_log[axis=y]"},
{"op": "cuboid", "start": [11, 1, 1], "end": [11, 4, 1], "block": "stripped_oak_log[axis=y]"}
```
The wall sits at z=0; pillars at z=1 protrude 1 toward the viewer.

**Plinth + cornice** (wall spans x 0..11, z 0..7, top at y=4)
```json
{"op": "cuboid", "start": [-1, 0, -1], "end": [12, 0, 8], "block": "stone_bricks"},
{"op": "hollow_box", "start": [-1, 1, -1], "end": [12, 1, 8], "block": "stone_brick_slab[type=top]", "walls": true, "floor": false, "ceiling": false},
{"op": "hollow_box", "start": [-1, 5, -1], "end": [12, 5, 8], "block": "stone_brick_stairs[half=top]", "walls": true, "floor": false, "ceiling": false}
```
The foundation course is a solid `cuboid` — it doubles as the ground floor. The
cap and the cornice must be **perimeter rings**, so pass
`"walls": true, "floor": false, "ceiling": false`.

> **`hollow_box` gotcha:** when `start` and `end` share the same Y, `floor`
> (default `true`) fills the entire plane, giving a solid slab rather than a
> ring. Always set `floor` and `ceiling` to `false` for single-course rings,
> ledges, belt courses and battlements.

**Inset window band** — fill the wall, then carve, then frame
```json
{"op": "cuboid", "start": [2, 2, 0], "end": [3, 3, 0], "block": "air"},
{"op": "cuboid", "start": [2, 2, 1], "end": [3, 3, 1], "block": "glass_pane"},
{"op": "block", "pos": [2, 1, 0], "block": "oak_stairs[half=top,facing=north]"},
{"op": "block", "pos": [3, 1, 0], "block": "oak_stairs[half=top,facing=north]"}
```
Glass one block *behind* the wall face is what makes the window read as inset.

**45° gable roof** — one `cuboid` strip per course. Building x 0..11, z 0..7,
walls topping at y=4. Ridge runs along X, slopes fall along Z:
```json
{"op": "cuboid", "start": [-1, 5, -1], "end": [12, 5, -1], "block": "dark_oak_stairs[facing=south]"},
{"op": "cuboid", "start": [-1, 5,  8], "end": [12, 5,  8], "block": "dark_oak_stairs[facing=north]"},
{"op": "cuboid", "start": [-1, 6,  0], "end": [12, 6,  0], "block": "dark_oak_stairs[facing=south]"},
{"op": "cuboid", "start": [-1, 6,  7], "end": [12, 6,  7], "block": "dark_oak_stairs[facing=north]"},
{"op": "cuboid", "start": [-1, 7,  1], "end": [12, 7,  1], "block": "dark_oak_stairs[facing=south]"},
{"op": "cuboid", "start": [-1, 7,  6], "end": [12, 7,  6], "block": "dark_oak_stairs[facing=north]"},
{"op": "cuboid", "start": [-1, 8,  2], "end": [12, 8,  2], "block": "dark_oak_stairs[facing=south]"},
{"op": "cuboid", "start": [-1, 8,  5], "end": [12, 8,  5], "block": "dark_oak_stairs[facing=north]"},
{"op": "cuboid", "start": [-1, 9,  3], "end": [12, 9,  4], "block": "dark_oak_planks"}
```
Each course steps up 1 and in 1 from **both** sides, so the roof narrows by 2 per
course. Keep going until 1–2 blocks remain, then cap that as the ridge.

**Work the arithmetic out before you emit the ops.** Eaves here span z −1..8, so
the width is 10: courses leave 10 → 8 → 6 → 4 → 2. An even width always lands on
a 2-wide ridge (cap with full blocks or a `[type=bottom]` slab run); an odd width
peaks at a single ridge line. Stopping a course early leaves a wide flat top —
that is a mansard, not a gable, and it looks like a mistake unless intended.

Both slopes share one facing each, opposite to the other. **If the slope looks
inverted in-game, swap the two `facing` values.**

**Round tower with conical roof** — stack shrinking rings
```json
{"op": "cylinder", "center": [0, 0, 0], "radius": 4, "height": 14, "block": "stone_bricks", "hollow": true},
{"op": "cylinder", "center": [0, 14, 0], "radius": 5, "height": 1, "block": "stone_brick_slab[type=top]"},
{"op": "cylinder", "center": [0, 15, 0], "radius": 4, "height": 1, "block": "dark_oak_stairs"},
{"op": "cylinder", "center": [0, 16, 0], "radius": 3, "height": 1, "block": "dark_oak_stairs"},
{"op": "cylinder", "center": [0, 17, 0], "radius": 2, "height": 1, "block": "dark_oak_stairs"},
{"op": "cylinder", "center": [0, 18, 0], "radius": 1, "height": 1, "block": "dark_oak_planks"},
{"op": "block", "pos": [0, 19, 0], "block": "lightning_rod"}
```
The radius-5 slab ring at y=14 is the overhanging eave.

**Arched doorway** — carve with `air`, then round the top corners
```json
{"op": "cuboid", "start": [5, 1, 0], "end": [6, 3, 0], "block": "air"},
{"op": "block", "pos": [5, 4, 0], "block": "stone_brick_stairs[half=top,facing=east]"},
{"op": "block", "pos": [6, 4, 0], "block": "stone_brick_stairs[half=top,facing=west]"}
```

**Battlements** — alternating merlons via a strip then a scatter of `air`
```json
{"op": "hollow_box", "start": [0, 12, 0], "end": [15, 13, 15], "block": "stone_bricks", "walls": true, "floor": false, "ceiling": false},
{"op": "block", "pos": [1, 13, 0], "block": "air"},
{"op": "block", "pos": [3, 13, 0], "block": "air"},
{"op": "block", "pos": [5, 13, 0], "block": "air"}
```

**Texture scatter** — after filling the wall
```json
{"op": "block", "pos": [2, 2, 0], "block": "cracked_stone_bricks"},
{"op": "block", "pos": [7, 1, 0], "block": "cracked_stone_bricks"},
{"op": "block", "pos": [9, 3, 0], "block": "mossy_stone_bricks"},
{"op": "block", "pos": [4, 4, 0], "block": "cracked_stone_bricks"}
```

---

## Detail vocabulary

Cheap, high-impact single blocks. Reach for these in the final pass.

| Element | Blocks |
|---|---|
| Shutters | `oak_trapdoor[facing=north,open=true]`, `dark_oak_trapdoor` |
| Windows | `glass_pane`, `iron_bars`, `tinted_glass` (1.17+) |
| Railings | `oak_fence`, `*_wall`, `iron_bars` |
| Hanging lights | `lantern[hanging=true]` under `chain` |
| Windowsill | `*_stairs[half=top]`, `*_slab[type=top]` |
| Beams | `stripped_*_log[axis=x]` / `[axis=z]` |
| Greenery | `oak_leaves`, `azalea_leaves`, `flowering_azalea_leaves`, `moss_block`, `flower_pot` |
| Chimney | `bricks` column + `campfire` top |
| Roof ridge | `*_slab[type=bottom]` run, or `*_wall` |
| Door | `oak_door[facing=north,half=lower]` + `[half=upper]` — needs both halves |

---

## Anti-patterns

Each of these appeared in this repo's own `examples/japanese_pagoda.json`
(849 blocks, 4 materials, 59% `dark_oak_planks`, **0 stairs, 0 lights,
0 windows**) — a worked example of what to avoid.

| Anti-pattern | Fix |
|---|---|
| One block dominating >50% of the build | Apply the 50/30/20 palette |
| Zero stairs or slabs | Stairs/slabs are the detail workhorses — trim, roofs, sills |
| Zero light sources | One light per 6–8 blocks of facade, one per room |
| Roof same material as walls | Contrast the roof |
| Flat unbroken wall face | Pillars, inset, plinth, cornice |
| Perfectly square footprint | ~1:1.5, and break the rectangle |
| Solid interior / no carved space | Carve with `air`, floor and light every room |
| Build stops flat at its base | Foundation plinth + ground scatter |
| Hundreds of `block` ops for a wall | Use `cuboid`; reserve `block` for scatter and detail |

---

## Pre-flight checklist

Run this before every `create_minecraft_structure` call. If you cannot answer
yes, fix the JSON first.

1. **Palette** — 3–5 blocks, roughly 50/30/20? Roof material ≠ wall material?
2. **Depth** — at least 3 depth techniques applied? No flat face over 6–8 blocks?
3. **Texture** — a sparse accent scatter on large wall faces?
4. **Proportion** — 3+ headroom, 4–5 per story, roof rise in the 4–10 band?
5. **Roof** — real pitch, arithmetic checked to a 1–2 wide ridge, overhangs 1–2 blocks, ridge capped?
6. **Silhouette** — not a plain box? One taller focal element?
7. **Openings** — doors 2×3, windows inset with glass set 1 back?
8. **Light** — one per 6–8 blocks of facade, one per interior room?
9. **Ground** — foundation plinth and a base transition?
10. **Interior** — carved with `air`, floored, lit?
11. **Efficiency** — walls and masses as `cuboid`/`hollow_box`, not block spam?
12. **Validity** — every block ID real for the target `mc_version`?

---

## Sources

Community building conventions this guide distills:

- [Planet Minecraft — Basic depth and detail](https://www.planetminecraft.com/blog/how-to-become-a-better-builder-basic-depth-and-detail/)
- [ByPixelbot — 4 common beginner mistakes](https://www.bypixelbot.com/blog/how-to-not-build-in-minecraft)
- [Switchblade Gaming — Building tips, beginner to pro](https://www.switchbladegaming.com/minecraft/building-tips/)
- [Minecraft Wiki — Roof construction guidelines](https://minecraft.wiki/w/Tutorial:Roof_construction_guidelines)
- [BlockBlend — Medieval palette guide](https://blockblend.app/guides/medieval-palette-guide)
- [Sportskeeda — Adding depth to builds](https://www.sportskeeda.com/minecraft/4-best-ways-add-depth-minecraft-build)
