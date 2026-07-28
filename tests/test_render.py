"""Tests for headless rendering: framing maths, plumbing, and one real browser.

Split deliberately. Everything up to the point Chromium is launched is pure and
is tested as such — the framing is where a mistake produces five plausible
pictures of the wrong thing, and none of it needs a browser to check. The single
browser test at the bottom exists because the rest cannot tell you whether an
actual PNG came out with the build in it, and skips itself where Playwright is
not installed.
"""

import json
import math
import sys
import tempfile
import zlib
from importlib import resources
from pathlib import Path

import pytest

from minecraft_builder.schema import MinecraftStructure
from minecraft_builder.web import app, render
from minecraft_builder.web.payload import build_payload
from minecraft_builder.web.render import (
    DEFAULT_VIEWS,
    MIN_FRAME_RADIUS,
    RenderError,
    View,
    camera_position,
    default_output_directory,
    frame_centre,
    frame_distance,
    render_views,
    select_views,
)


def _hut(size=6):
    return MinecraftStructure(
        name="hut",
        operations=[
            {"op": "hollow_box", "start": [0, 0, 0],
             "end": [size, 4, size], "block": "stone_bricks"},
        ],
    )


def _bounds(low, size):
    return {"min": list(low), "max": [low[i] + size[i] - 1 for i in range(3)],
            "size": list(size)}


def _playwright_installed():
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


needs_playwright = pytest.mark.skipif(
    not _playwright_installed(),
    reason="needs the render extra: pip install '.[render]' && playwright install chromium",
)


# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #

def test_centre_is_the_middle_of_the_box():
    assert frame_centre(_bounds((0, 0, 0), (10, 4, 6))) == (5.0, 2.0, 3.0)


def test_centre_survives_negative_coordinates():
    # Authoring coordinates go negative and the viewer renders them as-is, so a
    # camera framed on an absolute value would look at empty ground.
    assert frame_centre(_bounds((-20, -4, -8), (10, 4, 6))) == (-15.0, -2.0, -5.0)


def test_distance_frames_the_diagonal_not_the_longest_side():
    # A long thin build read as "half its longest side" would put the camera
    # close enough to clip its far corners off the frame.
    bounds = _bounds((0, 0, 0), (40, 4, 4))
    radius = math.hypot(40, 4, 4) / 2
    assert frame_distance(bounds) == pytest.approx(
        radius / math.sin(math.radians(render.CAMERA_FOV_DEGREES) / 2)
        * render.FRAMING_PADDING
    )


def test_distance_has_a_floor():
    # Without one, a single block puts the camera inside itself.
    tiny = frame_distance(_bounds((0, 0, 0), (1, 1, 1)))
    assert tiny == pytest.approx(
        MIN_FRAME_RADIUS / math.sin(math.radians(render.CAMERA_FOV_DEGREES) / 2)
        * render.FRAMING_PADDING
    )
    assert tiny > 1


def test_bigger_builds_are_seen_from_further_away():
    small = frame_distance(_bounds((0, 0, 0), (8, 8, 8)))
    large = frame_distance(_bounds((0, 0, 0), (80, 80, 80)))
    assert large > small * 9


@pytest.mark.parametrize("azimuth,axis,sign", [
    (0, 2, -1),    # north is -Z
    (90, 0, +1),   # east is +X
    (180, 2, +1),  # south is +Z
    (270, 0, -1),  # west is -X
])
def test_bearings_follow_the_minecraft_compass(azimuth, axis, sign):
    """A bearing here has to mean what it means on the game's F3 screen.

    Getting this backwards is the failure that costs the most: every image comes
    out looking fine and every one is of the opposite face.
    """
    bounds = _bounds((0, 0, 0), (10, 10, 10))
    position = camera_position(bounds, View("test", azimuth, 0.0))
    centre = frame_centre(bounds)
    offset = [position[i] - centre[i] for i in range(3)]

    assert math.copysign(1, offset[axis]) == sign
    assert abs(offset[axis]) == pytest.approx(frame_distance(bounds))
    # A cardinal bearing puts nothing on the other horizontal axis.
    other = 2 if axis == 0 else 0
    assert offset[other] == pytest.approx(0, abs=1e-9)


