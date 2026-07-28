"""Tests for the render-critique-patch loop the server steers the model into.

The loop is guidance, not code: it lives in the system prompt, in two tool
descriptions and in the result text of everything that produces a build. That
makes it easy to break silently — a reworded result still passes every other
test in this suite while quietly dropping the step that makes the model look at
its own work.

The other half of what is checked here is that the guidance stays *off* where it
cannot be followed. Telling a default install to call a tool that answers
"install a browser" would be worse than saying nothing, because it arrives on
every build.
"""

import asyncio
import json

import pytest

from minecraft_builder import server
from minecraft_builder.style import VISUAL_CRITIQUE_CHECKLIST
from minecraft_builder.web import app
from minecraft_builder.web.render import rendering_available


@pytest.fixture(autouse=True)
def clean_probe():
    """The probe is cached for the process, so a test that fakes it must reset.

    Autouse because the cache is already warm by the time any test runs —
    importing server.py calls it to build the instructions.
    """
    rendering_available.cache_clear()
    yield
    rendering_available.cache_clear()


@pytest.fixture
def without_rendering(monkeypatch):
    """A default install: no render extra."""
    monkeypatch.setattr(
        "minecraft_builder.web.render.importlib.util.find_spec",
        lambda name: None if name == "playwright" else object(),
    )
    rendering_available.cache_clear()


@pytest.fixture
def viewer_port(monkeypatch):
    """Never bind 8791 — a live session from another window usually holds it."""
    monkeypatch.setattr(app, "PREFERRED_PORT", 0)
    yield
    app.shutdown()


@pytest.fixture
def with_rendering(monkeypatch):
    monkeypatch.setattr(
        "minecraft_builder.web.render.importlib.util.find_spec",
        lambda name: object(),
    )
    rendering_available.cache_clear()


def _call(tool, arguments=None):
    return asyncio.run(server.call_tool(tool, arguments or {}))


def _cottage_json():
    return json.dumps({
        "name": "cottage",
        "operations": [
            {"op": "hollow_box", "start": [0, 0, 0], "end": [6, 4, 6],
             "block": "oak_planks"},
        ],
    })


# --------------------------------------------------------------------------- #
# The probe
# --------------------------------------------------------------------------- #

def test_the_probe_finds_an_installed_playwright(with_rendering):
    assert rendering_available() is True


def test_the_probe_reports_a_default_install(without_rendering):
    assert rendering_available() is False


def test_the_probe_does_not_import_playwright(monkeypatch):
    """find_spec, not import: this runs at startup and nothing needs the module.

    Guarded because switching to a plain try/import would work, pass every other
    test, and quietly add a browser library's import cost to every session that
    never renders.
    """
    asked = []
    monkeypatch.setattr(
        "minecraft_builder.web.render.importlib.util.find_spec",
        lambda name: asked.append(name) or object(),
    )
    rendering_available.cache_clear()
    rendering_available()
    assert asked == ["playwright"]


# --------------------------------------------------------------------------- #
# The system prompt
# --------------------------------------------------------------------------- #

def test_the_loop_is_in_the_instructions_when_it_can_be_run(with_rendering):
    instructions = server.build_instructions()
    assert "render_structure" in instructions
    assert "patch_operations" in instructions


def test_the_loop_is_absent_from_a_default_install(without_rendering):
    instructions = server.build_instructions()
    assert "render_structure" not in instructions
    # The rest of the guidance has to survive its removal intact.
    assert "show_structure" in instructions
    assert "await_prompt" in instructions


def test_the_loop_has_a_round_budget(with_rendering):
    # Without one the model keeps polishing; builds stop improving after two or
    # three passes and the tokens keep being spent.
    assert "Three rounds" in server.REVIEW_LOOP_INSTRUCTIONS


def test_the_loop_yields_to_the_user(with_rendering):
    """The human annotation flow outranks the model's own critique.

    A revision landing while someone is marking up the build repoints the note
    they are in the middle of writing — the exact failure annotations resolve at
    creation time to avoid.
    """
    instructions = server.build_instructions().lower()
    assert "stop the loop immediately once the user" in instructions
    assert "marking up" in instructions


