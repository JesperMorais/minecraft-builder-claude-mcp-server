"""The scoring rubric: the document, its dimensions, and the judge's reply shape.

``data/build_rubric.md`` is the single source of truth. The dimension list is
*parsed out of it* rather than declared here, and the same text is handed to the
judge verbatim, so the document a human scores against and the instructions the
judge follows cannot disagree. Adding a dimension is a documentation edit.

That parse is deliberately narrow — one heading form, ``### name — summary`` —
because a loose parser would happily accept a rubric it had half understood and
score builds against a silently truncated dimension list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Dict, Mapping, Tuple

RUBRIC_FILE = "build_rubric.md"

SCORE_MIN = 1
SCORE_MAX = 10

# "### silhouette — the outline against the sky". The em dash is required: it is
# what separates a dimension heading from any other third-level heading the
# document might grow.
_DIMENSION_HEADING = re.compile(r"^### (?P<name>[a-z_]+) — (?P<summary>.+)$", re.MULTILINE)

# Room for a sentence or two of justification per build. Long enough to be worth
# reading in a report, short enough that fourteen of them stay skimmable.
MAX_NOTE_CHARS = 600


class RubricError(ValueError):
    """The rubric document or a judge's reply could not be used as scores."""


@dataclass(frozen=True)
class Dimension:
    """One scored axis, named and summarised by its heading in the document."""

    name: str
    summary: str


@lru_cache(maxsize=1)
def load_rubric() -> str:
    """The rubric document, as markdown.

    Read as UTF-8 explicitly: it contains em dashes and en dashes that would
    fail under a Windows default codepage, the same trap the style guide hit.
    """
    return (
        resources.files("minecraft_builder.data")
        .joinpath(RUBRIC_FILE)
        .read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def dimensions() -> Tuple[Dimension, ...]:
    """The scored dimensions, in document order."""
    found = tuple(
        Dimension(name=match["name"], summary=match["summary"].strip())
        for match in _DIMENSION_HEADING.finditer(load_rubric())
    )
    if not found:
        raise RubricError(
            f"No dimensions found in {RUBRIC_FILE}. Each one needs a heading of "
            "the form '### name — summary'."
        )
    names = [dimension.name for dimension in found]
    if len(set(names)) != len(names):
        raise RubricError(f"Duplicate dimension names in {RUBRIC_FILE}: {names}")
    return found


def dimension_names() -> Tuple[str, ...]:
    return tuple(dimension.name for dimension in dimensions())


def score_schema() -> Dict[str, Any]:
    """The JSON schema the judge's reply must satisfy.

    Derived from the parsed dimensions so the rubric document stays the only
    place a dimension is declared.

    No ``minimum``/``maximum`` on the scores: structured outputs reject numeric
    constraints, so the 1-10 bound is enforced by ``parse_scores`` on the way
    back instead. The schema guarantees the shape; this module guarantees the
    range.
    """
    names = dimension_names()
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "properties": {name: {"type": "integer"} for name in names},
                "required": list(names),
                "additionalProperties": False,
            },
            "notes": {
                "type": "string",
                "description": (
                    "One or two sentences naming the single worst thing about "
                    "this build and the single best."
                ),
            },
        },
        "required": ["scores", "notes"],
        "additionalProperties": False,
    }


def parse_scores(payload: Mapping[str, Any]) -> Tuple[Dict[str, int], str]:
    """Validate a judge reply into scores and a note.

    Structured outputs guarantee the keys, not the values, and this also runs on
    hand-written JSON from a manual scoring pass. A partially valid reply is
    rejected outright rather than filled in: a missing dimension silently scored
    zero would move a run's mean without anything saying so.
    """
    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, Mapping):
        raise RubricError("Reply has no 'scores' object.")

    scores: Dict[str, int] = {}
    for name in dimension_names():
        if name not in raw_scores:
            raise RubricError(f"Reply is missing a score for '{name}'.")
        value = raw_scores[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RubricError(f"Score for '{name}' is not a number: {value!r}")
        if not SCORE_MIN <= value <= SCORE_MAX:
            raise RubricError(
                f"Score for '{name}' is {value}; it must be between "
                f"{SCORE_MIN} and {SCORE_MAX}."
            )
        scores[name] = int(round(value))

    unknown = set(raw_scores) - set(scores)
    if unknown:
        raise RubricError(f"Reply scores dimensions the rubric does not define: {sorted(unknown)}")

    note = str(payload.get("notes", "")).strip()
    return scores, note[:MAX_NOTE_CHARS]
