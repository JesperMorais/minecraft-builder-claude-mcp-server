"""Converts JSON structure definitions to Minecraft schematic files.

Two output formats, from the same expanded block map:

* ``.schem`` (Sponge Schematic v2) — WorldEdit's format. ``//schem load`` then
  ``//paste`` drops the build in instantly; needs creative or operator rights.
* ``.litematic`` — Litematica's own format. Renders the build as a translucent
  hologram you construct by hand in survival, with a material list. Litematica
  can read ``.schem`` on 1.17+, but that path is a stopgap in the mod and does
  not exist at all on 1.13-1.16, so writing its native format is the reliable
  way to hand someone a blueprint.
"""

from pathlib import Path
from typing import Dict, Iterable, Tuple

from mcschematic import MCSchematic, MCStructure

from .schema import MinecraftStructure
from .versions import DEFAULT_VERSION, mcschematic_version, normalize_version

# NBT DataVersion per supported release, which is how .litematic records the
# game version. Values from PrismarineJS minecraft-data (protocolVersions.json),
# the same source as the vendored block registries. Move this into
# data/mc_versions.json once that file lands, so there is a single source of
# truth for per-version metadata.
_DATA_VERSIONS: Dict[str, int] = {
    "1.19.4": 3337,
    "1.20.4": 3700,
    "1.21.4": 4189,
}

# Requestable output format -> file extension. One definition so the tool's
# schema, the writer, and the import instructions cannot drift apart.
OUTPUT_FORMATS: Dict[str, str] = {
    "schem": ".schem",
    "litematic": ".litematic",
}

DEFAULT_FORMATS = ("schem",)


