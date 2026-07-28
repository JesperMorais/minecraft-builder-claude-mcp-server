"""Running the benchmark set: find the structures, render them, score them.

The harness does not generate the builds. A model does that, through the same
MCP tools a user would drive, and drops the resulting JSON in a directory. That
split is the point — what gets measured is the whole pipeline the model actually
runs inside (guide, prompts, tools, linter, critique loop), not a
reimplementation of it that would drift from the real thing and quietly measure
nothing.

Every failure is a row, never the run. A missing structure, an unrenderable
build, a judge that rate-limits halfway through: each lands in one
``BuildResult.error`` and the rest of the set carries on, because a set of
thirteen scores plus a named gap is a usable measurement and a traceback is not.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence

from ..schema import MinecraftStructure
from ..web.render import RenderError, render_views, select_views
from .benchmarks import Benchmark, benchmark_fingerprint, benchmark_set_name, load_benchmarks
from .judge import JUDGE_MODEL, JudgeError, judge_build
from .report import write_run
from .results import BuildResult, Run

# Where runs pile up, relative to wherever the harness is invoked. Gitignored:
# a run is a few megabytes of PNG and belongs to whoever produced it.
DEFAULT_OUTPUT_ROOT = Path("evals")

# Three angles rather than the render tool's five. The prefix is ordered so
# three covers the isometric the viewer opens at, the level elevation and the
# opposite corner — enough to score every rubric dimension, and it is the
# difference between a judged run costing three images per build and five.
EVAL_VIEWS = 3

# Smaller than an interactive render. A judge reads shape, palette and relief,
# none of which need 800x600, and the whole set travels in one request per build.
EVAL_WIDTH = 640
EVAL_HEIGHT = 480

# Colons are legal in a POSIX filename and not on Windows, and this suite runs
# on both.
_TIMESTAMP = "%Y-%m-%dT%H-%M-%S"


def structure_path(structures_dir: Path, benchmark: Benchmark) -> Path:
    """Where a benchmark's structure is expected to be.

    Matching is by filename stem against the benchmark id — the one convention
    a caller has to follow, and the one the CLI prints when it cannot find a
    file.
    """
    return Path(structures_dir) / f"{benchmark.id}.json"


def load_structure(path: Path) -> MinecraftStructure:
    return MinecraftStructure(**json.loads(path.read_text(encoding="utf-8")))


def run_eval(
    structures_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    benchmarks: Optional[Sequence[Benchmark]] = None,
    judge_client: Any = None,
    judge_model: str = JUDGE_MODEL,
    views: int = EVAL_VIEWS,
    width: int = EVAL_WIDTH,
    height: int = EVAL_HEIGHT,
) -> Run:
    """Render and optionally score every benchmark; write the run and return it.

    ``judge_client`` is the switch: without one the run stops after rendering
    and writes a bundle to score by hand. Passing a client in rather than
    building one here keeps the API out of the orchestration and lets the whole
    path be tested with a stand-in.
    """
    chosen = list(benchmarks) if benchmarks is not None else list(load_benchmarks())
    started = time.strftime(_TIMESTAMP)
    directory = Path(output_root) / started
    images_dir = directory / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    run = Run(
        started_at=started,
        directory=directory,
        benchmark_set=benchmark_set_name(),
        benchmark_fingerprint=benchmark_fingerprint(),
        results=[],
        judged=judge_client is not None,
        judge_model=judge_model if judge_client is not None else "",
    )

    angles = select_views(count=views)
    for benchmark in chosen:
        result = _run_one(
            benchmark, structures_dir, images_dir, angles, width, height,
            judge_client, judge_model,
        )
        run.results.append(result)

    write_run(run)
    return run


def _run_one(
    benchmark: Benchmark,
    structures_dir: Path,
    images_dir: Path,
    angles: Sequence[Any],
    width: int,
    height: int,
    judge_client: Any,
    judge_model: str,
) -> BuildResult:
    """One benchmark, start to finish, absorbing every failure into the row."""
    result = BuildResult(id=benchmark.id, prompt=benchmark.prompt)
    path = structure_path(structures_dir, benchmark)
    if not path.exists():
        result.error = f"no structure at {path}"
        return result
    result.structure = path

    try:
        structure = load_structure(path)
    except Exception as error:
        result.error = f"could not load the structure: {type(error).__name__}: {error}"
        return result

    try:
        rendered = render_views(
            structure, images_dir, views=list(angles),
            width=width, height=height, stem=benchmark.id,
        )
    except RenderError as error:
        result.error = str(error)
        return result
    except Exception as error:
        result.error = f"render failed: {type(error).__name__}: {error}"
        return result

    result.images = [shot.path for shot in rendered]
    if judge_client is None:
        return result

    try:
        result.scores, result.notes = judge_build(
            judge_client, benchmark.prompt, [shot.png for shot in rendered], judge_model
        )
    except JudgeError as error:
        result.error = str(error)
    return result


def missing_structures(structures_dir: Path, benchmarks: Optional[Sequence[Benchmark]] = None) -> List[str]:
    """Benchmark ids with no structure file, so the CLI can say so up front.

    Checked before anything is rendered: discovering after ten minutes of
    browser work that half the set was never generated is a bad way to find out
    the directory was wrong.
    """
    chosen = list(benchmarks) if benchmarks is not None else list(load_benchmarks())
    return [b.id for b in chosen if not structure_path(structures_dir, b).exists()]
