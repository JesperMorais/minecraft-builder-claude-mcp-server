# Measuring build quality

Everything in this repo that aims at build quality does so by argument. The
style guide asserts that a 50/30/20 palette looks better. `lint.py` asserts that
an unbroken flat wall is a fault. The visual critique asserts that a picture is
worth answering. All three are probably right, and none of them can tell you
whether editing one of them made the *output* better — which is the only
question that matters when you are deciding whether to keep a change.

The eval harness answers it: render a fixed set of builds, score them against a
fixed rubric, and compare the number to the last time you asked.

## What it does and does not do

It does **not** generate the builds. A model does that, through the same MCP
tools a user would drive, and drops the resulting JSON in a directory. That
split is deliberate — what gets measured is the whole pipeline the model is
actually running inside (guide, prompts, tools, linter, critique loop), not a
reimplementation of it that would drift and quietly measure nothing.

So a run is three steps: generate, render, score.

## 1. Generate the builds

```bash
python -m minecraft_builder.evals --list
```

That prints fourteen prompts, each with an id and a note on what it is there to
catch. Ask a model to build each one the way a user would, and save the
structure JSON as `<id>.json` — `medieval_cottage.json`, `castle_gatehouse.json`
— all in one directory. Filename stem to benchmark id is the only convention.

A partial set is fine. Missing builds are reported and excluded from the means,
never scored zero, so a run over four builds is honest about being a run over
four builds.

`examples/eval/` holds one finished build so you can try the next two steps
without generating anything.

## 2. Render

```bash
pip install -e ".[render]" && playwright install chromium
python -m minecraft_builder.evals --structures examples/eval
```

This writes a timestamped run folder under `evals/` (gitignored):

```
evals/2026-07-28T11-19-52/
├── report.md      # scores table, per-build renders and notes
├── scores.json    # the same numbers, for comparing runs
└── images/        # three renders per build
```

Without a judge the score table is empty and `report.md` ends with a *Scoring
this run* section. That bundle is the manual path: open it, look at the renders,
fill the table in against [the rubric](../src/minecraft_builder/data/build_rubric.md).

## 3. Score automatically (optional, costs money)

```bash
pip install -e ".[eval]"
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login
python -m minecraft_builder.evals --structures builds/ --judge
```

`--judge` is opt-in rather than the default because it spends real money: one
API request per build, each carrying every render of that build. A harness that
billed you for existing would be run once and then avoided.

The judge sees the rubric and the renders, and nothing else — not the structure
JSON, not the operation list, not the linter's verdict. A judge that could read
the source would be scoring the *description* of the build, and would reward a
model for claiming a plinth it never rendered.

Useful flags: `--judge-model` (default `claude-sonnet-5`), `--views` (default 3),
`--width` / `--height`, `--output`.

## Reading a run

A single number means nothing. `6.2` is not a grade; it is a reading. What the
harness is for is the *difference* between two readings taken the same way:

```
before a style-guide change   mean 6.2   (silhouette 5.1, depth 4.8, …)
after                         mean 7.0   (silhouette 6.4, depth 6.9, …)
```

Two runs are only comparable if they asked the same questions of the same judge,
so `scores.json` records the benchmark set's `benchmark_fingerprint` and the
`judge_model` alongside the numbers. If either differs between two runs, the
comparison is not one.

Watch the per-dimension row rather than only the total — a change that lifts
`depth` while dropping `roofline` is a real finding that a moved mean hides. And
`overall` is judged holistically, not averaged from the other five, so a gap
between `overall` and the mean of the rest is itself interesting: it usually
means the build passes its parts and fails as a whole.

## Changing the rubric

`data/build_rubric.md` is the source of truth. The dimension list is parsed out
of its `### name — summary` headings, and the same text is handed to the judge
verbatim, so the document a human scores against and the instructions the judge
follows cannot drift apart. Adding a dimension is a documentation edit.

Changing it invalidates comparison with older runs, the same as changing the
benchmark set. That is the cost of the rubric being editable, and it is the
right trade — a rubric nobody may touch is a rubric that stops describing what
you care about.
