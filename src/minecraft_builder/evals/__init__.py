"""Measuring whether a change to the guide, the prompts or the linter helped.

Everything else in this repo improves build quality by argument: the style guide
asserts that a 50/30/20 palette looks better, the linter asserts that a flat wall
is a fault, the visual critique asserts that a picture is worth answering. None
of them can tell you whether an edit to any of the three made the *output* better
or worse, and a hunch after looking at two builds is not an answer.

This package renders a fixed set of benchmark builds and scores them against a
fixed rubric, so the same question can be asked twice and the two answers
compared. It deliberately does not generate the builds — a model does that, the
way a user would — so what is measured is the whole pipeline the model is
actually running inside, not a reimplementation of it.
"""
