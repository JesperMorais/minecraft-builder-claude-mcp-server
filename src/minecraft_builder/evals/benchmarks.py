"""The benchmark prompt set.

Kept in ``data/benchmarks.json`` rather than in Python so it travels with an
installed package and can be edited without touching code — the same reasoning
that puts the style guide there.

Order is load order and is never sorted. Two runs of the same set have to line
up row for row in a report, and a set whose order depended on a dict or a
filesystem listing would reshuffle itself between runs for no reason.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Tuple

BENCHMARKS_FILE = "benchmarks.json"


@dataclass(frozen=True)
class Benchmark:
    """One prompt in the set.

    ``stresses`` is what this prompt is here to catch. It is not used by any
    code — it exists so that whoever reads a bad score knows what the prompt was
    supposed to expose, and so that nobody removes a prompt for looking
    redundant when it is the only one covering, say, a roofless build.
    """

    id: str
    prompt: str
    stresses: str


@lru_cache(maxsize=1)
def _raw() -> dict:
    text = (
        resources.files("minecraft_builder.data")
        .joinpath(BENCHMARKS_FILE)
        .read_text(encoding="utf-8")
    )
    return {"text": text, "data": json.loads(text)}


@lru_cache(maxsize=1)
def load_benchmarks() -> Tuple[Benchmark, ...]:
    """The benchmark set, in file order."""
    data = _raw()["data"]
    return tuple(
        Benchmark(id=item["id"], prompt=item["prompt"], stresses=item.get("stresses", ""))
        for item in data["prompts"]
    )


def benchmark_set_name() -> str:
    return str(_raw()["data"]["name"])


def benchmark_fingerprint() -> str:
    """Short digest of the benchmark file.

    Two runs are only comparable if they asked the same questions. Recording the
    digest is what makes a changed prompt set visible in a diff of two reports,
    rather than showing up as an unexplained score movement.
    """
    return hashlib.sha256(_raw()["text"].encode("utf-8")).hexdigest()[:12]