def test_elevation_lifts_the_camera_and_keeps_the_distance():
    bounds = _bounds((0, 0, 0), (10, 10, 10))
    centre = frame_centre(bounds)
    level = camera_position(bounds, View("level", 135.0, 0.0))
    raised = camera_position(bounds, View("raised", 135.0, 30.0))

    assert level[1] == pytest.approx(centre[1])
    assert raised[1] > level[1]
    # Elevation orbits, it does not zoom: both stand the same distance off.
    assert math.dist(raised, centre) == pytest.approx(math.dist(level, centre))


def test_every_default_view_is_the_framing_distance_away():
    bounds = _bounds((-3, 0, 7), (12, 9, 5))
    centre = frame_centre(bounds)
    for view in DEFAULT_VIEWS:
        position = camera_position(bounds, view)
        assert math.dist(position, centre) == pytest.approx(frame_distance(bounds))


def test_framing_matches_the_viewer():
    """The page draws with a 50 degree camera; framing is computed here.

    They only agree because both use the same two numbers, and nothing at
    runtime would notice if one of them drifted.
    """
    viewer_js = (
        resources.files("minecraft_builder.web")
        .joinpath("static").joinpath("viewer.js").read_text(encoding="utf-8")
    )
    assert f"PerspectiveCamera({render.CAMERA_FOV_DEGREES:g}," in viewer_js


# --------------------------------------------------------------------------- #
# Choosing angles
# --------------------------------------------------------------------------- #

def test_default_is_four_corners_and_one_elevation():
    views = select_views()
    assert len(views) == 5
    level = [v for v in views if v.elevation == 0]
    assert len(level) == 1
    assert {v.azimuth for v in views if v.elevation} == {45, 135, 225, 315}


def test_a_smaller_count_is_a_prefix_of_the_standard_set():
    assert select_views(3) == list(DEFAULT_VIEWS[:3])


def test_the_first_two_are_a_corner_and_the_level_elevation():
    # The ordering promise: any prefix has to be a usable set on its own, so one
    # image is the corner the viewer opens at and two add the straight-on view.
    first, second = select_views(2)
    assert first.elevation == render.ISO_ELEVATION
    assert second.elevation == 0


def test_a_bigger_count_orbits_and_keeps_the_elevation():
    views = select_views(9)
    assert len(views) == 9
    assert sum(1 for v in views if v.elevation == 0) == 1
    bearings = sorted(v.azimuth for v in views if v.elevation)
    gaps = {round(b - a, 6) for a, b in zip(bearings, bearings[1:], strict=False)}
    assert len(gaps) == 1  # evenly spread


def test_count_must_be_positive():
    with pytest.raises(RenderError, match="at least 1"):
        select_views(0)


def test_explicit_angles_win_over_count():
    views = select_views(count=5, angles=[{"azimuth": 12, "elevation": 3}])
    assert len(views) == 1
    assert (views[0].azimuth, views[0].elevation) == (12.0, 3.0)


def test_angles_are_named_by_bearing_when_unnamed():
    assert select_views(angles=[{"azimuth": 7.4, "elevation": 0}])[0].name == "bearing-007"


def test_angle_names_cannot_escape_the_output_directory():
    view = select_views(angles=[{"azimuth": 0, "elevation": 0, "name": "../../etc/pwn"}])[0]
    assert "/" not in view.name and ".." not in view.name


def test_bearings_wrap():
    assert select_views(angles=[{"azimuth": 450, "elevation": 0}])[0].azimuth == 90.0


def test_straight_down_is_refused():
    # three.js has no defined up vector looking along it, and resolves the
    # ambiguity by spinning the frame.
    with pytest.raises(RenderError, match="between -89 and 89"):
        select_views(angles=[{"azimuth": 0, "elevation": 90}])


