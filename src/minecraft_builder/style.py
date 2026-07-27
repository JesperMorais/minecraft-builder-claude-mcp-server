"""Build-quality style guide shipped with the server.

The guide lives in ``data/style_guide.md`` so it travels with an installed
package instead of depending on a source checkout. Two forms are exposed:

* ``STYLE_CHECKLIST`` — the compact, always-in-context version embedded in the
  ``create_minecraft_structure`` description, so the non-negotiable rules apply
  even if the model never asks for the full guide.
* ``load_style_guide()`` — the full document, served by the
  ``get_build_style_guide`` tool.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

STYLE_GUIDE_FILE = "style_guide.md"

# Kept deliberately short: this ships in every tool listing.
STYLE_CHECKLIST = """BUILD QUALITY — for anything larger than a few dozen blocks, call
get_build_style_guide first. These rules apply regardless:
- Palette: 3-5 blocks in a ~50/30/20 split. The roof material must differ from
  the walls. One block dominating the whole build is the #1 amateur tell.
- Depth: no flat wall face longer than 6-8 blocks. Add pillars (+1 out), inset
  windows (-1 in), a base plinth, and a roofline cornice.
- Roof: real pitch (stairs give 45 degrees), overhang 1-2 blocks past the walls,
  ridge capped. A gable narrows by 2 per course — check the arithmetic lands on a
  1-2 wide ridge, or you get a flat top that looks like a mistake.
- Proportion: 3+ blocks headroom, 4-5 per storey, roof rise 4-10 blocks,
  footprint nearer 1:1.5 than square.
- Light: one lantern per 6-8 blocks of facade and one per interior room. Prefer
  lantern over torch. A build with no light sources looks dead.
- Silhouette: break the rectangle (L/T/U footprint, or a wing, bay or tower).
- Interior: carve it with "air", give it a floor, and light it."""


@lru_cache(maxsize=1)
def load_style_guide() -> str:
    """Return the full style-guide markdown.

    Read as UTF-8 explicitly — the guide contains typographic characters that
    would fail under a Windows default codepage.
    """
    return (
        resources.files("minecraft_builder.data")
        .joinpath(STYLE_GUIDE_FILE)
        .read_text(encoding="utf-8")
    )
