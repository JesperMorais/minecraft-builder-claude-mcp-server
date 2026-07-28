"""Tests for the eval harness: rubric parsing, aggregation, reports, plumbing.

Everything here runs without a browser, without a network and without an API
key. The harness exists to make quality changes measurable, so its own
arithmetic has to be trustworthy — a scoring bug would read as a build-quality
movement, which is exactly the conclusion the harness is supposed to license.

The judge is exercised against a stand-in client rather than the real API. The
request it builds is worth checking (the rubric has to reach the model, the
images have to be in the user turn); paying for a real judged run to learn that
is not.
"""

import json
from pathlib import Path

import pytest

from minecraft_builder.evals import benchmarks, judge, report, rubric, runner
from minecraft_builder.evals.judge import JudgeError, judge_build
from minecraft_builder.evals.results import BuildResult, Run, Totals, aggregate
from minecraft_builder.evals.rubric import RubricError, dimension_names, parse_scores


def _scores(**overrides):
    """A complete, valid score set, with any dimension overridable."""
    values = {name: 5 for name in dimension_names()}
    values.update(overrides)
    return values


def _result(build_id="cottage", scored=True, **overrides):
    return BuildResult(
        id=build_id,
        prompt="Build a cottage.",
        scores=_scores(**overrides) if scored else {},
    )


def _run(tmp_path, results, judged=False):
    return Run(
        started_at="2026-07-28T12-00-00",
        directory=tmp_path,
        benchmark_set="test-set",
        benchmark_fingerprint="abc123abc123",
        results=results,
        judged=judged,
        judge_model=judge.JUDGE_MODEL if judged else "",
    )


# --------------------------------------------------------------------------- #
# The rubric document
# --------------------------------------------------------------------------- #

def test_the_six_dimensions_are_parsed_from_the_document():
    assert dimension_names() == (
        "silhouette", "palette", "depth", "roofline", "detailing", "overall",
    )


def test_every_dimension_carries_its_summary():
    # The summary is what a judge and a human scorer read; a heading that parsed
    # but explained nothing would score builds against a bare word.
    for dimension in rubric.dimensions():
        assert dimension.summary
        assert not dimension.summary.startswith("—")


def test_the_document_is_the_only_place_dimensions_are_declared(monkeypatch):
    """Adding a dimension has to be a documentation edit, not a code edit."""
    monkeypatch.setattr(rubric, "load_rubric", lambda: (
        "## Dimensions\n\n### massing — how the volumes stack\nprose\n"
    ))
    rubric.dimensions.cache_clear()
    try:
        assert dimension_names() == ("massing",)
        assert rubric.score_schema()["properties"]["scores"]["required"] == ["massing"]
    finally:
        rubric.dimensions.cache_clear()


def test_a_rubric_with_no_dimensions_is_refused(monkeypatch):
    # Silently scoring against an empty dimension list would produce a run whose
    # mean is None and whose report looks merely empty.
    monkeypatch.setattr(rubric, "load_rubric", lambda: "# Rubric\n\nNo headings here.\n")
    rubric.dimensions.cache_clear()
    try:
        with pytest.raises(RubricError, match="No dimensions found"):
            rubric.dimensions()
    finally:
        rubric.dimensions.cache_clear()


def test_duplicate_dimensions_are_refused(monkeypatch):
    monkeypatch.setattr(rubric, "load_rubric", lambda: (
        "### depth — one\ntext\n\n### depth — two\ntext\n"
    ))
    rubric.dimensions.cache_clear()
    try:
        with pytest.raises(RubricError, match="Duplicate dimension"):
            rubric.dimensions()
    finally:
        rubric.dimensions.cache_clear()