def test_an_angle_without_numbers_is_refused():
    with pytest.raises(RenderError, match="numeric azimuth and elevation"):
        select_views(angles=[{"azimuth": "sideways", "elevation": 0}])


# --------------------------------------------------------------------------- #
# Output paths
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,expected", [
    ("stone hut", "stone_hut"),
    ("../../etc/passwd", "etc_passwd"),
    ("...", "structure"),
    ("", "structure"),
])
def test_structure_names_become_safe_stems(name, expected):
    # Structure names come from model-generated JSON and end up in a filename.
    assert render._safe_stem(name) == expected


def test_renders_default_to_a_temp_folder():
    # Working images from a review loop, not artefacts anyone asked to keep.
    assert default_output_directory().parent == Path(tempfile.gettempdir())


# --------------------------------------------------------------------------- #
# Failing without a browser
# --------------------------------------------------------------------------- #

def test_missing_playwright_names_the_install_command(monkeypatch, tmp_path):
    """The tool result is what the model reads next, so it has to be actionable."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)

    with pytest.raises(RenderError) as caught:
        render_views(_hut(), tmp_path)

    message = str(caught.value)
    assert 'pip install "minecraft-builder-mcp[render]"' in message
    assert "playwright install chromium" in message
    # The line gets copy-pasted. A sentence period lands inside the command and
    # produces a second, more confusing failure than the one being fixed.
    assert not message.rstrip().endswith(".")


def test_a_missing_browser_is_not_a_missing_library():
    """Both are 'no renderer', and the command that fixes them differs."""
    class _Error(Exception):
        pass

    class _Chromium:
        def launch(self, args):
            raise _Error("Executable doesn't exist at /home/x/.cache/ms-playwright/...")

    class _Playwright:
        chromium = _Chromium()

    api = type("api", (), {"Error": _Error})
    with pytest.raises(RenderError) as caught:
        render._launch(_Playwright(), api)

    message = str(caught.value)
    assert "playwright install chromium" in message
    assert "pip install" not in message


def test_the_caller_is_told_off_before_being_sent_to_install_anything(monkeypatch, tmp_path):
    """An empty structure is the caller's bug and stays one with a browser installed."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    empty = MinecraftStructure(
        name="void",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [3, 3, 3], "block": "air"}],
    )
    with pytest.raises(RenderError, match="no visible blocks"):
        render_views(empty, tmp_path)


def test_absurd_image_sizes_are_refused(tmp_path):
    with pytest.raises(RenderError, match="width must be between"):
        render_views(_hut(), tmp_path, width=20_000)
    with pytest.raises(RenderError, match="height must be between"):
        render_views(_hut(), tmp_path, height=1)


def test_no_angles_is_refused(tmp_path):
    with pytest.raises(RenderError, match="No camera angles"):
        render_views(_hut(), tmp_path, views=[])


def test_a_stall_blames_the_cdn_when_a_request_failed():
    # The viewer imports three.js over the network, so an offline machine gets a
    # page that loads, runs nothing and reports nothing.
    message = render._explain_stall(
        ["could not load https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js (net::ERR)"],
        TimeoutError("timeout"),
    )
    assert "network access" in message
    assert "cdn.jsdelivr.net" in message


def test_a_stall_with_no_faults_says_only_what_it_knows():
    message = render._explain_stall([], TimeoutError("Timeout 45000ms exceeded"))
    assert "never finished drawing" in message
    assert "network" not in message


# --------------------------------------------------------------------------- #
# Plumbing, with a stand-in for the browser
# --------------------------------------------------------------------------- #

class _FakeRoute:
    """Stands in for the intercepted /api/structure request."""

    def __init__(self):
        self.fulfilled = {}

    def fulfill(self, **kwargs):
        self.fulfilled = kwargs


