# Design: Web UI for Minecraft Builder

**Status:** Phases 0–3 built, plus headless rendering (§14); Phase 4 not started
(§13 has the current state)
**Date:** 2026-07-27, revised 2026-07-28

Two stages, deliberately ordered:

- **Stage 1 — local, Claude Code drives it.** A Claude Code session starts the site. You
  type in the browser, the prompt lands in that session, Claude builds, the 3D view updates.
  No API key, no API cost, no auth, no hosting. **This is what gets built first.**
- **Stage 2 — hosted site.** Later. Its own API key and agent loop. Recorded in §11 so
  Stage 1 doesn't paint us into a corner.

---

## 1. The mechanism: two paths, not one

The obvious objection to Stage 1 is that MCP is model-driven — a website cannot push a
prompt into a running Claude session. There are two answers, and the design needs both,
because the more elegant one is not always available.

| Path | How a browser prompt reaches Claude | Requires |
|---|---|---|
| **Channels** (§1.1) | The server pushes an event into the session | Research-preview flag, Anthropic auth, org permission |
| **Polling** (§1.2) | Claude calls `await_prompt`, which blocks until a prompt arrives | Nothing. An ordinary tool call |

This document was originally written assuming channels were *the* mechanism. They are not
available in the environment this was built in — see §1.4 — so `await_prompt` was added and
is the path that actually carries traffic here. Channels remain supported and take
precedence once they have proven they work.

The two are not redundant. Channels leave the terminal session free between messages, which
is the better product; polling occupies it with a wait loop but is subject to no gate
whatsoever. Neither subsumes the other, so both stay.

### 1.1 Channels

> **A channel is an MCP server that pushes events into your running Claude Code session.**
> Channels can be two-way: Claude reads the event and replies back through the same channel.

There is even an official demo channel, **fakechat**, that serves a chat UI on localhost,
pushes what you type into the session, and shows Claude's reply back in the browser. That is
precisely the product shape we want — we are adding a 3D viewport and structure tools to it.