class SchematicConverter:
    """Converts a MinecraftStructure to .schem or .litematic."""

    @staticmethod
    def normalize_block_id(block_id: str) -> str:
        """Ensure a block ID has the ``minecraft:`` namespace.

        Block-state suffixes are preserved, e.g. ``oak_log[axis=y]`` becomes
        ``minecraft:oak_log[axis=y]`` while ``minecraft:stone`` is untouched.
        """
        base = block_id.split("[", 1)[0]
        if ":" in base:
            return block_id
        return f"minecraft:{block_id}"

    @staticmethod
    def split_block_state(block_id: str) -> Tuple[str, Dict[str, str]]:
        """Split a block ID into its identifier and its block-state properties.

        ``oak_log[axis=y]`` -> ``("minecraft:oak_log", {"axis": "y"})``.

        mcschematic accepts the bracketed string as-is, but litemapy takes
        properties as keyword arguments and rejects an identifier containing
        brackets, so the two formats need this split.
        """
        normalized = SchematicConverter.normalize_block_id(block_id)
        identifier, _, remainder = normalized.partition("[")
        if not remainder:
            return identifier, {}

        state = remainder.rstrip("]")
        properties: Dict[str, str] = {}
        for pair in state.split(","):
            pair = pair.strip()
            if not pair:
                continue
            key, sep, value = pair.partition("=")
            if not sep:
                raise ValueError(
                    f"Malformed block state in {block_id!r}: expected key=value "
                    f"pairs inside the brackets, got {pair!r}."
                )
            properties[key.strip()] = value.strip()
        return identifier, properties

    @staticmethod
    def write_formats(
        structure: MinecraftStructure,
        output_dir: Path,
        stem: str,
        version: str = DEFAULT_VERSION,
        formats: Iterable[str] = DEFAULT_FORMATS,
    ) -> Dict[str, str]:
        """Write ``structure`` in each requested format under ``output_dir``.

        Args:
            structure: The structure to write.
            output_dir: Directory to write into; created if absent.
            stem: Filename without extension.
            version: Target Minecraft version.
            formats: Any of ``OUTPUT_FORMATS``.

        Returns:
            ``{format: absolute path}`` in the order requested.

        Raises:
            ValueError: If a format name is unknown or none were requested.
            StructureTooLargeError: If the structure breaches a safety ceiling.
        """
        requested = list(dict.fromkeys(formats))  # dedupe, keep order
        if not requested:
            raise ValueError(
                f"No output format requested. Choose from: "
                f"{', '.join(sorted(OUTPUT_FORMATS))}."
            )
        unknown = [f for f in requested if f not in OUTPUT_FORMATS]
        if unknown:
            raise ValueError(
                f"Unknown output format(s): {', '.join(unknown)}. "
                f"Choose from: {', '.join(sorted(OUTPUT_FORMATS))}."
            )

        # Fail the size check once, before writing anything, so a refused build
        # never leaves a partial set of files behind.
        structure.check_limits()

        writers = {
            "schem": SchematicConverter.to_schematic,
            "litematic": SchematicConverter.to_litematic,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        written: Dict[str, str] = {}
        for fmt in requested:
            target = output_dir / f"{stem}{OUTPUT_FORMATS[fmt]}"
            written[fmt] = writers[fmt](structure, str(target), version)
        return written

    @staticmethod
    def _min_corner(block_map) -> Tuple[int, int, int]:
        """Lowest occupied coordinate on each axis.

        Both formats index from zero, so this is subtracted from every
        coordinate on the way out. Blocks at negative coordinates are therefore
        preserved rather than silently dropped. The offset stays inside the
        converter: everything upstream works in authoring coordinates, which is
        what keeps operation indices and annotations meaningful.
        """
        return (
            min(c[0] for c in block_map),
            min(c[1] for c in block_map),
            min(c[2] for c in block_map),
        )

    @staticmethod
    def to_schematic(
        structure: MinecraftStructure,
        output_path: str,
        version: str = DEFAULT_VERSION,
    ) -> str:
        """Convert a MinecraftStructure to a .schem file.

        The full block map (explicit blocks + expanded shape operations) is
        translated so that its minimum corner sits at the origin. This preserves
        blocks placed at negative coordinates instead of silently dropping them.

        Args:
            structure: The structure to convert.
            output_path: Path where the .schem file will be saved.
            version: Target Minecraft version (see versions.SUPPORTED_VERSIONS).

        Returns:
            Absolute path to the created file.
        """
        schem_version = mcschematic_version(version)
        block_map = structure.expand()

        mc_structure = MCStructure()
        if block_map:
            min_x, min_y, min_z = SchematicConverter._min_corner(block_map)
            for (x, y, z), block_type in block_map.items():
                normalized_id = SchematicConverter.normalize_block_id(block_type)
                mc_structure.setBlock(
                    (x - min_x, y - min_y, z - min_z), normalized_id
                )

        schem = MCSchematic(mc_structure)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # schemName should be without the .schem extension.
        schem_name = output_file.stem
        schem.save(
            outputFolderPath=str(output_file.parent),
            schemName=schem_name,
            version=schem_version,
        )

        return str(output_file.absolute())

    @staticmethod
    def to_litematic(
        structure: MinecraftStructure,
        output_path: str,
        version: str = DEFAULT_VERSION,
    ) -> str:
        """Convert a MinecraftStructure to a .litematic file for Litematica.

        Drop the result in ``.minecraft/schematics/`` and load it as a placement
        to get a hologram to build against.

        Args:
            structure: The structure to convert.
            output_path: Path where the .litematic file will be saved.
            version: Target Minecraft version (see versions.SUPPORTED_VERSIONS).

        Returns:
            Absolute path to the created file.

        Raises:
            StructureTooLargeError: If the structure breaches a safety ceiling.
            ValueError: If the version is unsupported or a block state is malformed.
        """
        from litemapy import BlockState, Region

        data_version = _DATA_VERSIONS[normalize_version(version)]
        block_map = structure.expand()

        if block_map:
            min_x, min_y, min_z = SchematicConverter._min_corner(block_map)
            width = max(c[0] for c in block_map) - min_x + 1
            height = max(c[1] for c in block_map) - min_y + 1
            length = max(c[2] for c in block_map) - min_z + 1
        else:
            # litemapy rejects a zero-sized region, so emit a 1x1x1 of air.
            min_x = min_y = min_z = 0
            width = height = length = 1

        region = Region(0, 0, 0, width, height, length)
        for (x, y, z), block_type in block_map.items():
            identifier, properties = SchematicConverter.split_block_state(block_type)
            region[x - min_x, y - min_y, z - min_z] = BlockState(identifier, **properties)

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        schematic = region.as_schematic(
            name=structure.name,
            description=structure.description or "",
            mc_version=data_version,
        )
        schematic.save(str(output_file))

        return str(output_file.absolute())