class _FakePage:
    """Records what the driver asked the page to do."""

    def __init__(self):
        self.routes = {}
        self.evaluated = []
        self.shots = []
        self.url = None
        self.viewport = None

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    def on(self, event, handler):
        pass

    def route(self, pattern, handler):
        self.routes[pattern] = handler

    def goto(self, url, wait_until=None):
        self.url = url

    def wait_for_function(self, expression):
        pass

    def evaluate(self, expression, arg=None):
        self.evaluated.append((expression, arg))

    def screenshot(self, path):
        # The real one writes the file and hands back the same bytes.
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n-fake")
        self.shots.append(path)
        return b"\x89PNG\r\n\x1a\n-fake"


class _FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self, viewport, device_scale_factor):
        self.page.viewport = viewport
        self.page.scale = device_scale_factor
        return self.page

    def close(self):
        self.closed = True


class _FakeApi:
    """Just enough of playwright.sync_api to drive render_views."""

    Error = RuntimeError

    def __init__(self, page):
        self.browser = _FakeBrowser(page)

    def sync_playwright(self):
        api = self

        class _Context:
            def __enter__(self):
                return type("pw", (), {"chromium": type(
                    "chromium", (), {"launch": staticmethod(lambda args: api.browser)}
                )()})()

            def __exit__(self, *exc):
                return False

        return _Context()


@pytest.fixture
def fake_browser(monkeypatch):
    page = _FakePage()
    api = _FakeApi(page)
    monkeypatch.setattr(render, "_playwright_api", lambda: api)
    # Never bind the port a live session is already serving on.
    monkeypatch.setattr(app, "PREFERRED_PORT", 0)
    return page, api


def test_the_page_is_asked_for_render_mode(fake_browser, tmp_path):
    page, _ = fake_browser
    render_views(_hut(), tmp_path, views=[DEFAULT_VIEWS[0]])
    assert page.url.endswith("?render=1")


def test_the_payload_is_served_to_the_page_not_stored(fake_browser, tmp_path):
    """Rendering must not touch what the user is looking at.

    The structure reaches the page by answering its fetch, so the session's own
    state never hears about it — otherwise asking for a picture would bump the
    version and repoint any note not yet applied.
    """
    page, _ = fake_browser
    structure = _hut()
    before = app.STATE.version
    render_views(structure, tmp_path, views=[DEFAULT_VIEWS[0]])

    assert list(page.routes) == ["**/api/structure"]
    route = _FakeRoute()
    page.routes["**/api/structure"](route)
    assert json.loads(route.fulfilled["body"]) == build_payload(structure)
    assert app.STATE.version == before


def test_one_screenshot_per_view_named_for_its_angle(fake_browser, tmp_path):
    page, _ = fake_browser
    rendered = render_views(_hut(), tmp_path, views=list(DEFAULT_VIEWS[:3]))

    assert len(rendered) == 3
    assert [shot.path.name for shot in rendered] == [
        f"hut-{view.name}.png" for view in DEFAULT_VIEWS[:3]
    ]
    assert all(shot.path.exists() for shot in rendered)
    assert len(page.shots) == 3


def test_each_view_aims_the_camera_where_the_maths_says(fake_browser, tmp_path):
    page, _ = fake_browser
    structure = _hut()
    views = list(DEFAULT_VIEWS[:2])
    render_views(structure, tmp_path, views=views)

    bounds = build_payload(structure)["bounds"]
    aimed = [arg for expression, arg in page.evaluated if "mcbRender.view" in expression]
    assert len(aimed) == 2
    for view, (position, target) in zip(views, aimed, strict=True):
        assert position == pytest.approx(list(camera_position(bounds, view)))
        assert target == pytest.approx(list(frame_centre(bounds)))


def test_the_viewport_is_the_image(fake_browser, tmp_path):
    # A device scale factor would silently return pictures at another size.
    page, _ = fake_browser
    render_views(_hut(), tmp_path, views=[DEFAULT_VIEWS[0]], width=640, height=480)
    assert page.viewport == {"width": 640, "height": 480}
    assert page.scale == 1


