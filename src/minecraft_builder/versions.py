"""Minecraft version support and block-ID validation.

Block lists live in ``data/blocks_<version>.txt`` (one base block id per line,
no namespace, no block state). They are generated from PrismarineJS
minecraft-data — see ``data/README.md`` for the regeneration command.

Validation is intentionally lenient: an unknown vanilla block yields a *warning*
with fuzzy "did you mean" suggestions rather than a hard failure, so builds
don't break just because a newer block isn't in the vendored list. Non-vanilla
namespaces (modded blocks) are skipped entirely.
"""

from __future__ import annotations

import difflib
from functools import lru_cache
from importlib import resources
from typing import Dict, FrozenSet, Iterable, List

# Supported release -> the mcschematic Version enum member name.
SUPPORTED_VERSIONS: Dict[str, str] = {
    "1.19.4": "JE_1_19_4",
    "1.20.4": "JE_1_20_4",
    "1.21.4": "JE_1_21_4",
}

DEFAULT_VERSION = "1.19.4"


def normalize_version(version: str) -> str:
    """Validate and return a supported version string, or raise ValueError."""
    if version not in SUPPORTED_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_VERSIONS))
        raise ValueError(
            f"Unsupported Minecraft version {version!r}. Supported: {supported}."
        )
    return version


def mcschematic_version(version: str):
    """Return the mcschematic ``Version`` enum member for a supported version."""
    from mcschematic import Version

    return getattr(Version, SUPPORTED_VERSIONS[normalize_version(version)])


@lru_cache(maxsize=None)
def load_block_ids(version: str) -> FrozenSet[str]:
    """Load the set of valid base block ids (no namespace/state) for a version."""
    normalize_version(version)
    filename = f"blocks_{version.replace('.', '_')}.txt"
    text = resources.files("minecraft_builder.data").joinpath(filename).read_text()
    return frozenset(line.strip() for line in text.splitlines() if line.strip())


def base_block_id(block_id: str) -> str:
    """Strip the namespace and block-state suffix to the bare block name.

    ``minecraft:oak_log[axis=y]`` -> ``oak_log``; ``mymod:gadget`` -> ``mymod:gadget``
    (a non-minecraft namespace is preserved so it can be recognised as modded).
    """
    without_state = block_id.split("[", 1)[0].strip()
    namespace, sep, name = without_state.partition(":")
    if not sep:
        return without_state  # no namespace -> already a bare name
    if namespace == "minecraft":
        return name
    return without_state  # foreign namespace kept intact


def validate_block_ids(
    block_ids: Iterable[str], version: str
) -> Dict[str, List[str]]:
    """Return a mapping of unknown vanilla block id -> fuzzy suggestions.

    Blocks in a non-``minecraft`` namespace are treated as modded and skipped.
    An empty mapping means everything validated cleanly.
    """
    valid = load_block_ids(version)
    unknown: Dict[str, List[str]] = {}
    for raw in dict.fromkeys(block_ids):  # dedupe, preserve order
        base = base_block_id(raw)
        if ":" in base:
            continue  # foreign namespace -> assume modded, don't flag
        if base in valid:
            continue
        if base not in unknown:
            unknown[base] = difflib.get_close_matches(base, valid, n=3, cutoff=0.6)
    return unknown
