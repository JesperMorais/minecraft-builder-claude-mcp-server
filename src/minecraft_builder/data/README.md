# Vendored block/version data

Two files back `versions.py`:

| File | Contents |
|---|---|
| `mc_versions.json` | Every supported release in chronological order, with its NBT `DataVersion` |
| `block_versions.tsv` | One row per block: `name`, the version it was added in, and the last version that still had it (blank if current) |

Storing **spans** rather than one list per version keeps 46 registries in ~28 KB,
and is what lets the server answer "what's new in 1.21.9?" and "when did this
block appear?" — not just "is this block valid?".

## Why spans need a removal column

Five blocks were renamed rather than merely added, so a first-seen version alone
would wrongly mark them valid forever:

| Old ID | New ID | Renamed in |
|---|---|---|
| `chain` | `iron_chain` | 1.21.9 |
| `grass` | `short_grass` | 1.20.3 |
| `grass_path` | `dirt_path` | 1.17 |
| `sign` | `oak_sign` | 1.14 |
| `wall_sign` | `oak_wall_sign` | 1.14 |

## Source

Generated from [PrismarineJS/minecraft-data][mcdata], which publishes per-version
block registries extracted from the game, plus its `protocolVersions.json` for
`DataVersion` numbers.

[mcdata]: https://github.com/PrismarineJS/minecraft-data

## Provisional versions

Minecraft moved from `1.21.x` to a year-based `26.x` scheme, and minecraft-data
has not caught up — its newest registry is 1.21.11. Blocks for `26.1`–`26.2`
therefore come from [minecraft.wiki](https://minecraft.wiki) and are listed under
`provisional` in `mc_versions.json`. They may be incomplete; validation is
lenient, so an unrecognised block warns rather than fails.

Move a version out of `PROVISIONAL` in the regeneration script once upstream
publishes its registry.

## Regeneration

```bash
python scripts/regen_block_data.py
```

The script is idempotent — rerunning it with no upstream changes leaves both
files byte-identical. It refuses to write if any block's version span turns out
to be non-contiguous, which would break the range model.

Writing schematics for a version needs only its `DataVersion`: `MCSchematic.save`
reads `version.value` and nothing else, so `versions.mcschematic_version()`
returns a lightweight stand-in. That is how releases newer than the enum bundled
with `mcschematic` (which stops at 1.21.5) can still be targeted.
