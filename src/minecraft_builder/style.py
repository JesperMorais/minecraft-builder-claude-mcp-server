"""Build-quality style guide shipped with the server.

The guide lives in ``data/style_guide.md`` so it travels with an installed
package instead of depending on a source checkout. Two forms are exposed:

* ``STYLE_CHECKLIST`` — the compact, always-in-context version embedded in the
  ``create_minecraft_structure`` description, so the non-negotiable rules apply
  even if the model never asks for the full guide.
* ``VISUAL_CRITIQUE_CHECKLIST`` — the same guide asked as questions about a
  *picture*, returned with every render.
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
  the walls. One block dominating the whole build is the #1 amateur tell. A
  masonry primary needs a non-stone secondary or accent — wood, a plank deck, a
  contrasting cap. Cracked and mossy variants are texture, not a second material.
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
  Both sides 10+ blocks: the body must project something 3+ deep and a quarter
  of the facade wide. The roof does not count toward this.
- Interior: carve it with "air", give it a floor, and light it."""

# Returned with every render, so it has to stay short enough to reread each
# round. Deliberately phrased as what to LOOK for rather than what to count:
# lint.py already counts, and it reports every one of these it can reach from
# the JSON. What it cannot see is whether the result looks right — a build can
# satisfy the palette ratio and still read as one grey slab, or place its
# lanterns correctly and still hide every one behind a roof overhang.
VISUAL_CRITIQUE_CHECKLIST = """VISUAL CRITIQUE — go through these against the images, and say what you SEE
rather than what you meant to build. Vague approval here wastes the render.
1. Silhouette — trace the outline against the sky. Is it a plain box? Is there
   one element clearly taller than the rest to read as a focal point?
2. Palette — does one material swamp the picture? Is the roof obviously a
   different material from the walls, at a glance?
3. Depth — do the walls cast shadows across themselves, or read as flat panels?
   Pillars, plinth and cornice should be visible as relief, not just present.
4. Roofline — is the top edge resolved the way this style wants it? Pitched:
   deliberate slope, ridge capped, overhang clear of the walls. Flat or
   roofless: a parapet, cornice, awning or railing rather than a bare plane.
5. Light — can you actually see lanterns on the facade, or is the build dark?
   Lights hidden under an overhang count for nothing from outside.
6. Grounding — does the base meet the ground, or does the build look pasted on
   top of it? Look for the plinth and a softened ground line.
Name the worst offender, fix that one operation with patch_operations, and
render again. Do not fix everything at once — you cannot tell what helped."""


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