def test_the_schema_pins_the_shape_and_nothing_else():
    schema = rubric.score_schema()
    scores = schema["properties"]["scores"]
    assert scores["required"] == list(dimension_names())
    assert scores["additionalProperties"] is False
    assert schema["additionalProperties"] is False
    # Structured outputs reject numeric constraints, so the 1-10 bound cannot
    # live here — parse_scores enforces it instead. If this ever passes, the
    # range check on the way back has become redundant and should be revisited.
    assert all("minimum" not in field for field in scores["properties"].values())


# --------------------------------------------------------------------------- #
# Reading a reply
# --------------------------------------------------------------------------- #

def test_a_complete_reply_parses():
    scores, note = parse_scores({"scores": _scores(depth=8), "notes": "Good roof."})
    assert scores["depth"] == 8
    assert note == "Good roof."


def test_a_missing_dimension_is_refused():
    """Filling it in would move the run's mean with nothing saying so."""
    partial = _scores()
    del partial["palette"]
    with pytest.raises(RubricError, match="missing a score for 'palette'"):
        parse_scores({"scores": partial})


@pytest.mark.parametrize("value", [0, 11, -3, 100])
def test_out_of_range_scores_are_refused(value):
    with pytest.raises(RubricError, match="between 1 and 10"):
        parse_scores({"scores": _scores(depth=value)})


def test_a_boolean_is_not_a_score():
    # True is an int in Python, so a naive isinstance check scores it as 1.
    with pytest.raises(RubricError, match="not a number"):
        parse_scores({"scores": _scores(depth=True)})


def test_a_string_score_is_refused():
    with pytest.raises(RubricError, match="not a number"):
        parse_scores({"scores": _scores(depth="excellent")})


def test_scores_the_rubric_does_not_define_are_refused():
    # Usually means the judge is answering an older rubric than the one loaded.
    with pytest.raises(RubricError, match="does not define"):
        parse_scores({"scores": {**_scores(), "vibes": 9}})


def test_a_reply_with_no_scores_is_refused():
    with pytest.raises(RubricError, match="no 'scores' object"):
        parse_scores({"notes": "looks fine"})


def test_a_long_note_is_truncated_not_rejected():
    # The note is commentary; losing its tail costs nothing, losing the scores
    # with it would cost the row.
    scores, note = parse_scores({"scores": _scores(), "notes": "x" * 5000})
    assert scores
    assert len(note) == rubric.MAX_NOTE_CHARS


# --------------------------------------------------------------------------- #
# The benchmark set
# --------------------------------------------------------------------------- #

def test_the_benchmark_set_loads():
    prompts = benchmarks.load_benchmarks()
    assert len(prompts) >= 12
    assert all(prompt.id and prompt.prompt for prompt in prompts)


def test_benchmark_ids_are_unique():
    # Ids are filenames and report rows; a duplicate would silently overwrite.
    ids = [prompt.id for prompt in benchmarks.load_benchmarks()]
    assert len(set(ids)) == len(ids)


def test_benchmark_ids_are_safe_filenames():
    for prompt in benchmarks.load_benchmarks():
        assert prompt.id.replace("_", "").isalnum(), prompt.id


def test_every_benchmark_says_what_it_is_for():
    # Otherwise the next person deletes the one prompt covering roofless builds.
    assert all(prompt.stresses for prompt in benchmarks.load_benchmarks())


def test_the_fingerprint_identifies_the_prompt_set():
    # Two runs are only comparable if they asked the same questions.
    first = benchmarks.benchmark_fingerprint()
    assert len(first) == 12
    assert first == benchmarks.benchmark_fingerprint()


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def test_a_dimension_mean_is_the_mean_of_that_dimension():
    totals = aggregate([_result("a", depth=4), _result("b", depth=8)])
    assert totals.per_dimension["depth"] == 6.0
    assert totals.scored == 2


def test_unscored_builds_are_excluded_not_zeroed():
    """A build nobody could render is a gap, not a quality regression."""
    scored_only = aggregate([_result("a", depth=8)])
    with_a_gap = aggregate([_result("a", depth=8), _result("b", scored=False)])

    assert with_a_gap.per_dimension == scored_only.per_dimension
    assert with_a_gap.scored == 1
    assert with_a_gap.unscored == 1


