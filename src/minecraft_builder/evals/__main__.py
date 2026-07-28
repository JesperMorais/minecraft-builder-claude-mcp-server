"""Run the build-quality benchmark.

    python -m minecraft_builder.evals --structures builds/            # render only
    python -m minecraft_builder.evals --structures builds/ --judge    # render and score
    python -m minecraft_builder.evals --list                          # print the prompts

Give a model the prompts from ``--list``, have it build each one through the
usual tools, and save the structure JSON as ``<id>.json`` in one directory.
Point this at that directory and it renders every build and writes a run folder
with the images, a report and the scores.

``--judge`` is opt-in because it spends money: one API request per build,
carrying every render of it. Without it you get the same report with an empty
score table, ready to fill in by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..web.render import RenderError
from .benchmarks import load_benchmarks
from .judge import JUDGE_MODEL, JudgeError, build_client
from .runner import (
    DEFAULT_OUTPUT_ROOT,
    EVAL_HEIGHT,
    EVAL_VIEWS,
    EVAL_WIDTH,
    missing_structures,
    run_eval,
)


def _print_benchmarks() -> None:
    for benchmark in load_benchmarks():
        print(f"{benchmark.id}\n  {benchmark.prompt}\n  ({benchmark.stresses})\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m minecraft_builder.evals",
        description="Render and score the build-quality benchmark set.",
    )
    parser.add_argument("--list", action="store_true",
                        help="Print the benchmark prompts and exit.")
    parser.add_argument("--structures", type=Path,
                        help="Directory of structure JSON files, named <benchmark-id>.json.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT,
                        help=f"Where to write the run folder. Default {DEFAULT_OUTPUT_ROOT}/.")
    parser.add_argument("--judge", action="store_true",
                        help="Score the renders with a vision model. Costs money.")
    parser.add_argument("--judge-model", default=JUDGE_MODEL,
                        help=f"Model to score with. Default {JUDGE_MODEL}.")
    parser.add_argument("--views", type=int, default=EVAL_VIEWS,
                        help=f"Renders per build. Default {EVAL_VIEWS}.")
    parser.add_argument("--width", type=int, default=EVAL_WIDTH)
    parser.add_argument("--height", type=int, default=EVAL_HEIGHT)
    args = parser.parse_args(argv)

    if args.list:
        _print_benchmarks()
        return 0
    if args.structures is None:
        parser.error("--structures is required (or use --list)")

    missing = missing_structures(args.structures)
    if missing:
        # A warning, not an error: a partial run is a legitimate way to work,
        # and the report records exactly which rows were skipped.
        print(f"No structure for {len(missing)} benchmark(s): {', '.join(missing)}",
              file=sys.stderr)

    client = None
    if args.judge:
        try:
            client = build_client()
        except JudgeError as error:
            print(error, file=sys.stderr)
            return 1
        total = len(load_benchmarks()) - len(missing)
        print(f"Scoring {total} build(s) with {args.judge_model} — one request each.")

    try:
        run = run_eval(
            args.structures,
            output_root=args.output,
            judge_client=client,
            judge_model=args.judge_model,
            views=args.views,
            width=args.width,
            height=args.height,
        )
    except RenderError as error:
        print(error, file=sys.stderr)
        return 1

    totals = run.totals
    print(f"\nRun written to {run.directory}")
    if run.judged and totals.mean is not None:
        print(f"Mean {totals.mean} / 10 over {totals.scored} build(s)")
    else:
        print("Renders only — see 'Scoring this run' in report.md")
    if totals.unscored:
        print(f"{totals.unscored} build(s) not scored; see the report for why")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