# --------------------------------------------------------------------------- #
# The nudges on build results
# --------------------------------------------------------------------------- #

def test_a_build_result_names_the_next_step(with_rendering):
    nudge = server._look_before_done()
    assert "render_structure" in nudge
    assert "patch_operations" in nudge


def test_a_build_result_says_nothing_it_cannot_back_up(without_rendering):
    assert server._look_before_done() == ""
    assert server._render_before_export() == ""


def test_show_structure_tells_the_model_to_look(with_rendering, viewer_port):
    result = _call("show_structure", {"structure_json": _cottage_json()})
    assert "render_structure" in result[0].text


def test_show_structure_stays_quiet_without_the_extra(without_rendering, viewer_port):
    result = _call("show_structure", {"structure_json": _cottage_json()})
    assert "render_structure" not in result[0].text
    # and still says everything it said before
    assert "Showing" in result[0].text
    assert "📐" in result[0].text


def test_patching_points_back_at_the_render(with_rendering, viewer_port):
    _call("show_structure", {"structure_json": _cottage_json()})
    result = _call("patch_operations", {"patches": [
        {"index": 0, "action": "replace", "operation": {
            "op": "hollow_box", "start": [0, 0, 0], "end": [6, 5, 6],
            "block": "stone_bricks"}},
    ]})
    assert "render_structure" in result[0].text


def _tool_descriptions():
    return {tool.name: tool.description for tool in asyncio.run(server.list_tools())}


def test_the_export_tool_says_to_look_first(with_rendering):
    assert "LOOK AT IT BEFORE WRITING A FILE" in _tool_descriptions()[
        "create_minecraft_structure"
    ]


def test_the_export_tool_is_unchanged_without_the_extra(without_rendering):
    description = _tool_descriptions()["create_minecraft_structure"]
    assert "render_structure" not in description
    assert "BUILD QUALITY" in description  # the style checklist survives


def test_the_tool_is_offered_even_where_it_cannot_run(without_rendering):
    """Listing is not steering.

    The tool stays in the listing on a default install so the feature is
    discoverable and can explain its own install; what turns off is the server
    pushing the model toward it. Hiding it would make the extra unfindable.
    """
    assert "render_structure" in _tool_descriptions()


# --------------------------------------------------------------------------- #
# The rubric
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("dimension", [
    "Silhouette", "Palette", "Depth", "Roofline", "Light", "Grounding",
])
def test_the_checklist_covers_every_dimension(dimension):
    assert dimension in VISUAL_CRITIQUE_CHECKLIST


def test_the_checklist_asks_about_the_picture_not_the_json():
    """It has to add something lint.py cannot already report.

    lint.py counts palette ratios, flat faces, stairs and lights from the
    structure. A rubric that asked the same questions again would cost a reread
    every round and catch nothing new, so this one asks what only the image
    answers.
    """
    text = VISUAL_CRITIQUE_CHECKLIST.lower()
    assert "see" in text
    assert "images" in text


def test_the_checklist_asks_for_one_fix_at_a_time():
    # Fixing everything at once means not knowing which edit helped, which makes
    # the next round's critique meaningless.
    assert "worst" in VISUAL_CRITIQUE_CHECKLIST
    assert "Do not fix everything at once" in VISUAL_CRITIQUE_CHECKLIST


def test_the_checklist_stays_short_enough_to_reread():
    # It ships with every render, so a rubric that grew into an essay would be
    # skimmed instead of answered.
    assert len(VISUAL_CRITIQUE_CHECKLIST.splitlines()) <= 20


def test_a_render_returns_the_rubric_with_the_images(monkeypatch, tmp_path, viewer_port):
    """The critique step is where the rubric earns its place, so it rides along."""
    shot = server.RenderedView(
        view=server.DEFAULT_VIEWS[0],
        path=tmp_path / "cottage-southeast.png",
        png=b"\x89PNG\r\n\x1a\n",
    )
    monkeypatch.setattr(server, "render_views", lambda *args, **kwargs: [shot])
    result = _call("render_structure", {"structure_json": _cottage_json()})

    assert VISUAL_CRITIQUE_CHECKLIST in result[0].text
    assert result[-1].type == "image"