def test_a_run_with_nothing_scored_has_no_mean():
    # Not 0.0 — that would compare as the worst possible run.
    totals = aggregate([_result("a", scored=False)])
    assert totals.mean is None
    assert totals.per_dimension == {}


def test_the_run_mean_is_the_mean_of_the_dimension_means():
    totals = aggregate([_result("a", **{name: 6 for name in dimension_names()})])
    assert totals.mean == 6.0


def test_a_build_mean_is_reported_per_build():
    result = _result("a", depth=10)
    others = len(dimension_names()) - 1
    assert result.mean == round((10 + 5 * others) / (others + 1), 2)


def test_aggregating_nothing_is_not_an_error():
    assert aggregate([]) == Totals(per_dimension={}, mean=None, scored=0, unscored=0)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def test_the_report_has_a_row_per_build_and_a_mean_row(tmp_path):
    run = _run(tmp_path, [_result("cottage"), _result("tower")], judged=True)
    text = report.markdown_report(run)
    assert "| cottage |" in text
    assert "| tower |" in text
    assert "| **mean** |" in text


def test_the_report_keeps_the_benchmark_order(tmp_path):
    # Comparability across runs depends on the rows lining up.
    run = _run(tmp_path, [_result("zebra"), _result("apple")], judged=True)
    text = report.markdown_report(run)
    assert text.index("| zebra |") < text.index("| apple |")


def test_a_judged_report_names_the_model(tmp_path):
    run = _run(tmp_path, [_result("cottage")], judged=True)
    assert judge.JUDGE_MODEL in report.markdown_report(run)


def test_an_unscored_report_says_how_to_score_it(tmp_path):
    run = _run(tmp_path, [_result("cottage", scored=False)])
    text = report.markdown_report(run)
    assert "Scoring this run" in text
    assert 'pip install "minecraft-builder-mcp[eval]"' in text
    assert "--judge" in text
    assert report.UNSCORED in text


def test_a_build_that_failed_says_why(tmp_path):
    broken = BuildResult(id="tower", prompt="Build a tower.", error="no structure at builds/tower.json")
    text = report.markdown_report(_run(tmp_path, [broken]))
    assert "no structure at builds/tower.json" in text


def test_image_paths_are_relative_to_the_run_folder(tmp_path):
    """So a run folder can be moved or handed to someone else and still render."""
    result = _result("cottage")
    result.images = [tmp_path / "images" / "cottage-southeast.png"]
    payload = report.scores_payload(_run(tmp_path, [result], judged=True))
    assert payload["builds"][0]["images"] == [str(Path("images") / "cottage-southeast.png")]


def test_the_payload_records_what_would_make_two_runs_incomparable(tmp_path):
    payload = report.scores_payload(_run(tmp_path, [_result("cottage")], judged=True))
    assert payload["benchmark_fingerprint"] == "abc123abc123"
    assert payload["judge_model"] == judge.JUDGE_MODEL
    assert payload["dimensions"] == list(dimension_names())


def test_both_artefacts_are_written_either_way(tmp_path):
    for judged in (True, False):
        run = _run(tmp_path / str(judged), [_result("cottage", scored=judged)], judged=judged)
        written = report.write_run(run)
        assert written["report"].exists()
        payload = json.loads(written["scores"].read_text(encoding="utf-8"))
        assert payload["judged"] is judged


# --------------------------------------------------------------------------- #
# The judge, against a stand-in
# --------------------------------------------------------------------------- #

class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Reply:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, reply):
        self._reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


class _Client:
    """Just enough of anthropic.Anthropic to drive judge_build."""

    def __init__(self, reply):
        self.messages = _Messages(reply)