def test_the_browser_is_closed_even_when_a_shot_fails(fake_browser, tmp_path, monkeypatch):
    page, api = fake_browser

    def explode(path):
        raise RuntimeError("target closed")

    monkeypatch.setattr(page, "screenshot", explode)
    with pytest.raises(RenderError, match="Screenshot of southeast failed"):
        render_views(_hut(), tmp_path, views=[DEFAULT_VIEWS[0]])
    assert api.browser.closed


# --------------------------------------------------------------------------- #
# The real thing
# --------------------------------------------------------------------------- #

def _decode_png(data):
    """Minimal PNG reader: 8-bit RGB/RGBA, which is all Chromium emits.

    Here rather than as a dependency because it exists for one assertion — that
    the picture has the build in it and is not a blank frame — and Pillow is a
    lot of install for one assertion in one skipped-by-default test.
    """
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    position, compressed, header = 8, bytearray(), b""
    while position < len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        if kind == b"IHDR":
            header = body
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
        position += 12 + length

    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    assert header[8] == 8, "expected 8 bits per channel"
    channels = {2: 3, 6: 4}[header[9]]
    raw = zlib.decompress(bytes(compressed))

    stride = width * channels
    rows, prior, position = [], bytes(stride), 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prior[i]
            up_left = prior[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                estimate = left + up - up_left
                deltas = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
                nearest = (left, up, up_left)[deltas.index(min(deltas))]
                line[i] = (line[i] + nearest) & 0xFF
        rows.append(bytes(line))
        prior = line
    return width, height, channels, rows


@needs_playwright
def test_a_real_browser_draws_the_build(tmp_path, monkeypatch):
    """The one test that proves the whole path works.

    Small on purpose: 320x240 keeps both the software rasteriser and the pure
    Python PNG decode quick, and the assertion does not need pixels to spare.
    """
    monkeypatch.setattr(app, "PREFERRED_PORT", 0)
    structure = MinecraftStructure(
        name="grey tower",
        operations=[{"op": "cuboid", "start": [0, 0, 0], "end": [5, 20, 5],
                     "block": "stone_bricks"}],
    )
    views = [View("front", 180.0, 0.0)]
    rendered = render_views(structure, tmp_path, views=views, width=320, height=240)

    assert len(rendered) == 1
    shot = rendered[0]
    assert shot.path.exists()
    # The bytes handed back are the bytes on disk; the model reviews the file.
    assert shot.path.read_bytes() == shot.png

    width, height, channels, rows = _decode_png(shot.png)
    assert (width, height) == (320, 240)

    def pixel(x, y):
        row = rows[y]
        return row[x * channels], row[x * channels + 1], row[x * channels + 2]

    # A blank render is sky over grass: every pixel is blue-dominant or
    # green-dominant. Stone bricks are grey, so a column of near-neutral pixels
    # down the middle is the tower and nothing else could be.
    middle = [pixel(width // 2, y) for y in range(height // 4, height * 3 // 4)]
    neutral = [p for p in middle if max(p) - min(p) < 20]
    assert len(neutral) > len(middle) // 4, "no tower in the middle of the frame"
    assert all(sum(p) / 3 < 200 for p in neutral), "the tower should not be blown out"


@needs_playwright
def test_a_real_browser_renders_each_angle_differently(tmp_path, monkeypatch):
    """Proves the camera actually moves, which a single shot cannot."""
    monkeypatch.setattr(app, "PREFERRED_PORT", 0)
    structure = MinecraftStructure(
        name="lopsided",
        operations=[
            {"op": "cuboid", "start": [0, 0, 0], "end": [2, 10, 2], "block": "stone"},
            {"op": "cuboid", "start": [10, 0, 0], "end": [12, 2, 2], "block": "oak_planks"},
        ],
    )
    rendered = render_views(
        structure, tmp_path, width=320, height=240,
        views=[View("east", 90.0, 10.0), View("west", 270.0, 10.0)],
    )
    assert rendered[0].png != rendered[1].png
