# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Partial-block geometry in the 3D viewer.** Stairs, slabs, fences, walls,
  fence gates, glass panes, iron bars, doors, trapdoors, lanterns, chains,
  torches, campfires, candles, carpets, rods, pots, plates and buttons now
  render with real shapes instead of full cubes, with orientation parsed from
  block states (`oak_stairs[facing=south,half=top]`). Shapes are grouped into
  one `InstancedMesh` per (geometry, material) pair, so draw calls stay in the
  dozens regardless of block count. Glass renders translucent; light-emitting
  blocks render unlit so they read as light sources. Fences, walls and panes
  connect to their neighbours.
- Occlusion culling now only treats full opaque cubes as enclosing
  (`payload.occludes`): a voxel behind glass or under a stair stays visible
  instead of being dropped as "hidden".
- **Programmatic style checks (`lint.py`).** The style guide's pre-flight
  checklist, encoded: palette size and dominance (shape variants fold into
  their material family), unbroken flat exterior faces (flood-fill
  distinguishes exterior from interior walls), zero stairs/slabs, zero or
  sparse lighting, missing carved interior, near-square footprints, roof
  matching the walls, and per-voxel block spam. Anti-patterns report as
  warnings, structural heuristics as notes, and small builds stay quiet.
  `create_minecraft_structure` and `show_structure` now append the verdict to
  their results, so every build gets the same review the guide asks the model
  to run on itself. The repo's own `examples/japanese_pagoda.json` — the
  guide's worked anti-pattern — trips six findings; a guide-following cottage
  comes back clean.
- **Material rendering in the 3D viewer.** Mojang's textures can't be shipped,
  so each material family gets a generated 16x16 luminance map instead (plank
  seams, brick courses, stone-brick tiles, log grain, speckled cobble, leaf
  noise) multiplied with the palette colour, plus a deterministic per-block
  tint jitter on natural materials and a one-pixel darker rim per face as
  cheap ambient occlusion. Builds now sit in a world: sky gradient, fog, a
  tiled grass plane, and a real sun shadow sized to the build's bounds. The
  ground grid is off by default (still available in the panel), and the HUD
  got a panel background so it stays readable against the sky.
- **`await_prompt` tool — browser chat without channels.** Prompts typed in the
  viewer now queue server-side, and Claude collects them by calling
  `await_prompt` in a loop (long-poll, default 240 s per round). This makes the
  chat work where channels cannot: org policies that block
  `--dangerously-load-development-channels`, Bedrock/Vertex/Foundry, or a
  session started without the flag. Channels still work and take precedence
  when enabled; a channel-delivered prompt is never double-delivered through
  the queue.
- The viewer's status dot now distinguishes *proven* listening (an
  `await_prompt` call is blocked right now) from the weaker "an MCP session
  exists", and `/api/status` reports `waiting`, `polling` and `queued`.

## [0.2.0]

### Added
- **Shape operations** — declarative primitives that expand to blocks server-side
  instead of the model emitting every voxel: `cuboid`, `hollow_box`, `sphere`,
  `cylinder`, `line`, `pyramid`, `dome`, `cone`, `ellipsoid`, `torus`, `block`,
  `replace`. Operations apply in order with later-wins layering (fill a wall,
  then carve a window with `air`).
- **Multi-version support** — target any release from `1.13` to `26.2` via
  `mc_version`, backed by a span-based block registry (`data/mc_versions.json`,
  `data/block_versions.tsv`). Releases newer than mcschematic's bundled enum are
  reached through the raw NBT DataVersion.
- **Block-ID validation** — unknown vanilla blocks are diagnosed as a typo,
  too-new, or renamed, with suggestions; `strict` turns warnings into errors.
- **`get_build_style_guide` tool** and an embedded checklist so builds come out
  looking designed (palettes, depth, roofs, lighting), tested against the
  registry so palettes can't silently rot.
- **`preview_structure` tool** — ASCII layer slices + stats without saving a
  file, so the model can sanity-check geometry first.
- Cross-platform folder opening (`open_output_folder`: Explorer/Finder/xdg-open).
- CI (pytest on Python 3.10–3.12 × Linux/Windows) plus ruff and mypy checks.
- `LICENSE` (MIT) and this changelog.

### Changed
- `open_folder_in_explorer` renamed to `open_output_folder` (old name kept as an
  alias). Windows-only path assumptions relaxed; WSL `/mnt` conversion now only
  runs on native Windows.
- Create-tool result reports richer stats (solid/air split, fill ratio, top
  block types) and the target version.

### Fixed
- Blocks placed at negative coordinates were silently dropped; the structure is
  now offset to the origin so they survive.

## [0.1.0]
- Initial release: `create_minecraft_structure` from explicit block lists,
  `.schem` output, and a Windows-only folder-opening helper.
