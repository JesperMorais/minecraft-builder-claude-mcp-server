"""Targeted edits to a structure's operation list.

The reason this exists: "the roof is too steep" should cost one operation edit,
not a 200-operation rewrite. Claude gets an annotation naming operation #4, and
patching that index is a far smaller and more reliable act than regenerating the
whole build — which in practice also loses the parts the user liked.

**Indices refer to the structure as it was, never to a partially patched one.**
A batch of patches comes from a batch of annotations, all resolved against the
same version, so every index in the batch means what it meant on screen. Applying
them one at a time and letting each shift the next is the obvious implementation
and it is wrong: deleting #2 would silently turn a later "replace #5" into a
replace of what used to be #6.

Index space matches ``expand_with_provenance()``: explicit ``blocks`` occupy
``0..len(blocks)-1``, then ``operations`` continue from there. That is the same
space annotations carry, so an ``op_index`` can be passed straight through
without translation.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from .schema import BlockData, MinecraftStructure, Operation

# Validates a patch payload as either an operation or an explicit block, so a
# caller can replace like with like without saying which it meant.
_OPERATION_ADAPTER: TypeAdapter = TypeAdapter(Operation)
_BLOCK_ADAPTER: TypeAdapter = TypeAdapter(BlockData)


class Patch(BaseModel):
    """One edit against the pre-patch index space."""

    index: int = Field(..., ge=0)
    action: Literal["replace", "insert", "delete"]
    # Required for replace/insert, ignored for delete. Left loose here and
    # validated against the real union in _coerce, so the error names the actual
    # problem with the operation instead of "did not match any variant".
    operation: Optional[dict] = None


class PatchError(ValueError):
    """A patch that cannot be applied. Message is meant for Claude to read."""


def _coerce(payload: dict, position: int) -> Tuple[str, object]:
    """Validate a patch payload as an operation or an explicit block.

    Returns ``("operation"|"block", model)``. Tries the operation union first
    because that is what callers should almost always be sending.
    """
    if not isinstance(payload, dict):
        raise PatchError(f"patch {position}: operation must be a JSON object")

    if "op" in payload:
        try:
            return "operation", _OPERATION_ADAPTER.validate_python(payload)
        except ValidationError as error:
            raise PatchError(
                f"patch {position}: invalid operation - {error}"
            ) from error

    try:
        return "block", _BLOCK_ADAPTER.validate_python(payload)
    except ValidationError as error:
        raise PatchError(
            f"patch {position}: not a valid operation or block. An operation "
            f"needs an \"op\" field naming its kind - {error}"
        ) from error


def apply_patches(
    structure: MinecraftStructure,
    patches: Sequence[Union[Patch, dict]],
) -> MinecraftStructure:
    """Return a new structure with ``patches`` applied. Never mutates the input.

    Semantics, all resolved against the *original* indices:

    - ``delete`` — drop the entry at ``index``.
    - ``replace`` — substitute the entry at ``index``.
    - ``insert`` — place the new entry immediately *before* ``index``;
      ``index == total`` appends.

    Note that explicit ``blocks`` always apply before ``operations``, in the
    original structure and in the result. So inserting an operation at a *block*
    index cannot interleave it between blocks; it lands at the front of the
    operation list, which is the closest honest approximation. Builds that use
    operations throughout — what the style guide asks for — never meet this.
    """
    parsed: List[Patch] = []
    for position, patch in enumerate(patches):
        if isinstance(patch, Patch):
            parsed.append(patch)
            continue
        try:
            parsed.append(Patch.model_validate(patch))
        except ValidationError as error:
            raise PatchError(f"patch {position}: {error}") from error

    total = len(structure.blocks) + len(structure.operations)

    deletes: set = set()
    replacements: Dict[int, Tuple[str, object]] = {}
    inserts: Dict[int, List[Tuple[str, object]]] = {}

    for position, patch in enumerate(parsed):
        if patch.action == "insert":
            # One past the end is the append position, so this bound is looser
            # than the others by exactly one.
            if patch.index > total:
                raise PatchError(
                    f"patch {position}: cannot insert at {patch.index}; "
                    f"the structure has {total} entries (0..{total} allowed)"
                )
        elif patch.index >= total:
            raise PatchError(
                f"patch {position}: no entry at index {patch.index}; "
                f"the structure has {total} "
                f"({'0..' + str(total - 1) if total else 'none'})"
            )

        if patch.action == "delete":
            deletes.add(patch.index)
            continue

        if patch.operation is None:
            raise PatchError(
                f"patch {position}: \"{patch.action}\" needs an operation"
            )
        entry = _coerce(patch.operation, position)

        if patch.action == "replace":
            if patch.index in replacements:
                raise PatchError(
                    f"patch {position}: index {patch.index} is replaced twice"
                )
            replacements[patch.index] = entry
        else:
            inserts.setdefault(patch.index, []).append(entry)

    conflict = deletes & replacements.keys()
    if conflict:
        raise PatchError(
            f"index {sorted(conflict)[0]} is both deleted and replaced; "
            "pick one"
        )

    # Rebuild by walking the original positions, so nothing shifts underneath.
    entries: List[Tuple[str, object]] = (
        [("block", b) for b in structure.blocks]
        + [("operation", o) for o in structure.operations]
    )

    result: List[Tuple[str, object]] = []
    for index, entry in enumerate(entries):
        result.extend(inserts.get(index, ()))
        if index in deletes:
            continue
        result.append(replacements.get(index, entry))
    result.extend(inserts.get(total, ()))

    blocks = [model for kind, model in result if kind == "block"]
    operations = [model for kind, model in result if kind == "operation"]

    if not blocks and not operations:
        raise PatchError(
            "those patches would leave the structure empty; a build needs at "
            "least one block or operation"
        )

    # Rebuilt through the model so the result is validated exactly as an
    # incoming structure would be.
    patched = MinecraftStructure(
        name=structure.name,
        description=structure.description,
        # Recomputed on demand by calculate_size(); carrying the old value over
        # would describe the pre-patch bounds.
        size=None,
        blocks=blocks,       # type: ignore[arg-type]
        operations=operations,  # type: ignore[arg-type]
    )
    # Checked here rather than left to the first expand(): a patch can raise the
    # voxel count (one replaced cuboid is enough), and failing at patch time
    # means the error arrives while the offending patch is still the subject.
    patched.check_limits()
    return patched
