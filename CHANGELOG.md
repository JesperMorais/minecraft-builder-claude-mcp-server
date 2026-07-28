# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **The review loop: render, critique, patch, repeat.** Having a tool that
  returns pictures is not the same as using it, so the loop is now the path the
  server steers toward — in the system prompt, in the export tool's description,
  and in the result text of everything that produces a build, which is where the
  advice is actually actionable. Three rounds is the stated budget; builds
  improve sharply for two or three passes and then stop.

  Every render returns a six-point visual critique (`VISUAL_CRITIQUE_CHECKLIST`
  in `style.py`) covering silhouette, palette, depth, roofline, light and
  grounding. It is phrased as what to *look* for rather than what to count,
  because `lint.py` already counts and reports everything it can reach from the
  JSON — what it cannot see is whether the result looks right. A build can
  satisfy the palette ratio and still read as one grey slab, or place its
  lanterns correctly and hide every one behind a roof overhang. The rubric asks
  for one fix per round on purpose: fixing everything at once means not knowing
  which edit helped.

  **The loop yields to the human.** It stops as soon as the user says anything or
  starts marking up the build, because a revision landing mid-annotation
  repoints the note they are writing — the same failure annotations resolve at
  creation time to avoid. Renders still never touch `ViewerState`.

  **None of this guidance appears without the render extra installed.**
  `rendering_available()` probes once at startup with `find_spec`, and the
  instructions, the export tool's description and the build results all drop
  their render step when it comes back false. Guidance naming an uninstalled tool
  is worse than no guidance: it would arrive on every single build, and the fix
  is a browser download the user may have declined deliberately. The tool itself
  stays listed either way, so the feature is discoverable and can explain its own
  install.
- **`render_structure`: Claude can see its own builds.** Every other feedback
  path in this server describes a build in words — ASCII slices, block counts, a
  style verdict. This one photographs it. A headless Chromium loads the real
  viewer with `?render=1`, the tool aims the camera at four isometric corners and
  one level elevation, and the PNGs come back as MCP image content, so the model
  reviews what it actually made rather than what it meant to emit.

  It drives the existing viewer rather than shipping a renderer of its own: a
  second renderer would be a second thing to keep in step with `viewer.js`, and
  every disagreement between them would be invisible — the model would be
  reviewing a picture the user never sees. The structure reaches the page by
  intercepting its `/api/structure` fetch instead of going through
  `ViewerState`, so taking a picture cannot bump the version, replace what the
  user is looking at, or repoint a note they have not applied yet.

  Angles are compass bearings for where the camera stands, matching Minecraft's
  own compass (0 = north = -Z, 90 = east = +X), and the framing maths lives in
  Python so it can be tested without a browser. `count` takes a prefix of the
  standard set — ordered so one image is the corner the viewer opens at, two add
  the elevation, three show the back — or pass explicit `angles`. With no
  structure argument it renders whatever `show_structure` last displayed.

  Playwright is an optional extra (`pip install ".[render]"`), because it brings
  a browser with it. Missing library, missing browser and an unreachable CDN each
  come back as one sentence naming the command that fixes it; nothing else in the
  server is affected by its absence.

  Render mode also stops the viewer's animation loop and turns on
  `preserveDrawingBuffer`. Chromium software-rasterises every frame here, so an
  idle loop leaves each screenshot queueing behind it for the one thread doing
  the work — dropping it took a five-view render from 45 seconds to 7.
- **The annotation loop (Phase 3).** Mark up a build in the viewer and have
  Claude act on it. Tick *Mark up the build*, click a block or Shift-click two
  blocks to box a region, and attach a note; notes collect in a tray with an
  **Apply notes** button.

  The point is that a note names an *operation*, not a coordinate. The server
  resolves the click through `expand_with_provenance()` **at the moment it is
  made**, against the version on screen — resolve later and it would silently
  point at whatever occupies that coordinate after a revision. So Claude receives
  *"operation #4 (pyramid centre=[8,5,8] base=6), the roof: too steep"* and can
  edit that one operation. A region resolves to the operation owning the most
  voxels in it (a box round a roof always clips a wall), reports its coverage
  share and what else it touched, and breaks ties toward the later operation
  since that is the one drawn on top.

  Three new tools: `get_annotations`, `patch_operations` and
  `resolve_annotations`. `patch_operations` does `replace`/`insert`/`delete` by
  index, and **every index in one call refers to the pre-patch structure**, so a
  batch of notes cannot shift each other's targets — applying them sequentially
  would turn a delete into an off-by-one on every later patch. It re-shows the
  build itself. Picking uses the per-instance records the renderer already keeps,
  so a click maps back to the exact voxel rather than rounding a hit point to a
  cell, which would be wrong for every partial block.
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
  once they have proven themselves, at which point a channel-delivered prompt
  is not also queued.
- **Proof of delivery for the channel path.** Channel events are
  unacknowledged, so nothing on the outbound side could tell a delivered push
  from one a policy-blocked client dropped. A reply coming back is that proof:
  the `reply` tool latches `ChannelBridge.confirm()`, which is ignored unless an
  event was pushed first — Claude also calls `reply` from ordinary terminal
  turns and from the `await_prompt` loop, neither of which involves a channel.
  `/api/status` reports `confirmed` alongside `waiting`, `polling`, `queued` and
  `events_sent`, and all three responses that answer "does chat work" now come
  from one `_link_status()` so they cannot disagree.

### Fixed
- **Browser prompts were silently destroyed whenever an MCP session was
  attached.** `ChannelBridge.push()` reports that a frame reached the transport,
  not that Claude received it, and the bridge is attached for every stdio
  session whether or not the channel is enabled. A session with channels
  blocked by org policy therefore accepted the write, discarded the
  notification, and `push()` still returned `True` — so the HTTP layer skipped
  the queue and the prompt was gone. The `await_prompt` fallback could not save
  it either, because nothing was ever queued: a loop blocked and waiting
  received nothing, while `/api/prompt` answered `delivered=True`. Prompts are
  now queued as well as pushed until the channel is confirmed, and the queued
  copies are dropped once it is, so `await_prompt` cannot replay an
  already-answered prompt. The whole test suite ran with the bridge detached,
  which is why this was invisible; there is now a fixture that attaches one.
- **The status dot told the truth in its label but not in its colour.** It ORed
  `attached` into green, so "an MCP session exists" was painted identically to
  proven delivery — the reason a green dot reported a healthy link through an
  entire debugging session in which nothing arrived. Green is now reserved for
  evidence that a prompt gets collected (`waiting`, `polling`, or a confirmed
  channel), a bare `attached` is amber with a tooltip explaining what to do
  about it, and nothing listening stays red.

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