def _valid_reply(**overrides):
    return _Reply(json.dumps({"scores": _scores(**overrides), "notes": "Roof floats."}))


def test_a_judged_build_returns_scores_and_a_note():
    client = _Client(_valid_reply(depth=7))
    scores, note = judge_build(client, "Build a cottage.", [b"\x89PNG"])
    assert scores["depth"] == 7
    assert note == "Roof floats."


def test_the_judge_is_shown_the_rubric_and_the_pictures():
    """It has to score what a human scorer would score, from the same document."""
    client = _Client(_valid_reply())
    judge_build(client, "Build a cottage.", [b"one", b"two"])

    sent = client.messages.calls[0]
    assert "silhouette" in sent["system"][0]["text"]
    blocks = sent["messages"][0]["content"]
    assert blocks[0]["type"] == "text"
    assert "Build a cottage." in blocks[0]["text"]
    assert [b["type"] for b in blocks[1:]] == ["image", "image"]


def test_the_judge_never_sees_the_structure_json():
    # A judge that could read the source would score the claim, not the build.
    client = _Client(_valid_reply())
    judge_build(client, "Build a cottage.", [b"png"])
    sent = json.dumps(client.messages.calls[0], default=str)
    assert '"op"' not in sent
    assert "cuboid" not in sent


def test_the_reply_shape_is_constrained_rather_than_parsed_out_of_prose():
    client = _Client(_valid_reply())
    judge_build(client, "Build a cottage.", [b"png"])
    fmt = client.messages.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == rubric.score_schema()


def test_the_model_is_named_in_one_place():
    client = _Client(_valid_reply())
    judge_build(client, "Build a cottage.", [b"png"])
    assert client.messages.calls[0]["model"] == judge.JUDGE_MODEL


def test_a_refusal_is_reported_not_read():
    # stop_reason has to be checked before content — a refusal has none.
    client = _Client(_Reply("", stop_reason="refusal"))
    with pytest.raises(JudgeError, match="declined"):
        judge_build(client, "Build a cottage.", [b"png"])


def test_a_non_json_reply_is_reported():
    client = _Client(_Reply("The build is quite nice, 7/10."))
    with pytest.raises(JudgeError, match="not JSON"):
        judge_build(client, "Build a cottage.", [b"png"])


def test_an_out_of_range_score_from_the_judge_is_reported():
    client = _Client(_valid_reply(depth=99))
    with pytest.raises(JudgeError, match="between 1 and 10"):
        judge_build(client, "Build a cottage.", [b"png"])


def test_judging_a_build_with_no_renders_is_refused():
    with pytest.raises(JudgeError, match="no renders"):
        judge_build(_Client(_valid_reply()), "Build a cottage.", [])


