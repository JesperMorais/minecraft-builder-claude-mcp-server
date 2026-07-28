"""Headless screenshots of the 3D viewer, so a model can see what it built.

Every other feedback path in this project describes a build in words — an ASCII
preview, a style-guide verdict, a block count. This one shows it. A build that
lints clean and reads plausibly in JSON can still have its roof floating a block
above its walls, and no amount of text catches that.

Four decisions shape the module:

* **Drive the real viewer, not a second renderer.** Chromium loads the same page
  the user has open, with ``?render=1``. A renderer of our own would be a second
  thing to keep in step with ``viewer.js``, and every disagreement between them
  would be invisible: the model would review a picture the user never sees.
* **Serve the payload to the page instead of storing it.** The driver intercepts
  ``/api/structure`` and answers it directly. Pushing the structure through
  ``ViewerState`` would work and would be wrong — asking for a picture would
  bump the version, replace whatever the user was looking at, and silently
  repoint any note they had not applied yet.
* **The angle maths lives here, in Python.** The page is handed a camera
  position and a target and does as it is told. That keeps the part worth
  testing testable without a browser, and keeps the two ends from each holding
  half a framing calculation.
* **Playwright is optional and its absence is not an error worth a traceback.**
  Both ways it can be missing — no library, or a library with no browser — come
  back as one sentence naming the command that fixes it. This runs inside a tool
  call whose result is what the model reads next.

Coordinates are the structure's own authoring coordinates, matching the payload
and the viewer. Bearings follow Minecraft's compass, so an angle named here
means the same thing it does on the game's F3 screen.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..schema import MinecraftStructure
from .app import ensure_running
from .payload import build_payload

# Must match the PerspectiveCamera in viewer.js. Framing is computed on this
# side, so a disagreement here mis-frames every shot.
CAMERA_FOV_DEGREES = 50.0

# Room left around the build, as a multiple of the distance at which it would
# exactly fill the frame. The same 1.25 the viewer's own framing uses, so a
# default render looks like the default view.
FRAMING_PADDING = 1.25

# Stops a one-block build putting the camera inside itself.
MIN_FRAME_RADIUS = 2.0

# Big enough to read a roofline, small enough that five of them stay a
# reasonable tool result. Images are what a vision model pays for.
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600
MIN_DIMENSION = 200
MAX_DIMENSION = 2000

# Generous: the page fetches three.js from a CDN on a cold cache before it can
# draw anything, and a slow first load is not a failure.
DEFAULT_TIMEOUT_MS = 45_000

ISO_ELEVATION = 30.0

# Chromium here has no GPU, so WebGL has to come from SwiftShader. Asking for it
# explicitly rather than letting Chromium decide: on the builds where it decides
# not to, context creation fails inside the module and the page dies before it
# can report why.
BROWSER_ARGS = (
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
)

MISSING_PLAYWRIGHT = """\
Rendering needs Playwright, which is not installed. It is an optional extra
because it pulls in a browser; everything else in this server works without it.

Install the extra and the browser it drives with:

pip install "minecraft-builder-mcp[render]" && playwright install chromium"""

MISSING_BROWSER = """\
Playwright is installed but the Chromium it drives has not been downloaded.

Fetch it with:

playwright install chromium"""


class RenderError(RuntimeError):
    """Rendering failed for a reason the caller can do something about.

    Everything that escapes this module is one of these. The tool result is what
    the model reads before deciding what to do next, and a traceback tells it
    nothing actionable where "install the browser" tells it everything.
    """


@dataclass(frozen=True)
class View:
    """One camera angle.

    ``azimuth`` is a compass bearing for where the camera *stands*: 0 puts it
    due north of the build looking south, 90 due east looking west. Minecraft's
    north is -Z and its east is +X, so a bearing means here what it means in the
    game. ``elevation`` is degrees above the horizon, 0 being a level look.
    """

    name: str
    azimuth: float
    elevation: float


# Ordered so that any prefix is a sensible set on its own, because callers pick
# a count far more often than they pick angles: one image should be the corner
# the user's own viewer opens at, two should add the level elevation that makes
# proportion and roof pitch readable, three should show the back.
DEFAULT_VIEWS: Tuple[View, ...] = (
    View("southeast", 135.0, ISO_ELEVATION),
    View("south-elevation", 180.0, 0.0),
    View("northwest", 315.0, ISO_ELEVATION),
    View("southwest", 225.0, ISO_ELEVATION),
    View("northeast", 45.0, ISO_ELEVATION),
)


@dataclass(frozen=True)
class RenderedView:
    """One captured angle: where it was written and the bytes that went there."""

    view: View
    path: Path
    png: bytes


# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #

def frame_centre(bounds: Dict[str, List[int]]) -> Tuple[float, float, float]:
    """The point every camera looks at: the middle of the bounding box."""
    low = bounds["min"]
    size = bounds["size"]
    return (low[0] + size[0] / 2, low[1] + size[1] / 2, low[2] + size[2] / 2)


def frame_distance(
    bounds: Dict[str, List[int]],
    fov_degrees: float = CAMERA_FOV_DEGREES,
    padding: float = FRAMING_PADDING,
) -> float:
    """How far back the camera stands for the whole build to fit.

    What has to fit is the build's bounding *sphere*, so the radius is half the
    box diagonal rather than half its longest side. Framing on the longest side
    is the obvious version and it clips the corners of anything that is not a
    cube — which is most builds, and always the interesting ones.
    """
    size = bounds["size"]
    radius = max(math.hypot(*size) / 2, MIN_FRAME_RADIUS)
    return radius / math.sin(math.radians(fov_degrees) / 2) * padding


def camera_position(
    bounds: Dict[str, List[int]],
    view: View,
    fov_degrees: float = CAMERA_FOV_DEGREES,
    padding: float = FRAMING_PADDING,
) -> Tuple[float, float, float]:
    """Where the camera stands for ``view``, in authoring coordinates."""
    centre_x, centre_y, centre_z = frame_centre(bounds)
    distance = frame_distance(bounds, fov_degrees, padding)
    elevation = math.radians(view.elevation)
    azimuth = math.radians(view.azimuth)
    horizontal = distance * math.cos(elevation)
    # Negated on Z because a bearing of 0 means north, and north is -Z.
    return (
        centre_x + horizontal * math.sin(azimuth),
        centre_y + distance * math.sin(elevation),
        centre_z - horizontal * math.cos(azimuth),
    )


def select_views(
    count: Optional[int] = None,
    angles: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[View]:
    """Resolve a caller's request into concrete angles.

    Explicit ``angles`` win outright. A ``count`` past the named set falls back
    to an even orbit rather than inventing more compass names for corners, and
    keeps the level elevation, which is the one view an orbit never produces.
    """
    if angles:
        return [_view_from(index, angle) for index, angle in enumerate(angles)]
    if count is None:
        return list(DEFAULT_VIEWS)
    if count < 1:
        raise RenderError("count must be at least 1.")
    if count <= len(DEFAULT_VIEWS):
        return list(DEFAULT_VIEWS[:count])

    step = 360.0 / (count - 1)
    orbit = [
        _bearing_view((DEFAULT_VIEWS[0].azimuth + index * step) % 360.0, ISO_ELEVATION)
        for index in range(count - 1)
    ]
    return orbit + [DEFAULT_VIEWS[1]]


def _bearing_view(azimuth: float, elevation: float) -> View:
    return View(f"bearing-{int(round(azimuth)) % 360:03d}", azimuth, elevation)


def _view_from(index: int, angle: Dict[str, Any]) -> View:
    """One caller-supplied angle, validated."""
    if not isinstance(angle, dict):
        raise RenderError(f"Angle {index} must be an object with azimuth and elevation.")
    try:
        azimuth = float(angle["azimuth"]) % 360.0
        elevation = float(angle["elevation"])
    except (KeyError, TypeError, ValueError) as error:
        raise RenderError(
            f"Angle {index} needs a numeric azimuth and elevation ({error})."
        ) from error
    if not -89.0 <= elevation <= 89.0:
        # Straight up or straight down leaves the camera's up vector undefined,
        # and three.js resolves the ambiguity by spinning the frame.
        raise RenderError(
            f"Angle {index} has elevation {elevation}; it must be between -89 and 89."
        )
    name = str(angle.get("name") or _bearing_view(azimuth, elevation).name)
    return View(_safe_stem(name), azimuth, elevation)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

_UNSAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")

# Long enough to stay recognisable, short enough to leave room for the angle
# suffix inside a filesystem's name limit.
MAX_STEM_LENGTH = 60


def _safe_stem(name: str) -> str:
    """A filename stem from a structure or angle name.

    Both come out of model-generated JSON, so this has to survive slashes, dots
    and anything else that would otherwise write outside the output directory.
    """
    cleaned = _UNSAFE_STEM.sub("_", name).strip("._-")
    return cleaned[:MAX_STEM_LENGTH] or "structure"


def default_output_directory() -> Path:
    """Where renders go when the caller does not say.

    The temp directory, deliberately. These are working images from a review
    loop, not artefacts anyone asked for the way a ``.schem`` is — writing five
    PNGs onto someone's desktop every time the model checks its own work would
    be rude. A caller who wants to keep them passes a directory.
    """
    return Path(tempfile.gettempdir()) / "minecraft-builder-renders"


def _checked_size(width: int, height: int) -> Tuple[int, int]:
    for label, value in (("width", width), ("height", height)):
        if not MIN_DIMENSION <= value <= MAX_DIMENSION:
            raise RenderError(
                f"{label} must be between {MIN_DIMENSION} and {MAX_DIMENSION} pixels."
            )
    return int(width), int(height)


# --------------------------------------------------------------------------- #
# The browser
# --------------------------------------------------------------------------- #

def _playwright_api() -> Any:
    """The Playwright sync API, or a RenderError explaining how to get it.

    Imported here rather than at module scope so the package still imports, and
    every other tool still works, on an install without the render extra.
    """
    try:
        import playwright.sync_api as api
    except ImportError as error:
        raise RenderError(MISSING_PLAYWRIGHT) from error
    return api


def _launch(playwright: Any, api: Any) -> Any:
    try:
        return playwright.chromium.launch(args=list(BROWSER_ARGS))
    except api.Error as error:
        # Playwright's own message for this names a cache path and a command,
        # which is more than the model needs and less than it can act on.
        if "Executable doesn't exist" in str(error):
            raise RenderError(MISSING_BROWSER) from error
        raise RenderError(f"Could not start headless Chromium: {error}") from error


def _explain_stall(faults: List[str], error: Exception) -> str:
    """Turn a page that never became ready into something actionable.

    The overwhelmingly likely cause is the CDN: ``index.html`` pulls three.js
    over the network through an import map, so an offline machine gets a page
    that loads, executes nothing, and reports no error of its own.
    """
    if not faults:
        return (
            "The viewer page never finished drawing. "
            f"Chromium gave up after: {error}"
        )
    detail = "\n".join(f"- {fault}" for fault in dict.fromkeys(faults))
    return (
        "The viewer page never finished drawing:\n"
        f"{detail}\n\n"
        "The viewer loads three.js from a CDN through an import map, so "
        "rendering needs network access. To render offline, vendor "
        "three.module.js and the addons next to index.html and point the import "
        "map at them."
    )


def _watch_for_faults(page: Any) -> List[str]:
    """Collect the reasons a page might never become ready.

    Registered before navigation because both signals fire during load and
    neither is readable afterwards. Nothing here fails the render on its own —
    a page can log an error and still draw — but if it does stall, this is the
    only account of why.
    """
    faults: List[str] = []
    page.on("pageerror", lambda error: faults.append(f"page error: {error}"))
    page.on(
        "requestfailed",
        lambda request: faults.append(
            f"could not load {request.url} ({(request.failure or 'failed')})"
        ),
    )
    return faults


def render_views(
    structure: MinecraftStructure,
    output_dir: Path,
    views: Optional[Sequence[View]] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    stem: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> List[RenderedView]:
    """Screenshot ``structure`` from each angle and write the PNGs.

    Blocking, and it drives a browser: call it off the event loop. Raises
    ``RenderError`` for anything the caller can act on, which is everything it
    is expected to hit.
    """
    # Everything the caller got wrong is checked before Playwright is imported.
    # These faults hold whether or not a browser is installed, and sending
    # someone to download 150 MB of Chromium to be told their structure was empty
    # is the wrong order to find that out in.
    chosen = list(views) if views is not None else list(DEFAULT_VIEWS)
    if not chosen:
        raise RenderError("No camera angles to render.")
    width, height = _checked_size(width, height)

    payload = build_payload(structure)
    if not payload["voxels"]:
        raise RenderError(
            "Nothing to render — this structure has no visible blocks. "
            "Every block in it is air, or the whole thing is enclosed."
        )

    api = _playwright_api()
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RenderError(f"Could not create the output directory: {error}") from error

    file_stem = _safe_stem(stem or structure.name)
    body = json.dumps(payload)
    target = frame_centre(payload["bounds"])
    url = ensure_running() + "?render=1"

    with api.sync_playwright() as playwright:
        browser = _launch(playwright, api)
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                # The viewport is the image, so a scale factor would silently
                # return pictures at a size nobody asked for.
                device_scale_factor=1,
            )
            page.set_default_timeout(timeout_ms)
            faults = _watch_for_faults(page)
            # Answering /api/structure from here is what keeps rendering
            # side-effect free: the page gets this build without the session's
            # own state ever hearing about it.
            page.route(
                "**/api/structure",
                lambda route: route.fulfill(
                    status=200, content_type="application/json", body=body
                ),
            )
            try:
                page.goto(url, wait_until="load")
                page.wait_for_function("() => window.mcbRender !== undefined")
                # A ready signal, not a sleep: the page has a CDN fetch, texture
                # generation and a first frame to get through, and none of those
                # has a duration worth guessing at.
                page.evaluate("() => window.mcbRender.ready")
            except api.Error as error:
                raise RenderError(_explain_stall(faults, error)) from error

            rendered = []
            for view in chosen:
                position = camera_position(payload["bounds"], view)
                page.evaluate(
                    "([position, target]) => window.mcbRender.view(position, target)",
                    [list(position), list(target)],
                )
                path = directory / f"{file_stem}-{view.name}.png"
                try:
                    png = page.screenshot(path=str(path))
                except api.Error as error:
                    raise RenderError(f"Screenshot of {view.name} failed: {error}") from error
                rendered.append(RenderedView(view=view, path=path, png=png))
            return rendered
        finally:
            browser.close()
