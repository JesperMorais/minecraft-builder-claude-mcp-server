# Build Quality Rubric

How to score a generated Minecraft build from renders of it. Six dimensions,
1–10 each. This document is both the human scoring sheet and the text handed to
the automated judge — `eval/rubric.py` parses the dimension headings out of it,
so the two cannot drift apart.

Scores are only useful comparatively. A single build scoring 6.2 says almost
nothing; the same benchmark set scoring 6.2 before a style-guide change and 7.1
after it is the measurement this exists for. Score consistently rather than
generously.

## The scale

| Range | Means |
|---|---|
| 1–3 | Actively bad. A player would read this as broken or unfinished. |
| 4–6 | Serviceable. Nothing offends, nothing is memorable. Most naive output lands here. |
| 7–8 | Good. Deliberate choices are visible; it looks designed. |
| 9–10 | Excellent. You would screenshot it. Reserve 10 for builds with nothing to fix. |

Judge only what the renders show. Do not infer intent from the prompt, do not
give credit for a feature you cannot see, and do not penalise the flat-colour
material rendering — every build is drawn the same way, so it cancels out.

## Dimensions

### silhouette — the outline against the sky

Trace the shape with the build blacked out. Is it a box, or does it have a
profile worth looking at? Look for an L, T, U or cross footprint, a projecting
wing, bay or porch, and one element clearly taller than the rest to carry the
eye. Deliberate asymmetry scores; perfect mirroring reads as machine-made. A
plain rectangular prism caps this dimension at 3 no matter how well detailed.

### palette — materials and how they are distributed

Does a single material swamp the picture? The guide asks for 3–5 materials in
roughly a 50/30/20 split, and for the roof to differ from the walls at a
glance. Score down hard for one block over ~50% of what is visible, and for a
roof that reads as a continuation of the wall. Score up for an accent material
used sparingly and consistently rather than scattered at random.

### depth — relief on the exterior faces

Do the walls cast shadows across themselves, or read as flat painted panels?
Pillars, plinths, cornices, belt courses and inset windows should be visible as
relief, not merely present in the JSON. The rule of thumb is no unbroken flat
face longer than 6–8 blocks. A build whose depth techniques are all invisible
from outside scores as if it had none.

### roofline — how deliberately the build's top edge is resolved

Score the treatment the *style* calls for, not the presence of a pitch. Decide
first which kind of building this is, then judge it against its own kind.

**Pitched styles** — cottage, barn, chapel, teahouse, tower. Look for a real
slope rather than a flat cap, a ridge resolving to a 1–2 wide line instead of a
stepped plateau or a wedding-cake of terraces, an overhang clear of the walls by
a block or two, and a roof material that contrasts with the wall below it. A
pyramid whose arithmetic lands on a wide flat top scores 3 or below.

**Flat and roofless styles** — modern villa, desert market row, curtain wall,
bridge, walled yard. There is nothing to pitch, so score what stands in for it:
a parapet or cornice with its own cap course, crenellation, an awning or canopy
line, a railing, a deliberate change of material at the top course, a projecting
eave over a flat deck. A flat roof done properly is a 7 or 8 here.

What scores low is the absence of *any* considered top edge — a wall that simply
stops, a flat plane with nothing at its perimeter, a deck whose edge is the same
block as its surface. Do not mark a build down for lacking a pitch its style
would never have; a bridge has no roof by design, and its parapet and deck edge
are the thing to score.

### detailing — trim, openings, lighting and ground contact

The pass that separates a shape from a building. Windows and doors present,
sized sensibly and aligned with each other. Stairs and slabs used as trim,
sills and chamfers. Visible light sources on the facade — lights hidden under
an overhang count for nothing from outside. A foundation plinth and a softened
ground line so the build meets the terrain instead of sitting on top of it.

### overall — the holistic verdict

Not the average of the five above: this is whether the build works as a whole.
A build can pass every dimension separately and still be incoherent, or carry
one weak dimension and still be lovely. Ask whether you would be pleased to
find this in a world, and whether it reads as the thing it was asked to be.
Where this score and the mean of the others diverge sharply, that gap is itself
the interesting result.
