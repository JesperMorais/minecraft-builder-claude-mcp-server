"""Turning a run into something you can read and something you can diff.

Two artefacts, because they answer different questions. ``report.md`` is for a
person deciding whether a change helped; ``scores.json`` is for a later run
comparing itself against this one, and for anyone who wants the numbers without
re-parsing prose.

Both are written even when nothing was scored. A render bundle with an empty
score table is exactly what a manual scoring pass needs, and printing the same
report either way means the unscored path is not a second, less-tested format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .rubric import dimensions
from .results import BuildResult, Run

# What an unscored cell looks like. A middot rather than a blank so a column of
# them is visible as "nobody scored this" instead of reading as a broken table.
UNSCORED = "·"


def scores_payload(run: Run) -> Dict[str, Any]:
    """The machine-readable half. Key order is fixed so two runs diff cleanly."""
    totals = run.totals
    return {
        "started_at": run.started_at,
        "benchmark_set": run.benchmark_set,
        "benchmark_fingerprint": run.benchmark_fingerprint,
        "judged": run.judged,
        "judge_model": run.judge_model,
        "dimensions": [dimension.name for dimension in dimensions()],
        "totals": {
            "mean": totals.mean,
            "per_dimension": totals.per_dimension,
            "scored": totals.scored,
            "unscored": totals.unscored,
        },
        "builds": [_build_payload(run, result) for result in run.results],
    }


def _build_payload(run: Run, result: BuildResult) -> Dict[str, Any]:
    return {
        "id": result.id,
        "prompt": result.prompt,
        "structure": _relative(run, result.structure),
        "images": [_relative(run, image) for image in result.images],
        "scores": result.scores,
        "mean": result.mean,
        "notes": result.notes,
        "error": result.error,
    }


def _relative(run: Run, path: Any) -> str:
    """Paths relative to the run folder, so the folder can be moved or shared."""
    if path is None:
        return ""
    try:
        return str(Path(path).relative_to(run.directory))
    except ValueError:
        return str(path)


def markdown_report(run: Run) -> str:
    """The human-readable half."""
    totals = run.totals
    names = [dimension.name for dimension in dimensions()]

    lines: List[str] = [
        f"# Build quality — {run.started_at}",
        "",
        f"- Benchmark set: **{run.benchmark_set}** (`{run.benchmark_fingerprint}`), "
        f"{len(run.results)} prompt(s)",
    ]
    if run.judged:
        lines.append(f"- Judged by `{run.judge_model}`")
        lines.append(
            f"- **Mean {totals.mean} / 10** over {totals.scored} build(s)"
            + (f", {totals.unscored} unscored" if totals.unscored else "")
        )
    else:
        lines.append("- **Not scored** — renders only, see *Scoring this run* below")
    lines.extend(["", "## Scores", ""])

    header = "| Build | " + " | ".join(names) + " | mean |"
    lines.append(header)
    lines.append("|" + "---|" * (len(names) + 2))
    for result in run.results:
        cells = [str(result.scores.get(name, UNSCORED)) for name in names]
        mean = result.mean if result.mean is not None else UNSCORED
        lines.append(f"| {result.id} | " + " | ".join(cells) + f" | {mean} |")

    average_cells = [
        str(totals.per_dimension.get(name, UNSCORED)) for name in names
    ]
    overall = totals.mean if totals.mean is not None else UNSCORED
    lines.append(
        "| **mean** | " + " | ".join(f"**{cell}**" for cell in average_cells)
        + f" | **{overall}** |"
    )

    lines.extend(["", "## Builds", ""])
    for result in run.results:
        lines.extend(_build_section(run, result))

    if not run.judged:
        lines.extend(_scoring_instructions())
    return "\n".join(lines) + "\n"


def _build_section(run: Run, result: BuildResult) -> List[str]:
    heading = result.id if result.mean is None else f"{result.id} — {result.mean}"
    lines = [f"### {heading}", "", f"> {result.prompt}", ""]
    if result.error:
        lines.extend([f"**Not rendered:** {result.error}", ""])
        return lines
    for image in result.images:
        relative = _relative(run, image)
        lines.append(f"![{result.id}]({relative})")
    lines.append("")
    if result.notes:
        lines.extend([result.notes, ""])
    return lines


def _scoring_instructions() -> List[str]:
    """What to do with an unjudged bundle.

    Named commands rather than a description of them: this section exists
    precisely because the reader has just discovered the thing they wanted did
    not happen, and the useful response is the line that fixes it.
    """
    return [
        "## Scoring this run",
        "",
        "Nothing was scored. The renders above are the bundle; fill the score",
        "table in by hand against `data/build_rubric.md`, or score it",
        "automatically with a vision model.",
        "",
        "To enable automatic judging, install the extra, make credentials",
        "available, and re-run with `--judge`:",
        "",
        "```",
        'pip install "minecraft-builder-mcp[eval]"',
        "export ANTHROPIC_API_KEY=sk-ant-...   # or: ant auth login",
        "python -m minecraft_builder.evals --structures <dir> --judge",
        "```",
        "",
        "Judging is opt-in because it costs money: one request per build, each",
        "carrying every render of that build.",
    ]


def write_run(run: Run) -> Dict[str, Path]:
    """Write both artefacts into the run folder; returns where they went."""
    run.directory.mkdir(parents=True, exist_ok=True)
    report = run.directory / "report.md"
    scores = run.directory / "scores.json"
    report.write_text(markdown_report(run), encoding="utf-8")
    scores.write_text(
        json.dumps(scores_payload(run), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return {"report": report, "scores": scores}
