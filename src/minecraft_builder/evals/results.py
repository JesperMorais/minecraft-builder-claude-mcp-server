"""What a run produced, and how the numbers combine.

Kept apart from both the rubric and the report because it is the one piece two
runs are compared through: the report is a rendering of it, and a future
regression check would read it rather than re-parse markdown.

The arithmetic is deliberately unclever. Means only, no weighting, no
normalisation, missing builds excluded rather than scored zero. A weighted score
would need a defence of the weights, and the whole point is that two runs of the
same set are comparable — which mean-of-means already gives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .rubric import dimension_names


@dataclass
class BuildResult:
    """One benchmark prompt's outcome.

    Every failure mode is a state of this object rather than an exception, so a
    missing structure or a judge error costs one row of the report instead of
    the run.
    """

    id: str
    prompt: str
    structure: Optional[Path] = None
    images: List[Path] = field(default_factory=list)
    scores: Dict[str, int] = field(default_factory=dict)
    notes: str = ""
    error: str = ""

    @property
    def scored(self) -> bool:
        return bool(self.scores)

    @property
    def mean(self) -> Optional[float]:
        if not self.scores:
            return None
        return round(sum(self.scores.values()) / len(self.scores), 2)


@dataclass(frozen=True)
class Totals:
    """A run's headline numbers."""

    per_dimension: Dict[str, float]
    mean: Optional[float]
    scored: int
    unscored: int


@dataclass
class Run:
    """Everything one invocation produced."""

    started_at: str
    directory: Path
    benchmark_set: str
    benchmark_fingerprint: str
    results: List[BuildResult]
    judged: bool = False
    judge_model: str = ""

    @property
    def totals(self) -> Totals:
        return aggregate(self.results)


def aggregate(results: Sequence[BuildResult]) -> Totals:
    """Mean per dimension and overall, over the builds that were scored.

    Unscored builds are excluded, not counted as zero — a build nobody could
    render is a gap in the measurement, and folding it in as a zero would report
    a quality regression where there was a missing file. The counts are returned
    alongside so a mean over three builds is never mistaken for one over
    fourteen.
    """
    scored = [result for result in results if result.scored]
    per_dimension: Dict[str, float] = {}
    for name in dimension_names():
        values = [result.scores[name] for result in scored if name in result.scores]
        if values:
            per_dimension[name] = round(sum(values) / len(values), 2)

    mean = (
        round(sum(per_dimension.values()) / len(per_dimension), 2)
        if per_dimension
        else None
    )
    return Totals(
        per_dimension=per_dimension,
        mean=mean,
        scored=len(scored),
        unscored=len(results) - len(scored),
    )