def test_a_missing_anthropic_package_names_the_install(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    with pytest.raises(JudgeError) as caught:
        judge.build_client()
    message = str(caught.value)
    assert 'pip install "minecraft-builder-mcp[eval]"' in message
    # Copy-pasteable, so no sentence period after the command.
    assert not message.rstrip().endswith(".")


def test_the_credentials_hint_does_not_assume_an_api_key():
    """An unset ANTHROPIC_API_KEY is not proof there are no credentials."""
    assert "ant auth login" in judge.NO_CREDENTIALS
    assert not judge.NO_CREDENTIALS.rstrip().endswith(".")


# --------------------------------------------------------------------------- #
# The runner, with the browser and the judge stubbed
# --------------------------------------------------------------------------- #

class _Shot:
    def __init__(self, path):
        self.path = path
        self.png = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def fake_render(monkeypatch):
    """Stands in for the browser: writes a file per view and reports the paths."""
    def render(structure, output_dir, views, width, height, stem):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        shots = []
        for view in views:
            path = Path(output_dir) / f"{stem}-{view.name}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            shots.append(_Shot(path))
        return shots

    monkeypatch.setattr(
        runner, "render_views",
        lambda structure, output_dir, views, width, height, stem: render(
            structure, output_dir, views, width, height, stem),
    )


@pytest.fixture
def one_benchmark():
    return [benchmarks.Benchmark(
        id="medieval_cottage", prompt="Build a cottage.", stresses="the baseline")]


@pytest.fixture
def structures(tmp_path):
    directory = tmp_path / "builds"
    directory.mkdir()
    (directory / "medieval_cottage.json").write_text(json.dumps({
        "name": "cottage",
        "operations": [{"op": "cuboid", "start": [0, 0, 0], "end": [4, 3, 4],
                        "block": "oak_planks"}],
    }), encoding="utf-8")
    return directory


def test_a_render_only_run_writes_a_bundle(tmp_path, fake_render, structures, one_benchmark):
    run = runner.run_eval(structures, output_root=tmp_path / "out", benchmarks=one_benchmark)

    assert run.judged is False
    assert len(run.results[0].images) == runner.EVAL_VIEWS
    assert (run.directory / "report.md").exists()
    assert (run.directory / "scores.json").exists()
    assert run.totals.mean is None


def test_a_judged_run_scores_every_build(tmp_path, fake_render, structures, one_benchmark):
    run = runner.run_eval(
        structures, output_root=tmp_path / "out", benchmarks=one_benchmark,
        judge_client=_Client(_valid_reply(depth=9)),
    )
    assert run.judged is True
    assert run.results[0].scores["depth"] == 9
    assert run.totals.scored == 1


def test_a_missing_structure_costs_one_row_not_the_run(tmp_path, fake_render, structures):
    """Thirteen scores and a named gap is a measurement; a traceback is not."""
    set_with_a_gap = [
        benchmarks.Benchmark(id="medieval_cottage", prompt="Build a cottage.", stresses=""),
        benchmarks.Benchmark(id="never_generated", prompt="Build a tower.", stresses=""),
    ]
    run = runner.run_eval(
        structures, output_root=tmp_path / "out", benchmarks=set_with_a_gap,
        judge_client=_Client(_valid_reply()),
    )
    assert run.results[0].scored
    assert not run.results[1].scored
    assert "no structure at" in run.results[1].error
    assert run.totals.scored == 1 and run.totals.unscored == 1


def test_a_judge_failure_costs_one_row_not_the_run(tmp_path, fake_render, structures, one_benchmark):
    run = runner.run_eval(
        structures, output_root=tmp_path / "out", benchmarks=one_benchmark,
        judge_client=_Client(_Reply("not json at all")),
    )
    assert not run.results[0].scored
    assert "not JSON" in run.results[0].error
    # The renders survive, so the row can still be scored by hand.
    assert run.results[0].images


def test_missing_structures_is_checked_before_any_rendering(tmp_path, structures):
    absent = [benchmarks.Benchmark(id="nope", prompt="p", stresses="")]
    assert runner.missing_structures(structures, absent) == ["nope"]
    assert runner.missing_structures(structures, [
        benchmarks.Benchmark(id="medieval_cottage", prompt="p", stresses="")]) == []


def test_the_run_folder_name_is_a_legal_windows_filename(tmp_path, fake_render, structures, one_benchmark):
    # CI runs on Windows, where a colon in a path is not allowed.
    run = runner.run_eval(structures, output_root=tmp_path / "out", benchmarks=one_benchmark)
    assert ":" not in run.directory.name


def test_the_shipped_fixture_answers_a_real_benchmark():
    """The example exists so the runner can be tried without generating a set."""
    fixture = Path(__file__).resolve().parent.parent / "examples" / "eval"
    ids = {prompt.id for prompt in benchmarks.load_benchmarks()}
    shipped = {path.stem for path in fixture.glob("*.json")}
    assert shipped
    assert shipped <= ids, f"fixture names must match benchmark ids: {shipped - ids}"
    assert runner.load_structure(fixture / "medieval_cottage.json").expand()
