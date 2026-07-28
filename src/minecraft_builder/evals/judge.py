"""Scoring a rendered build with a vision model.

The judge sees exactly what a human scorer would: the rubric document and the
renders. It never sees the structure JSON, the operation list or the linter's
verdict — a judge that could read the source would be scoring the description of
the build rather than the build, and would quietly reward a model for *claiming*
a plinth it never rendered.

Optional, and opt-in twice over: the ``anthropic`` package is an extra, and the
runner only calls this when asked. Judging costs real money — one request per
build, each carrying every render of it — and a harness that spent it by default
would be run once and then avoided.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Sequence, Tuple

from .rubric import RubricError, load_rubric, parse_scores, score_schema

# One constant, deliberately. Which model grades is the single most important
# variable in whether two runs are comparable, so it is named here and echoed
# into every report rather than defaulted somewhere inside a call.
JUDGE_MODEL = "claude-sonnet-5"

# The reply is a handful of integers and two sentences, but adaptive thinking is
# on by default and shares this budget — a tight cap truncates the reasoning and
# takes the JSON with it.
JUDGE_MAX_TOKENS = 8000

MISSING_ANTHROPIC = """\
Automatic judging needs the anthropic package, which is not installed. It is an
optional extra; rendering and manual scoring work without it.

Install it with:

pip install "minecraft-builder-mcp[eval]\""""

NO_CREDENTIALS = """\
Automatic judging needs Anthropic credentials. The SDK looks for an API key, an
auth token, and then a logged-in profile, and found none of them.

Set one of:

export ANTHROPIC_API_KEY=sk-ant-...

ant auth login"""

JUDGE_SYSTEM = """\
You are grading generated Minecraft builds against a fixed rubric, so that two
runs of the same benchmark set can be compared. Consistency matters more than
generosity: the same build shown to you twice should get the same numbers.

You are shown renders of one build from several angles, and the prompt it was
built from. Score only what the renders show. Do not give credit for anything
you cannot see, and do not penalise the flat-colour materials — every build is
drawn that way, so it cancels out across the set.

The rubric follows in full.

"""


class JudgeError(RuntimeError):
    """Judging failed for a reason the caller can act on."""


def build_client(api_key: str = "") -> Any:
    """An Anthropic client, or an error naming the thing that is missing.

    Credentials are left to the SDK unless one is passed explicitly. An unset
    ``ANTHROPIC_API_KEY`` does not mean there are none — the SDK also resolves an
    auth token and an ``ant auth login`` profile — so checking the environment
    variable here would refuse to run on a machine that is perfectly able to.
    """
    try:
        import anthropic
    except ImportError as error:
        raise JudgeError(MISSING_ANTHROPIC) from error

    try:
        return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    except Exception as error:
        # The SDK raises on construction when it cannot resolve any credential.
        raise JudgeError(f"{NO_CREDENTIALS}\n\n({error})") from error


def judge_prompt(prompt: str, images: Sequence[bytes]) -> list:
    """The user turn: what was asked for, then the pictures of what came back."""
    content: list = [
        {
            "type": "text",
            "text": (
                f"This build was made from the prompt:\n\n{prompt}\n\n"
                f"{len(images)} render(s) follow. Score the build against every "
                "rubric dimension and say, in one or two sentences, the single "
                "worst thing about it and the single best."
            ),
        }
    ]
    for image in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image).decode("ascii"),
            },
        })
    return content


def judge_build(
    client: Any,
    prompt: str,
    images: Sequence[bytes],
    model: str = JUDGE_MODEL,
) -> Tuple[Dict[str, int], str]:
    """Score one build. Returns its scores and the judge's note."""
    if not images:
        raise JudgeError("Nothing to judge — this build produced no renders.")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=JUDGE_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": JUDGE_SYSTEM + load_rubric(),
                # Identical for every build in a run, so it is worth caching even
                # though a short rubric may fall under the model's minimum
                # cacheable prefix and silently not cache.
                "cache_control": {"type": "ephemeral"},
            }],
            # Structured output rather than parsing prose: a judge that returns
            # its scores in a sentence turns every rubric edit into a parser
            # edit, and fails on the one build it decided to be discursive about.
            output_config={"format": {"type": "json_schema", "schema": score_schema()}},
            messages=[{"role": "user", "content": judge_prompt(prompt, images)}],
        )
    except Exception as error:
        raise JudgeError(_explain_api_failure(error)) from error

    return _read_reply(response)


def _read_reply(response: Any) -> Tuple[Dict[str, int], str]:
    """Pull scores out of a response, checking it is one before reading it."""
    if getattr(response, "stop_reason", None) == "refusal":
        raise JudgeError("The judge declined to score this build.")

    text = next(
        (block.text for block in response.content if getattr(block, "type", "") == "text"),
        "",
    )
    if not text:
        raise JudgeError("The judge returned no text to score with.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise JudgeError(f"The judge's reply was not JSON: {error}") from error
    try:
        return parse_scores(payload)
    except RubricError as error:
        raise JudgeError(str(error)) from error


def _explain_api_failure(error: Exception) -> str:
    """Say which kind of failure this was, since the fixes differ.

    Imported lazily and matched by class so a rate limit is not reported as a
    bad API key. Falls back to the message when the SDK is not importable, which
    can only happen if a caller passed their own client.
    """
    try:
        import anthropic
    except ImportError:
        return f"The judge call failed: {error}"

    if isinstance(error, anthropic.AuthenticationError):
        return NO_CREDENTIALS
    if isinstance(error, anthropic.NotFoundError):
        return f"No such model — check the judge model name: {error}"
    if isinstance(error, anthropic.RateLimitError):
        return f"Rate limited. Wait and re-run; scored builds are already written. ({error})"
    if isinstance(error, anthropic.APIConnectionError):
        return f"Could not reach the API: {error}"
    return f"The judge call failed: {error}"
