# Vendored block-ID lists

Each `blocks_<version>.txt` holds one base Minecraft block id per line (no
`minecraft:` namespace, no block-state suffix), sorted. They back the
block-ID validation in `versions.py`.

## Source

Generated from [PrismarineJS/minecraft-data][mcdata], which publishes per-version
block registries extracted from the game.

[mcdata]: https://github.com/PrismarineJS/minecraft-data

## Regeneration

```bash
for v in 1.19.4 1.20.4 1.21.4; do
  curl -sSL "https://raw.githubusercontent.com/PrismarineJS/minecraft-data/master/data/pc/$v/blocks.json" \
    | python3 -c "import json,sys; print('\n'.join(sorted(b['name'] for b in json.load(sys.stdin))))" \
    > "src/minecraft_builder/data/blocks_${v//./_}.txt"
done
```

To add a new version: confirm `mcschematic` supports it (`Version.JE_<ver>`),
add it to `SUPPORTED_VERSIONS` in `versions.py`, and regenerate its list.
