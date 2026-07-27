"""Minecraft version support and block-ID validation.

Two vendored data files back this module (see ``data/README.md``):

* ``data/mc_versions.json`` — every supported release, in order, with its NBT
  ``DataVersion``.
* ``data/block_versions.tsv`` — one row per block: the version it was added in
  and, if it was later removed or renamed, the last version that still had it.

A block is valid for a version when that version falls inside the block's
[added, removed_after] span. Storing spans rather than a per-version list keeps
46 registries in one 28 KB file, and is what lets the server answer "what's new
in this version" and "when did this block appear".

Validation stays lenient: an unknown vanilla block yields a *warning* with fuzzy
"did you mean" suggestions rather than a hard failure. Non-vanilla namespaces
(modded blocks) are skipped entirely.
"""

from __future__ import annotations

import difflib
import json
from functools import lru_cache
from importlib import resources
from typing import Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Tuple

DEFAULT_VERSION = "1.19.4"


class BlockSpan(NamedTuple):
    """The version range a block exists in."""

    added: str
    removed_after: Optional[str]  # None while the block is still current


@lru_cache(maxsize=1)
def _version_data() -> Tuple[Tuple[str, ...], Dict[str, int], FrozenSet[str]]:
    """(ordered versions, version -> DataVersion, provisional versions)."""
    raw = json.loads(
        resources.files("minecraft_builder.data")
        .joinpath("mc_versions.json")
        .read_text(encoding="utf-8")
    )
    return (
        tuple(raw["versions"]),
        {v: int(dv) for v, dv in raw["data_versions"].items()},
        frozenset(raw.get("provisional", ())),
    )


def supported_versions() -> Tuple[str, ...]:
    """Every supported release, oldest first."""
    return _version_data()[0]


def _version_index() -> Dict[str, int]:
    return {v: i for i, v in enumerate(supported_versions())}


# Mapping kept for backwards compatibility: version -> NBT DataVersion.
class _SupportedVersions(Dict[str, int]):
    """``dict``-alike so ``SUPPORTED_VERSIONS`` stays iterable and sortable."""


SUPPORTED_VERSIONS: Dict[str, int] = _SupportedVersions(_version_data()[1])

LATEST_VERSION = supported_versions()[-1]


def is_provisional(version: str) -> bool:
    """True when a version's block list is wiki-sourced and may be incomplete.

    Minecraft's move to the year-based ``26.x`` scheme outran the upstream
    registry we vendor from, so those versions carry an approximate block list.
    """
    return version in _version_data()[2]


def normalize_version(version: str) -> str:
    """Validate and return a supported version string, or raise ValueError."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"Unsupported Minecraft version {version!r}. "
            f"Supported: {', '.join(supported_versions())}."
        )
    return version


def data_version(version: str) -> int:
    """The NBT ``DataVersion`` stamped into a schematic for this release."""
    return SUPPORTED_VERSIONS[normalize_version(version)]


class _DataVersion(NamedTuple):
    """Stand-in for ``mcschematic.Version``.

    ``MCSchematic.save`` only ever reads ``version.value``, so supplying the raw
    DataVersion lets us target releases newer than the enum bundled with
    mcschematic (which stops at 1.21.5).
    """

    value: int


def mcschematic_version(version: str) -> _DataVersion:
    """Return something ``MCSchematic.save`` accepts as its ``version``."""
    return _DataVersion(data_version(version))


@lru_cache(maxsize=1)
def _block_spans() -> Dict[str, BlockSpan]:
    """block name -> the version span it exists in."""
    text = (
        resources.files("minecraft_builder.data")
        .joinpath("block_versions.tsv")
        .read_text(encoding="utf-8")
    )
    spans: Dict[str, BlockSpan] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, added, removed = (line.split("\t") + ["", ""])[:3]
        spans[name] = BlockSpan(added, removed or None)
    return spans


def block_span(block_id: str) -> Optional[BlockSpan]:
    """The version span for a block, or None if it isn't a known vanilla block."""
    return _block_spans().get(base_block_id(block_id))


@lru_cache(maxsize=None)
def load_block_ids(version: str) -> FrozenSet[str]:
    """The set of valid base block ids (no namespace/state) for a version."""
    normalize_version(version)
    idx = _version_index()
    here = idx[version]
    return frozenset(
        name
        for name, span in _block_spans().items()
        if idx[span.added] <= here
        and (span.removed_after is None or here <= idx[span.removed_after])
    )


def blocks_added_in(version: str) -> FrozenSet[str]:
    """Blocks that first appeared in this exact version."""
    normalize_version(version)
    return frozenset(n for n, s in _block_spans().items() if s.added == version)


def blocks_removed_after(version: str) -> FrozenSet[str]:
    """Blocks whose last appearance was this version (removed or renamed next)."""
    normalize_version(version)
    return frozenset(n for n, s in _block_spans().items() if s.removed_after == version)


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


def explain_unknown(block_id: str, version: str) -> str:
    """Human-readable reason a block failed validation for a version.

    A block that exists in *some* release is the most useful diagnosis of all:
    it means the build targets the wrong version rather than having a typo.
    """
    base = base_block_id(block_id)
    span = _block_spans().get(base)
    if span is None:
        matches = difflib.get_close_matches(base, load_block_ids(version), n=3, cutoff=0.6)
        return f"did you mean: {', '.join(matches)}?" if matches else "not a known block"

    idx = _version_index()
    if idx[span.added] > idx[version]:
        return f"added in {span.added} — target that version or newer to use it"
    replacement = RENAMED_TO.get(base)
    if replacement:
        return f"renamed to `{replacement}` after {span.removed_after}"
    return f"removed after {span.removed_after}"


# Blocks that were renamed rather than deleted; used to give an actionable hint.
RENAMED_TO: Dict[str, str] = {
    "chain": "iron_chain",
    "grass": "short_grass",
    "grass_path": "dirt_path",
    "sign": "oak_sign",
    "wall_sign": "oak_wall_sign",
}
