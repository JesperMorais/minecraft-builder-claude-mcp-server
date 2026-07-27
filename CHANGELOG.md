# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/).

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