**Contract** (from the [channels reference](https://code.claude.com/docs/en/channels-reference)):

| Piece | Value |
|---|---|
| Capability | `capabilities.experimental["claude/channel"] = {}` — presence registers the listener |
| Push a prompt in | notification `notifications/claude/channel`, params `{content: str, meta: Record<str,str>}` |
| How Claude sees it | `<channel source="minecraft-builder" chat_id="1">build a stone hut</channel>` |
| Claude replies out | a normal MCP tool (conventionally `reply`) that we implement |
| Steer Claude | the `instructions` string on the Server constructor — injected into Claude's system prompt |
| Enable | `claude --dangerously-load-development-channels server:minecraft-builder` |

### 1.2 Polling: the `await_prompt` inversion

Channels invert MCP's direction, which is what makes them gated. Polling gets the same
result without inverting anything: prompts wait in a server-side queue, and Claude collects
them with `await_prompt`, an ordinary tool call that blocks (long-poll, default 240 s per
round, ceiling 540 s to stay inside the MCP client's own timeout). No policy gates a tool
call, so this works on a stock session, on Bedrock/Vertex/Foundry, and with no flag.

Claude runs it as a loop: call `await_prompt`, handle whatever comes back with
`show_structure`, answer with `reply`, call `await_prompt` again. A timeout is not an error,
just a quiet round. The `instructions` string teaches this loop, same as it teaches the
channel workflow.

The cost is that the terminal session is occupied while the loop runs, and each round is a
tool call. That is a real downside and the reason channels are still preferred when they
work.

**Delivery has three grades here**, which is what lets the UI stop guessing (§4.3):

- `waiting` — an `await_prompt` call is blocked on the queue right now. A prompt enqueued
  this instant arrives in milliseconds.
- `polling` — nobody is blocked, but a take happened within the grace window (900 s, which
  covers a full wait round plus the build-and-reply work between two rounds), so the loop is
  between rounds and will be back.
- neither — the prompt is stored, but nothing suggests anyone will collect it.

### 1.3 Verified: this works from Python

The documented examples are all Bun, and the reference says the only hard requirement is
"the MCP SDK and a Node.js-compatible runtime". That would have forced a second process,
because our core is Python. It turns out not to be a constraint — the Python SDK does both
halves. Checked against the SDK in `.venv` and against the real `server.py`:

```python
app.create_initialization_options(NotificationOptions(), {"claude/channel": {}})
# -> {"experimental": {"claude/channel": {}}, "tools": {"listChanged": false}}
```

and a plain Pydantic model serializes to the exact frame the contract specifies:

```json
{"method":"notifications/claude/channel",
 "params":{"content":"build me a stone hut","meta":{"chat_id":"1","sender":"web"}},
 "jsonrpc":"2.0"}
```

**So Stage 1 is a single Python process**: existing MCP server + channel capability +
localhost HTTP/SSE + static UI, importing `schema.py` and `converter.py` directly. No Bun,
no IPC, no duplicated geometry model.

`ServerSession.send_notification` is typed `SendNotificationT` but only calls
`.model_dump()` on it, so a custom notification model passes at runtime. Pin the `mcp`
version and add a test asserting the serialized frame, since this relies on the SDK not
tightening that annotation.

### 1.4 Preview caveats — read before committing

**These apply to channels only.** Polling (§1.2) is subject to none of them, which is the
whole reason it exists.

- **Research preview.** The `--channels` flag syntax and the protocol contract may change.
  Neither flag appears in `claude --help`.
- **Custom channels are not on the allowlist**, so ours needs
  `--dangerously-load-development-channels server:minecraft-builder`. The `server:` prefix is
  for a bare `.mcp.json` entry; `plugin:` is for a packaged plugin. Getting on the real
  allowlist requires an Anthropic partner contact — not a path we should plan around.
- **Requires Anthropic auth** via claude.ai or a Console API key. Not available on Bedrock,
  Google Cloud, or Microsoft Foundry.
- **Enabling requires restarting Claude Code.** A channel cannot be turned on mid-session.
- Personal Pro/Max accounts skip the org checks entirely. Team/Enterprise needs an admin to
  set `channelsEnabled`.

**This project hit that last one.** The account this was developed on is on a plan where
channels are disabled, and startup reports *"blocked by org policy … have an administrator
set `channelsEnabled: true`"*. **No code change fixes it** — it needs an Owner at claude.ai →
Admin settings → Claude Code → Channels, and server-delivered policy beats any local
`managed-settings.json`. Do not spend time looking for a workaround; there isn't one. This is
not a footnote, it is why §1.2 exists and why the channel path cannot be the only one.

**The failure mode that will cost the most debugging time:** notifications are
fire-and-forget with no acknowledgement. If the session wasn't started with the flag, or org
policy blocks it, **events are dropped silently** — the browser posts a prompt and nothing
whatsoever happens.

Worse, the drop is invisible from the sending side too. `ChannelBridge.push()` reports that
the frame reached the transport, and the bridge is attached for every stdio session whether
or not the channel is enabled, so a successful write says nothing about whether Claude
received anything. This is not a theoretical concern: trusting `push()` as delivery meant
browser prompts were destroyed outright in exactly this configuration, because the code
treated a successful push as reason not to queue the prompt for `await_prompt` either.
Mitigations in §4.3.

---

## 2. What existed at the start

Kept as written, because the plan below was built on it and the reasoning only makes sense
against this starting point. For the layout as it stands now, see §5.

| File | Lines | Role | Stage 1 use |
|---|---:|---|---|
| `schema.py` | 241 | `MinecraftStructure`, 8 shape ops, `expand()` | **Core.** Tool schema + wire format. |
| `shapes.py` | 192 | Pure geometry generators | **Core, unchanged.** |
| `converter.py` | 73 | `expand()` → Sponge v2 `.schem` | Core; gains `to_litematic()`. |
| `versions.py` | 89 | Version registries + fuzzy block validation | **Core, unchanged.** |
| `paths.py` | 122 | Cross-platform path / file-manager helpers | Used — we are local. |
| `server.py` | 326 | MCP stdio server, 2 tools | **Extended in place** (§4). |
| `data/blocks_*.txt` | 3 | Vendored PrismarineJS registries | Also seeds the renderer colour table. |

`MinecraftStructure.expand()` already returns `Dict[(x,y,z) -> block_id]` — exactly a voxel
renderer's input. The repo is unusually well-shaped for this.

**Central principle:** the operations list is the source code; `.schem`/`.litematic` are
compiled artifacts. The UI edits and versions JSON, renders from `expand()`, and only
compiles on export. Nothing reads a schematic back.

---

## 3. Stage 1 architecture

```
┌──── Browser · http://127.0.0.1:8791 ─────────────────────────────┐
│  chat pane        3D viewport (three.js)      annotation tray    │
└───┬──────────────────────▲───────────────────────┬───────────────┘
    │ POST /api/prompt     │ GET /api/events (SSE) │ POST /annotations
    ▼                      │                       ▼
┌───────────── ONE Python process ─────────────────────────────────┐
│  web/app.py    http.server on 127.0.0.1 — static UI + JSON API   │
│  web/channel.py   PUSH path: notifications/claude/channel  ──┐   │
│  web/prompts.py   PULL path: queue, drained by await_prompt ─┼─┐ │
│  web/chat.py      transcript + SSE bus                       │ │ │
│  web/state.py     current structure + version                │ │ │
│  server.py     reply · await_prompt · show_structure · export │ │ │
│  core/   schema · shapes · converter · versions · lint (imported) │
└──────────────────────────┬───────────────────────────────────┼─┼─┘
                    stdio  │ (Claude Code spawned us)          │ │
                           ▼                                   │ │
                  ┌────────────────────────┐                   │ │
                  │  Claude Code session   │◄──────────────────┘ │
                  │  = the agent. No API   │  <channel …>prompt<…>│
                  │  key, no loop to write │─────────────────────┘
                  └────────────────────────┘   await_prompt returns
                                               the queued prompt
```

Two arrows into the session, and they are genuinely different directions: the channel
**pushes** (server-initiated, gated, unacknowledged), `await_prompt` **is pulled** (Claude
initiates, ungated, and the pull itself is the acknowledgement). Everything else in the
process is shared.

The thing to notice: **there is no agent layer to build.** Stage 1 has no tool-use loop, no
model selection, no prompt caching, no streaming assembly, no token budget, no cost. Claude
Code is the agent. That deletes most of the engineering in the original hosted design and is
why this ordering is right.

**Round trip, channel path:** browser `POST /api/prompt` → notification into the session →
Claude reasons, calls `show_structure(...)` → version bumped, SSE `structure` frame to the
browser → viewport re-renders → Claude calls `reply("added a doorway on the south face")` →
SSE `message` frame → chat pane.

**Round trip, polling path:** Claude is already blocked in `await_prompt` → browser
`POST /api/prompt` → the prompt is queued and the blocked call returns it → identical from
`show_structure` onwards → Claude calls `await_prompt` again.

**Both at once:** the prompt is queued *and* pushed until the channel proves itself, because
a push cannot be distinguished from a silently dropped push (§1.4). Once a `reply` confirms
the channel, the push is trusted alone and the queued insurance copies are dropped, so
`await_prompt` cannot hand back a prompt that has already been answered.

---

## 4. Changes to `server.py`

### 4.1 Declare the channel and instruct Claude

```python
# __main__.py / server.py
async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options(
            NotificationOptions(),
            experimental_capabilities={"claude/channel": {}},
        ))
```

`Server(...)`'s `instructions` is the single most important knob in Stage 1 — it lands in
Claude's system prompt and is how we get the workflow right without the user re-explaining
it every session. It should say roughly:

> Prompts from the Minecraft build UI arrive as `<channel source="minecraft-builder"
> chat_id="…">`. They are build requests. Call `show_structure` to render — the user sees the
> result in 3D immediately, so prefer showing a build over describing one. Use shape
> `operations`, not per-block lists. After showing, call `reply` with one short sentence,
> passing the `chat_id` from the tag. When the user asks you to apply their notes, call
> `get_annotations` first; each annotation names the operation index it refers to, so prefer
> editing that operation over regenerating the whole structure. Only call `export` when asked
> for a file.

### 4.2 Tools

Keep both existing tools (the plain MCP workflow must keep working for users who aren't
running a channel). Add four:

| Tool | Purpose |
|---|---|
| `show_structure` | Accepts a full structure; validates, stores as a new version, pushes to the viewport. **The tool the whole product hangs on.** |
| `patch_operations` | `[{index, action: replace\|insert\|delete, operation}]`. Makes "the roof is too steep" a one-op edit instead of re-emitting 200 ops. |
| `get_annotations` | Open markup, each pre-resolved to an operation index + summary (§6.1, §8). |
| `reply` | Reply → chat pane. Params `{chat_id, text}` per convention. Also the channel's proof of life: a reply is the only evidence the push round trip closes, so it latches `ChannelBridge.confirm()`. |
| `await_prompt` | Blocks until a browser prompt arrives, then returns it (§1.2). The chat path that needs no flag and no permission. |

Notes:
- Validate through Pydantic inside every tool and return the `ValidationError` text with
  `is_error: true` so Claude self-corrects. Never let it escape as a traceback.
- Reuse `validate_block_ids()` and return unknown blocks with fuzzy suggestions in the result
  — that already works in this repo; keep the behaviour.
- Cap total voxels (suggest 2 000 000) *before* calling `expand()`. A cuboid from
  `[-100000,…]` to `[100000,…]` is a trivial OOM, and here it would take the user's Claude
  Code session down with it.

### 4.3 Liveness — the silent-drop problem

Because notifications are unacknowledged, the browser cannot tell "Claude is thinking" from
"the channel never registered". This section cost more debugging time than the rest of the
design combined, so it is written as what was built, not what was proposed.

**The rule: never paint a claim the server cannot support.** One `_link_status()` answers
"does chat work", and `/api/status`, the SSE snapshot and the `POST /api/prompt` reply all
return it, so they cannot disagree. Its keys divide cleanly into evidence and non-evidence:

| Key | Evidence of delivery? |
|---|---|
| `waiting` | Yes — an `await_prompt` is blocked on the queue right now |
| `polling` | Yes — a take happened within the grace window; the loop is between rounds |
| `confirmed` | Yes — a pushed event came back answered, the only proof the channel works |
| `attached` | **No.** An MCP session exists over stdio. True with the channel disabled, true with it blocked by policy |
| `events_sent`, `queued` | Diagnostics only |

The status dot has three colours, and the middle one is the point: green for the three
evidence keys, **amber** for `attached` alone, red for nothing. Amber is not a failure state —
it means "something is there and nothing has proven it", which is the honest description of a
policy-blocked session. An earlier version ORed `attached` into green and reported a healthy
link through an entire session in which not one prompt was delivered.

- Queue the prompt as well as pushing it until the channel is confirmed. A push that cannot
  be verified must not be the only delivery path; that mistake destroyed prompts outright.
- After ~20 s with no reply, say so in the transcript and name the likely cause, including the
  `await_prompt` escape hatch — it is the fix that always works.
- Copy-pasteable hints must not end in a sentence period. `…server:minecraft-builder.` was
  pasted verbatim and Claude Code looked for a server named `minecraft-builder.`, reporting
  *"no MCP server configured with that name"* — a second, more confusing failure stacked on
  the first.
- Log every outbound notification to stderr — it shows up in
  `~/.claude/debug/<session-id>.txt`.

**Testing note that matters more than it looks:** exercise the *attached* path. The suite
originally ran entirely with the bridge detached, so `push()` never succeeded in a test and a
bug that only appears once a session is attached stayed invisible. A fixture that attaches a
bridge to a live loop with a stream that accepts and discards frames reproduces a
policy-blocked client exactly.

### 4.4 Config

```json
// .mcp.json  — gitignored; copy .mcp.json.example
{"mcpServers": {"minecraft-builder": {
  "command": "/abs/path/to/.venv/bin/python",
  "args": ["-m", "minecraft_builder"], "timeout": 600000}}}
```

**`command` cannot be a bare `python`.** It has to be an interpreter that can
`import minecraft_builder`, which usually means the project virtualenv by absolute path. That
absolute path is also why the file is gitignored rather than committed: a checked-in copy
names one machine's interpreter and breaks every other machine, and the symptom is a server
that silently never connects. `.mcp.json.example` is committed instead.

`.mcp.json` is project-scoped, so starting Claude Code from a git worktree or any other
directory finds no server at all.

Launch: `claude --dangerously-load-development-channels server:minecraft-builder` — or don't,
and use `await_prompt` instead (§1.2), which needs no flag.

Two gotchas worth writing into the README: **`meta` keys must be identifiers** — letters,
digits, underscores; keys with hyphens are *silently dropped*. And if Claude is mid-turn when
several prompts arrive, they are **delivered together on the next turn** and handled as a
group, so the UI should discourage rapid-fire prompting or queue visibly.

The first `reply` call triggers a permission prompt in the terminal. Pre-allowlist
`mcp__minecraft-builder__reply` and `mcp__minecraft-builder__show_structure` in project
settings so the loop doesn't stall on approval every session.

---

## 5. Repo layout

As built. The channel/state modules ended up under `web/` rather than at the package root,
since they exist to serve the browser and nothing else imports them:

```
src/minecraft_builder/          # core stays importable and framework-free
├── schema.py                   # + expand_with_provenance()      (§6.1)
├── shapes.py
├── converter.py                # + to_litematic()                (§9)
├── versions.py
├── colors.py                   # block_id -> RGB                 (§7)
├── lint.py                     # style guide as programmatic checks
├── style.py                    # style guide loader
├── paths.py
├── server.py                   # channel capability + tools      (§4)
└── web/
    ├── app.py                  # localhost HTTP + SSE
    ├── channel.py              # PUSH: notification model, bridge, confirm()
    ├── prompts.py              # PULL: queue drained by await_prompt
    ├── chat.py                 # transcript + SSE event bus
    ├── state.py                # structure versions
    ├── payload.py              # voxel payload + occlusion culling
    ├── render.py               # headless screenshots of the viewer (§14)
    └── static/                 # index.html · viewer.js · style.css
```

The frontend is three hand-written files served as-is, not a build. There is no bundler and
no `web/src/` tree: the assets are re-read per request, so editing `viewer.js` needs a browser
refresh rather than a session restart. Worth keeping unless a real dependency arrives —
`node --check` is the only tooling, since there is no frontend test runner.

---

## 6. Core data-model changes

Both additive; neither changes existing behaviour.

### 6.1 Operation provenance — the change that makes feedback work

Naïve markup gives Claude `{"pos": [7,4,3], "note": "hate this"}`. Weak. Tracking *which
operation placed each block* makes it *"operation #4, the roof pyramid, is too steep"* — a
targeted edit instead of a coordinate guess.

A before/after diff **cannot** recover this: an operation that overwrites a coordinate with
the *same* block ID is invisible to a diff yet is still the last writer. Provenance must be
recorded at write time. Since every `apply()` writes through `blocks[coord] = block`, a
recording dict captures all of them with **no change to any operation class**:

```python
Provenance = Dict[Tuple[int, int, int], int]   # coord -> index in the combined op list


class _RecordingBlockMap(dict):
    """A BlockMap that remembers which operation index last wrote each coordinate."""

    def __init__(self) -> None:
        super().__init__()
        self.origin: Provenance = {}
        self.index = 0          # caller sets this before each operation runs

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self.origin[key] = self.index


def expand_with_provenance(self) -> Tuple[BlockMap, Provenance]:
    """Resolve exactly as expand() does, also returning each coord's last writer.

    Index space: explicit ``blocks`` occupy 0..len(blocks)-1, then ``operations``
    continue from there, matching the order expand() applies them.
    """
    block_map = _RecordingBlockMap()
    for i, b in enumerate(self.blocks):
        block_map.index = i
        block_map[(b.x, b.y, b.z)] = b.block_type
    offset = len(self.blocks)
    for j, operation in enumerate(self.operations):
        block_map.index = offset + j
        operation.apply(block_map)
    return dict(block_map), block_map.origin
```

`expand()` becomes `return self.expand_with_provenance()[0]`, so there is one resolution path
and the two cannot disagree. `ReplaceOp` reads via `blocks.get(c)`, which `dict` provides.

*Prototyped against the current `schema.py` and confirmed: block map identical to
`expand()`; a doorway carved with `air` attributes to the carving op; a wall voxel to the
`hollow_box`; an overwrite with an **identical** block ID correctly attributes to the later op
(a diff reports the earlier one); `replace` and negative coordinates both behave.*

### 6.2 Coordinate space — a real bug waiting to happen

`converter.py:51-58` re-centres the build so its minimum corner sits at the origin. **The
viewer must render in authoring coordinates**, or an annotation on a block maps to the wrong
operation. Authoring coords are canonical everywhere; the min-corner offset is computed only
inside export and never leaves it. Add a regression test that annotates a build with negative
coordinates and asserts the resolved operation index survives an export round-trip.

---

## 7. The 3D viewer

**One `InstancedMesh` per distinct block type**, instance matrices from the `expand()` block
map, interior faces culled (emit a voxel only if one of its 6 neighbours is absent). Handles
the sizes this tool produces comfortably. Add instance-ID raycast picking — required for
annotation.

| Alternative | Verdict |
|---|---|
| [`deepslate`](https://misode.github.io/deepslate/) | Real block models, mature — but *we* supply models + texture atlas. |
| [`lodestone`](https://github.com/mattzh72/lodestone) | On-target, ships a default pack, `ThreeStructureRenderer` — but 21 stars / 34 commits. Too thin for the critical path. Revisit later. |

**Textures.** Stage 1 is local, so a user pointing the tool at their own
`.minecraft/versions/<v>/<v>.jar` is entirely legitimate — nothing is redistributed. Still
ship **flat per-block colours** as the default (`colors.py`, generated from PrismarineJS
minecraft-data — the same source as `data/blocks_*.txt`, so `data/README.md`'s regeneration
script extends naturally). Silhouette plus colour is ~90% of what's needed to judge a build,
and it keeps Stage 2 unblocked, where serving a vanilla atlas from our origin would **not**
be legal. Real textures are an opt-in extra, read from the local jar, never bundled.

---

## 8. Annotation and the feedback loop

```python
class Annotation(BaseModel):
    id: UUID
    structure_version: int          # what was on screen when marked
    kind: Literal["point", "region", "operation", "global"]
    pos: Optional[Vec3]             # point
    start: Optional[Vec3]           # region
    end: Optional[Vec3]
    op_index: Optional[int]         # resolved server-side via provenance
    op_summary: Optional[str]       # 'pyramid centre=[8,5,8] base=6 block=oak_planks'
    note: str
    status: Literal["open", "resolved"] = "open"
```

The server resolves coordinates → `op_index` + `op_summary` **at creation time**, against the
version on screen, using `expand_with_provenance()`. A region resolves to the operations
covering it, ranked by voxel count, keeping the dominant one; the tray lets the user override
the target. `get_annotations` therefore hands Claude something directly actionable.

**Flow:** click a face (point) or shift-drag corners (region) → note popover → marker pinned
in 3D and listed in the tray → batch up several → **Apply notes** posts a canned prompt →
Claude calls `get_annotations` → `patch_operations` → `show_structure` → `reply`.

Batching is not a compromise: events arriving mid-turn are grouped anyway, and users
accumulate several objections before wanting a revision. Don't build a polling mechanism to
fake interruption.

Every accepted revision appends an immutable version so the user can roll back — "actually
the old roof was better" is the most predictable request in this product. Stage 1 keeps
versions in memory plus a JSON file; no database.

---

## 9. Export and the Minecraft side

Today: `.schem` (Sponge v2) only — a **WorldEdit** format (`//schem load` + `//paste`),
instant paste, needs creative/op.

**Add `.litematic`.** Litematica is the mod people mean by "blueprint": a translucent
hologram you build by hand in survival, with a material list. Its native format is
`.litematic`; its `.schem` support is explicitly a hack by the author and absent on 1.13–1.16
([discussion](https://github.com/maruohon/litematica/discussions/332)).
[`litemapy`](https://pypi.org/project/litemapy/) (0.11.0b0, June 2025) writes it, and its
input shape is what `expand()` already returns:

```python
def to_litematic(structure, output_path, version=DEFAULT_VERSION) -> str:
    from litemapy import Region, BlockState
    block_map = structure.expand()
    xs = [c[0] for c in block_map]; ys = [c[1] for c in block_map]; zs = [c[2] for c in block_map]
    reg = Region(0, 0, 0,
                 max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, max(zs) - min(zs) + 1)
    for (x, y, z), block_id in block_map.items():
        reg[x - min(xs), y - min(ys), z - min(zs)] = BlockState(
            SchematicConverter.normalize_block_id(block_id))
    ...
```

Pin `litemapy` with an upper bound — it is beta, and a writer regression would be silent (the
file loads, the build is wrong). Add a round-trip test comparing readback against `expand()`.

Because Stage 1 is local, `paths.py` can write **straight into
`.minecraft/schematics/`** — "copy into the game" becomes zero steps. Emit a material list
(block counts from `expand()`) with every export; it costs nothing and Litematica users need
it.

---

## 10. Security (Stage 1)

- Bind HTTP to `127.0.0.1` explicitly, never `0.0.0.0`. An open channel endpoint is a prompt
  injection vector into a session that can run `Bash` on the user's machine.
- Single local user, so no sender allowlist is needed — but that assumption *is* the security
  model, so don't add a remote-reachable transport without revisiting it.
- Voxel and operation caps enforced inside the tools (§4.2), so a runaway build can't OOM the
  session.
- `expand()` is CPU-bound; run large expansions and exports in a thread with a timeout so the
  stdio loop stays responsive.
- Do not declare `claude/channel/permission` (permission relay). It would let anything that
  can POST to localhost approve tool use in the session. No benefit for a local UI.

---

## 11. Stage 2: what changes when it's hosted

Recorded so Stage 1 doesn't foreclose it. Everything in §5–§9 carries over unchanged; what
gets *added* is the agent layer Stage 1 doesn't need.

- **Replace the channel with an agent loop.** FastAPI + `client.beta.messages.tool_runner`,
  the same tools promoted to `strict: true` API tool definitions. Model `claude-opus-5`
  ($5/$25 per MTok), adaptive thinking, `effort: "high"` to start then sweep, streaming with
  `max_tokens` ≥ 32000 — note thinking and text share that budget on Opus 5.
- **Prompt caching is mandatory**, roughly halving input cost on multi-turn sessions. One
  breakpoint on the last system block covers tools + system; volatile content goes after it.
  Three silent cache-killers to avoid: structure JSON in the system prompt, per-user tool
  sets, timestamps in the prefix. Assert `cache_read_input_tokens > 0` in staging.
- **Cost, illustrative** (~5K cached prefix, ~1.5K fresh input and ~2.5K output per turn):
  one-shot build ~$0.20, build + 3 revisions ~$1.00, heavy session ~$3.50. **Estimates —
  price on `count_tokens` against real transcripts.** `task_budget` (min 20 000) is the
  per-user quota mechanism; meter output tokens and hard-stop at the cap.
- **Textures become a hard constraint.** Vanilla assets cannot be served from our origin.
  Flat colours by default; user-supplied jar unpacked **in the browser** only.
- Postgres (structures as JSONB, append-only versions), OAuth, object storage with signed
  expiring URLs, per-user and per-IP rate limits. Never expose the API key to the client.

The reason to build Stage 1 first is not just that it's cheaper: it validates the two things
Stage 2 can't tell us in advance — whether flat-colour fidelity is enough to judge a build,
and whether operation-level annotation actually produces good revisions.

---

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Channels are a research preview; contract may change | **High** | Isolate all channel code in `web/channel.py`. Pin `mcp`. Test asserting the wire frame. The MCP tools keep working without the channel, so a break degrades rather than bricks. `await_prompt` is not affected at all. |
| Channels unavailable — org policy, Bedrock/Vertex/Foundry, or no flag | **Materialised.** Blocked by org policy on the development account | `await_prompt` (§1.2). This is no longer a risk so much as the normal case, which is why polling is a first-class path rather than a fallback. |
| Custom channels need `--dangerously-load-development-channels` indefinitely | Medium | Accept it for a personal tool. Document the flag prominently. Don't plan around allowlisting. |
| Silent event drop when the flag is missing | **Materialised, and worse than predicted** | It ate an entire session, and the design's own mitigation was the thing that broke: treating a successful `push()` as delivery meant prompts were never queued and were destroyed outright. §4.3 — evidence only, queue until confirmed, and test the attached path. |
| Flat colours aren't enough to judge a build | Medium | Phase 1 exists to answer this before more is built. Local jar extraction is the escape hatch. |
| Python SDK tightens `SendNotificationT` typing | Low | Pinned `mcp` + serialization test. |
| `litemapy` beta regression corrupts blueprints silently | Medium | Pin, round-trip test, manual in-game check per release. |
| Runaway `expand()` OOMs the user's Claude Code session | Medium | Caps enforced in-tool before expansion. |

---

## 13. Milestones

**Phase 0 — core, no UI. ✅ Done.** `expand_with_provenance()` + tests · `to_litematic()` +
`output_formats` on the existing tool + round-trip test · `colors.py` + generation script ·
voxel/op caps. *Every item improves the current MCP server on its own and carries no channel
risk. Land this regardless of what happens to the rest of the plan.*

**Phase 1 — viewer, no channel. ✅ Done, and gone past.** `web/app.py` serving the UI, three.js
`InstancedMesh` renderer, orbit/pan/zoom, fed by `show_structure` called the ordinary way.
The fidelity question it existed to answer came back "flat colours are not quite enough", so
the viewer also gained partial-block geometry (stairs, slabs, fences, panes and the rest as
real shapes with orientation parsed from block states), generated per-material texture maps,
sky/fog/sun-shadow, and occlusion culling that only treats full opaque cubes as enclosing.

**Phase 2 — browser → session. ✅ Done, both paths.** Capability declaration,
`web/channel.py`, `POST /api/prompt`, `GET /api/events` SSE, chat pane, `reply`,
`instructions` tuning. Then, once channels turned out to be blocked here (§1.4),
`web/prompts.py` and `await_prompt` — which is what actually carries traffic on this account.
The liveness work in §4.3 belongs to this phase and was the expensive part: proof-of-delivery
for the channel, an honest three-colour status dot, and queueing until the channel is
confirmed.

Also landed alongside, unplanned: `lint.py`, the style guide encoded as programmatic checks,
appended to every `create_minecraft_structure` and `show_structure` result so builds get
reviewed at the moment the feedback is actionable.

**Phase 3 — annotation loop. ✅ Done.** The differentiating feature, as designed in §8:
`web/annotations.py` (model, store, resolution), `patches.py` (targeted operation edits),
raycast picking and Shift-click box select in `viewer.js`, the tray with its **Apply notes**
button, and the `get_annotations` / `patch_operations` / `resolve_annotations` tools.

Three decisions worth recording, all of them things the naive implementation gets wrong:

- **Resolution happens at creation, not at read.** The user marked what was on screen. Resolve
  when Claude asks and a revision in between silently repoints the note. Annotations therefore
  capture their version and resolve immediately, and `get_annotations` warns when a note
  predates the version now showing rather than patching a stale index in silence.
- **Patch indices refer to the pre-patch structure.** A batch of notes is resolved against one
  version, so a batch of patches must be too. Applying them one at a time is the obvious
  implementation and it corrupts the batch: one delete makes every later index off by one.
- **Picking goes through the renderer's per-instance records, not the hit point.** Rounding an
  intersection to a cell is wrong for every partial block, whose geometry does not fill its
  cell and whose surface can sit inside a neighbour. `instanceId` indexes straight back to the
  voxel that produced the instance.

Region resolution picks the operation owning the most voxels — a box round a roof always clips
a wall — reports the coverage share and what else it touched, and breaks ties toward the
*later* operation, since that is the one drawn on top and therefore the one the user clicked.

Not done from §8: **version rollback**. `ViewerState` keeps the last 20 versions and can now
fetch one by number, so the data is there; nothing exposes "the old roof was better" yet.

**Phase 4 — export polish. ⬜ Not started.** Direct write to `.minecraft/schematics/`,
material list, format picker, import instructions per format.

**Stage 2 (later).** §11.

---

## 14. Rendering for the model (`web/render.py`)

Unplanned, and it closes a gap the rest of the design left open. Phases 1–3 all
point the same way: the *user* can see the build, and the model cannot. §7 even
opens by asking whether flat colours are enough "to judge a build" — a question
only the person at the browser was ever in a position to answer.

`render_structure` drives the viewer in a headless Chromium and returns PNGs as
MCP image content, so the model reviews its own work before the user has to.

Four decisions, each the opposite of the obvious implementation:

- **Drive the real page, not a renderer of our own.** `?render=1` hides the
  chrome, drops the live connections and exposes `window.mcbRender`. A dedicated
  offscreen renderer would be a second thing to keep in step with `viewer.js`,
  and its disagreements would be invisible: the model would review a picture the
  user never sees. §12's "own three.js renderer" reasoning applies twice over
  here.
- **Serve the payload, do not store it.** The driver answers `/api/structure`
  itself. Pushing through `ViewerState` works and is wrong — it would bump the
  version, replace what the user is looking at, and repoint every note not yet
  applied (§8: resolution happens at creation, and a silent revision underneath
  it is exactly the failure that rule exists to prevent).
- **Framing maths in Python, a dumb camera in the browser.** The page is handed
  a position and a target. This is the part where a mistake produces five
  plausible pictures of the wrong thing, so it is the part that has to be
  testable without a browser.
- **No animation loop in render mode.** Chromium has no GPU here and
  software-rasterises every frame, so an idle `requestAnimationFrame` loop leaves
  each screenshot queueing behind it: 45 seconds for five views, against 7 with
  the loop stopped and `preserveDrawingBuffer` on. The reverse of what is right
  for an interactive page, which is why it is conditional rather than a change to
  the viewer.

Playwright is an optional extra. The CDN import map (§7) is now load-bearing for
a *tool*, not just for the user's page, so an offline machine gets a page that
loads, runs nothing and reports nothing — `_explain_stall()` watches
`requestfailed` and names that specific cause rather than timing out mutely.
Vendoring three.js would remove the last network dependency and is the obvious
next move if rendering is ever wanted offline or in CI.

---

## Appendix: decisions and rationale

| Decision | Rationale |
|---|---|
| Stage 1 local via channels, hosting later | Deletes the entire agent layer, API cost, auth, and texture-licensing problem. Validates the two open product questions first. |
| One Python process, not Bun + Python | Verified the Python SDK can declare the capability and emit the notification. Avoids splitting state across processes and duplicating the geometry model. |
| Channel code isolated in `web/channel.py` | It's the only research-preview surface. Everything else must survive a contract change. |
| **Two delivery paths, not one** | Channels are gated by org policy and unavailable on Bedrock/Vertex/Foundry — on the account this was built on, they are simply off. `await_prompt` is subject to no gate because it is an ordinary tool call. Channels are better when available (the session stays free); polling always works. Neither subsumes the other. |
| **Green means proven, never merely plausible** | Channel events are unacknowledged, so an attached session is not evidence of delivery. Painting it green reported a healthy link through a whole session in which nothing arrived. Amber for "unproven" is the only honest option, and it costs nothing because the prompt is queued anyway. |
| **A reply is what confirms the channel** | The one signal that travels back. Guarded so it only counts after an event was actually pushed — Claude calls `reply` from ordinary terminal turns and from the `await_prompt` loop, neither of which involves a channel — and latched, since a transport going away is not evidence the channel never worked. |
| **Queue as well as push, until confirmed** | A push that cannot be verified must not be the sole delivery path. Skipping the queue on an unverifiable push destroyed prompts outright. One duplicate on the first exchange of a proven channel is a far cheaper failure than losing every prompt. |
| `.mcp.json` gitignored, `.example` committed | Its `command` is an absolute path to one machine's interpreter. Committing it breaks every other machine, and the symptom is a server that silently never connects. |
| Keep the existing MCP tools working | A channel break degrades to the current product instead of bricking it. |
| Operations JSON as source of truth | Schematics are compiled output; editing JSON is what makes revision cheap and diffable. |
| Own three.js renderer | No asset-licensing problem, no thin dependency in the critical path. |
| Operation provenance for annotations | Turns vague dissatisfaction into a targeted single-operation edit. |
| **Screenshot the real viewer instead of rendering separately** | A second renderer is a second thing to keep in step with `viewer.js`, and a divergence would be silent — the model would review a picture the user never sees. Costs a browser dependency, which is why it is an optional extra. |
| **Rendering never touches `ViewerState`** | Asking for a picture must not bump the version, replace what is on screen, or repoint an unapplied note. The payload is served to the headless page instead. |
| `patch_operations` alongside `show_structure` | "Make the roof steeper" costs one op edit, not a 200-op rewrite. |
| Batched "Apply notes" | Mid-turn events are grouped by Claude Code anyway, and users batch objections naturally. |
| Flat colours default even locally | Keeps Stage 2 legal and Phase 1 cheap; local jar extraction is an opt-in extra. |
| No permission relay | Anything that can POST to localhost would be able to approve tool use in the session. |
