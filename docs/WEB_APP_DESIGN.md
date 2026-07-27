# Design: Hosted Web App for Minecraft Builder

**Status:** proposal
**Date:** 2026-07-27
**Decision taken:** standalone hosted website with its own Claude API key (not a local
companion to Claude Desktop/Code).

---

## 1. Purpose and scope

Turn this repo from an MCP server that writes `.schem` files into a hosted product where a
user can:

1. Describe a build in natural language and watch it appear in **3D in the browser**.
2. **Mark up** what they don't like — click a block, drag a box, add a note.
3. Say "apply my notes" and have the build revised in place.
4. **Export** to a file that drops straight into Minecraft, including a blueprint-mod
   format (`.litematic`) so the build can be built by hand in survival.

Out of scope for v1: multiplayer/collaborative editing, in-browser manual block placement
(the model is the editor), server-side Minecraft integration, mobile.

**Existing surfaces are kept.** The MCP server stays and becomes a second thin client over
the same core (§4). Both must not diverge.

---

## 2. What exists today

| File | Lines | Role | Reuse in web app |
|---|---:|---|---|
| `schema.py` | 241 | Pydantic models: `MinecraftStructure`, 8 shape ops, `expand()` | **Core.** Becomes the agent's tool schema *and* the API wire format. |
| `shapes.py` | 192 | Pure geometry generators, coordinate iterators | **Core, unchanged.** |
| `converter.py` | 73 | `expand()` → Sponge v2 `.schem` via `mcschematic` | Core; gains a `.litematic` sibling. |
| `versions.py` | 89 | 1.19.4 / 1.20.4 / 1.21.4 registries, fuzzy block-ID validation | **Core, unchanged.** Feeds a validation tool result. |
| `paths.py` | 122 | Cross-platform path + file-manager helpers | Local/MCP only. Not used server-side. |
| `server.py` | 326 | MCP stdio server, 2 tools | Stays as one of two clients. |
| `data/blocks_*.txt` | 3 files | Vendored block registries from PrismarineJS minecraft-data | Also seeds the renderer colour table (§7). |

The important property: **`MinecraftStructure.expand()` already returns exactly what a voxel
renderer needs** — `Dict[(x, y, z) -> block_id_string]`. The repo is unusually well-shaped
for this.

### The central design principle

The **operations list is the source code**; `.schem` / `.litematic` are compiled binaries.
The web app edits and versions the JSON, renders from `expand()`, and only compiles on
export. Nothing in the product should read a schematic file back.

---

## 3. Architecture

```
┌──────────────────────── Browser (React + TS) ────────────────────────┐
│  Chat pane        3D viewport (three.js)      Annotation tray        │
│      │                    │                          │              │
│      │  POST /chat        │  structure JSON          │ POST /annot.  │
│      │  (SSE down)        │  (from SSE events)       │              │
└──────┼────────────────────┴──────────────────────────┴──────────────┘
       │
┌──────▼─────────────────── FastAPI (Python 3.11+) ───────────────────┐
│  routes/          chat (SSE) · structures · annotations · export     │
│  agent/           Claude tool-use loop  ──►  Anthropic API          │
│  tools/           6 custom tools (§6.2) — the only thing Claude sees │
│  core/  ◄── existing src/minecraft_builder (schema, shapes, convert) │
│  store/           Postgres: users, structures, versions, annotations │
│  export/          .schem (mcschematic) · .litematic (litemapy)       │
└──────┬──────────────────────────────────────────────────────────────┘
       │
   Object storage (exported files, 24h signed URLs)
```

**Why Python for the backend:** `schema.py` is the tool schema. Rewriting the operation
model in TypeScript would mean maintaining two definitions of the geometry and guaranteeing
they drift. FastAPI + Pydantic v2 is already the stack this repo implies.

---

## 4. Repo layout

Keep the core importable and framework-free; add the web app beside it.

```
src/minecraft_builder/          # unchanged public core
├── schema.py                   # + expand_with_provenance()   (§5.1)
├── shapes.py
├── converter.py                # + to_litematic()             (§9)
├── versions.py
├── colors.py                   # NEW: block_id -> RGB          (§7)
├── paths.py                    # local/MCP only
└── server.py                   # MCP client (unchanged behaviour)

src/minecraft_web/              # NEW: the hosted app
├── main.py                     # FastAPI app factory
├── settings.py                 # pydantic-settings; no secrets in code
├── routes/
│   ├── chat.py                 # POST /api/chat  -> SSE stream
│   ├── structures.py           # CRUD + version history
│   ├── annotations.py          # create / list / resolve
│   └── export.py               # POST /api/export -> signed URLs
├── agent/
│   ├── loop.py                 # Claude tool-use loop
│   ├── prompt.py               # system prompt (STABLE — see §6.3)
│   └── events.py               # SSE event envelope
├── tools/
│   └── structure_tools.py      # the 6 tools
├── store/
│   ├── models.py               # SQLAlchemy
│   └── repo.py
└── export/
    └── artifacts.py

web/                            # NEW: frontend
├── src/render/                 # three.js InstancedMesh voxel renderer
├── src/annotate/               # picking, box select, notes
├── src/chat/
└── src/api/                    # typed client, generated from OpenAPI
```

---

## 5. Core data-model changes

Two small additive changes to `src/minecraft_builder`. Neither breaks the MCP server.

### 5.1 Operation provenance — the change that makes feedback work

Naïve markup gives the model `{"pos": [7,4,3], "note": "hate this"}`. Weak. If we track
*which operation placed each block*, markup becomes *"operation #4, the roof pyramid, is
too steep"* — a targeted edit to one operation instead of a coordinate guess. This is the
highest-value change in the whole design and it is ~15 lines.

A before/after diff of the block map cannot recover this: an operation that overwrites a
coordinate with the *same* block ID is invisible to a diff, yet it is still the last writer.
Provenance has to be recorded at write time. Since every `apply()` implementation writes via
`blocks[coord] = block`, a recording dict captures all of them with **no change to any
operation class**:

```python
# schema.py — additive; expand() keeps its current signature and behaviour.
Provenance = Dict[Tuple[int, int, int], int]   # coord -> index into a combined op list


class _RecordingBlockMap(dict):
    """A BlockMap that remembers which operation index last wrote each coordinate.

    Every ``_Operation.apply()`` writes through ``blocks[coord] = block``, so
    overriding ``__setitem__`` records provenance for all of them — including
    overwrites with an identical block ID, which a before/after diff would miss.
    """

    def __init__(self) -> None:
        super().__init__()
        self.origin: Provenance = {}
        self.index = 0          # set by the caller before each operation runs

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

`expand()` then becomes `return self.expand_with_provenance()[0]`, so there is exactly one
resolution path and the two can never disagree. `ReplaceOp` reads via `blocks.get(c)`, which
`dict` provides unchanged.

*Prototyped against the current `schema.py` and confirmed: block map identical to
`expand()`; a doorway carved with `air` attributes to the carving op; a wall voxel to the
`hollow_box`; an overwrite with an **identical** block ID correctly attributes to the later
op (a diff reports the earlier one); `replace` and negative coordinates both behave.*

### 5.2 Coordinate space — a real bug waiting to happen

`converter.py:51-58` re-centres the build so its minimum corner sits at the origin. **The
viewer must render in authoring coordinates**, not export coordinates, or an annotation on
a block will map to the wrong operation.

Rule: authoring coords are canonical everywhere in the product (API, viewer, annotations,
model context). The min-corner offset is computed *only* inside the export step and never
leaves it. Add a regression test that annotates a build with negative coordinates and
asserts the resolved operation index is stable across an export round-trip.

---

## 6. The agent layer

### 6.1 Model configuration

| Setting | Value | Why |
|---|---|---|
| Model | `claude-opus-5` | Spatial reasoning + multi-step tool use is the hard part of this product. |
| Thinking | `{"type": "adaptive"}` | Default on Opus 5. **`max_tokens` caps thinking + text together** — size it generously. |
| `max_tokens` | `32000`, streaming | Must stream above ~16K or the SDK hits HTTP timeouts. |
| `output_config.effort` | `"high"` to start | Sweep `medium` / `high` / `xhigh` on a real eval set; `low`/`medium` are unusually strong on Opus 5 and are the main cost lever. |
| `thinking.display` | `"summarized"` | We show a "thinking…" trace in the chat pane; the default `"omitted"` returns empty text and reads as a dead pause. |
| `task_budget` | per-request, ≥20 000 | Bounds cumulative spend across the loop and lets the model pace itself instead of being cut off. See §11. |
| `fallbacks` | `"default"` | Cheap insurance. Unlikely to fire for Minecraft builds, but a classifier refusal returns HTTP 200 with `stop_reason: "refusal"` and empty `content` — code that reads `content[0]` would crash. |

```python
# agent/loop.py — shape only
runner = client.beta.messages.tool_runner(
    model="claude-opus-5",
    max_tokens=32_000,
    betas=["task-budgets-2026-03-13"],
    system=[{"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],
    output_config={"effort": "high",
                   "task_budget": {"type": "tokens", "total": budget}},
    thinking={"type": "adaptive", "display": "summarized"},
    tools=STRUCTURE_TOOLS,
    messages=history,
    stream=True,
)
```

**Use the SDK Tool Runner, not a hand-written loop.** It drives request → execute → repeat
for us, supports streaming, and its per-turn hooks cover everything we need (inspecting
results before they return, adding `cache_control`, bounding iterations). The `pause_turn`
caveat that complicates the Python runner applies to *server-side* tools; we have only
custom tools, so it cannot occur here.

### 6.2 Tool surface — six tools, and no filesystem

The tool surface is the product's real API. Design it so the model can do surgical edits,
not just full rewrites.

| Tool | Purpose | Notes |
|---|---|---|
| `put_structure` | Replace the whole structure (`name`, `description`, `operations`, `blocks`) | Used for the first build and for wholesale redesigns. |
| `patch_operations` | Ordered list of `{index, action: replace\|insert\|delete, operation}` | **The feedback workhorse.** Lets "make the roof steeper" cost one op edit instead of re-emitting 200. |
| `get_structure` | Read current state + per-op block counts | Cheap re-grounding after a gap. |
| `get_annotations` | Pull open user markup, each already resolved to an operation index | The feedback channel (§8). |
| `resolve_annotations` | Close annotations with a note on what changed | Drives the UI's "addressed" state. |
| `export_structure` | Compile to requested formats + version | Returns signed download URLs. |

Every tool is declared `strict: true` with `additionalProperties: false` and explicit
`required`. Notes:

- **Schema constraint gap.** Strict tool use rejects numerical constraints (`minimum`,
  `maximum`) and array-length constraints. Our schema has both — `radius: ge=0`, and
  `Vec3 = Annotated[List[int], Field(min_length=3, max_length=3)]`. The Python SDK strips
  these from the schema it sends and validates client-side, so the model is *not* prevented
  from emitting a 2-element vector. Every tool therefore validates through Pydantic and, on
  failure, returns `tool_result` with `is_error: true` and the Pydantic message verbatim so
  the model self-corrects. Do not let a `ValidationError` escape the tool function.
- **Block validation is a tool result, not a hard failure.** Reuse `validate_block_ids()`;
  return unknown blocks with fuzzy suggestions in the result so the model can fix its own
  typos mid-loop. This is already the MCP server's behaviour — keep it.
- **Do not expose a file-write tool.** Persistence is our concern, not the model's.
- Tool descriptions should be *prescriptive about when to call*, e.g. "Call
  `patch_operations` rather than `put_structure` whenever fewer than half the operations
  change." Opus 5 responds well to trigger conditions in descriptions.

### 6.3 Prompt caching

Render order is `tools` → `system` → `messages`, and caching is a **prefix match** — one
changed byte invalidates everything after it.

- **Stable prefix:** the 6 tool schemas (fixed, deterministically ordered) + the system
  prompt (build guidance, operation reference, block palette advice). One `cache_control`
  breakpoint on the last system block covers both. Comfortably over Opus 5's 512-token
  minimum.
- **Volatile content goes in `messages`, after the breakpoint:** current structure state,
  annotations, user text.
- **Second breakpoint** on the last content block of the newest turn, so long revision
  sessions accrue cache hits incrementally.

Three traps to avoid, all of which silently destroy the cache:

1. **Never interpolate the structure JSON into the system prompt.** It changes every turn
   and sits ahead of everything. It belongs in a tool result.
2. **Never interpolate a timestamp, user ID, or session ID into the system prompt.** Same
   reason, and it also prevents any cross-user sharing of the prefix.
3. **Keep the tool list identical for every user and every request.** Tools render at
   position 0; a per-user tool set means nothing ever caches.

Verify in staging by asserting `usage.cache_read_input_tokens > 0` on the second request of
a session. If it is zero, one of the three above is happening.

### 6.4 Streaming to the browser

One SSE stream per chat turn. Typed envelope so the frontend can drive both panes from one
connection:

```ts
type AgentEvent =
  | { t: "thinking";  text: string }              // summarized reasoning delta
  | { t: "text";      text: string }              // assistant message delta
  | { t: "tool_call"; name: string; label: string }
  | { t: "structure"; version: number; structure: Structure }  // -> re-render 3D
  | { t: "warning";   blocks: Record<string, string[]> }       // unknown block ids
  | { t: "usage";     input: number; output: number; cost_cents: number }
  | { t: "done";      stop_reason: string }
  | { t: "error";     message: string }
```

`structure` events are emitted by the `put_structure` / `patch_operations` tool functions
pushing onto an `asyncio.Queue` that the SSE handler drains. The viewport updates *during*
the model's turn, not after it — which is most of the "watch it get built" feel.

---

## 7. The 3D viewer

### 7.1 Renderer

**Build it directly on three.js: one `InstancedMesh` per distinct block type**, instance
matrices from the `expand()` block map, with interior faces culled (only emit a voxel if at
least one of its 6 neighbours is absent). This handles the sizes this tool produces
(thousands to low tens of thousands of voxels) comfortably and keeps us free of a
thin-maintenance dependency.

Evaluated alternatives:

| Option | Fidelity | Verdict |
|---|---|---|
| Own `InstancedMesh` renderer | Flat-shaded blocky preview, correct silhouette | **Chosen.** No asset problem, full control, small. |
| [`deepslate`](https://misode.github.io/deepslate/) | Real Minecraft block models | Mature, but *we* must supply models + texture atlas — which is the licensing problem below. |
| [`lodestone`](https://github.com/mattzh72/lodestone) | Real models, ships a default pack, `ThreeStructureRenderer` | On-target but 21 stars / 34 commits. Too thin a dependency for a hosted product's critical path. Revisit later. |

Add instance-ID picking (`raycaster` against the instanced meshes) — required for
annotation (§8).

### 7.2 Textures: a hard constraint for a hosted product

**Vanilla Minecraft textures are Mojang's and cannot be redistributed from our servers.**
This was a non-issue for a local tool and is a real one now. Three viable paths:

1. **Flat per-block colours (default, ship this).** Add `src/minecraft_builder/colors.py`
   mapping block ID → RGB, generated from PrismarineJS minecraft-data — the *same source*
   as the vendored `data/blocks_*.txt`, so `data/README.md`'s regeneration script extends
   naturally to it. Fall back to a hand-tuned table for blocks without usable colour data.
   Zero legal exposure, and for judging "this roof is wrong" silhouette + colour is ~90% of
   the value.
2. **User-supplied resource pack (opt-in, phase 3).** The user picks their own
   `.minecraft/versions/<v>/<v>.jar`; we unzip and build the atlas **entirely in the
   browser** and cache it in IndexedDB. The assets never reach our server, so we are not
   storing or distributing them. This is the clean way to offer real textures.
3. Openly-licensed resource pack — viable, but looks like neither vanilla nor our own
   thing. Not recommended.

Ship 1, add 2 behind a toggle. Never ship a vanilla atlas from our origin.

---

## 8. Annotation and the feedback loop

### 8.1 Annotation schema

```python
class Annotation(BaseModel):
    id: UUID
    structure_version: int          # which version was on screen when marked
    kind: Literal["point", "region", "operation", "global"]
    pos: Optional[Vec3]             # kind="point"
    start: Optional[Vec3]           # kind="region"
    end: Optional[Vec3]
    op_index: Optional[int]         # resolved server-side via provenance
    op_summary: Optional[str]       # e.g. 'pyramid centre=[8,5,8] base=6 block=oak_planks'
    note: str
    status: Literal["open", "resolved"] = "open"
```

The server resolves `pos` / `start`+`end` → `op_index` + `op_summary` using
`expand_with_provenance()` (§5.1) **at creation time**, against the version that was on
screen. A region annotation resolves to the set of operations covering it, ranked by voxel
count, keeping the dominant one.

`get_annotations` therefore hands the model something directly actionable:

```json
{"id": "…", "kind": "region", "op_index": 4,
 "op_summary": "pyramid centre=[8,5,8] base=6 axis=y block=oak_planks",
 "note": "roof is too steep and the wrong material"}
```

### 8.2 Interaction

1. User clicks a block face (point) or shift-drags two corners (region) in the viewport.
2. A note popover opens; the annotation is created and pinned as a marker in 3D. The tray
   lists all open annotations with the operation each resolved to.
3. User batches up several complaints, then sends "apply my notes" — or presses **Apply
   notes**, which posts a canned message.
4. The agent calls `get_annotations` → `patch_operations` → `resolve_annotations`. Each
   marker flips to "addressed" with the model's note on what it changed.

**Why a button and not automatic:** the agent loop is driven by a request; the browser
cannot interrupt a turn in progress. Batching is also better UX — users accumulate several
objections before wanting a revision. Do not build a polling mechanism to fake
interruption.

Every accepted revision writes a new immutable `structure_version` row, so the user can
diff and roll back. This matters — "actually the old roof was better" is the single most
predictable request in this product.

---

## 9. Export and the Minecraft side

### 9.1 What works today

`.schem` (Sponge v2) only, which is a **WorldEdit** format: `//schem load x` + `//paste`.
Instant paste, requires creative/op.

### 9.2 Add `.litematic` — the blueprint-mod path

**Litematica** is the mod users mean by "blueprint": it renders a translucent hologram in
the world that you build by hand in survival, with a material list and progress overlay.
Its native format is `.litematic`. It can load `.schem` on 1.17+, but the author describes
that as a "quick hax" and 1.13–1.16 cannot load Sponge schematics at all
([discussion](https://github.com/maruohon/litematica/discussions/332)). Native output
removes the question.

[`litemapy`](https://pypi.org/project/litemapy/) writes `.litematic` from Python (0.11.0b0,
June 2025). Its input shape — set blocks by coordinate — is exactly what `expand()`
returns:

```python
# converter.py
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

Pin `litemapy` with an explicit upper bound — it is a beta release, and a `.litematic`
writer regression would be silent (the file loads, the build is wrong). Add a round-trip
test that reads back what it wrote and compares against `expand()`.

`export_structure` returns one signed URL per requested format, plus copy-paste import
instructions per format:

| Format | Mod | In-game |
|---|---|---|
| `.litematic` | Litematica | drop in `.minecraft/schematics/`, load as a placement, build against the hologram |
| `.schem` | WorldEdit 7.x | `//schem load <name>` then `//paste` |

Also emit a **material list** (block counts from `expand()`) in the export response — it
costs nothing, Litematica users need it, and it makes the export screen feel finished.

---

## 10. Persistence, auth, multi-tenancy

- **Postgres.** `users`, `structures`, `structure_versions` (JSONB, immutable, append-only),
  `annotations`, `messages`, `usage_events`.
- **Structures as JSONB**, not schematics. Schematics are regenerable artifacts; store them
  in object storage with a short TTL and regenerate on demand.
- **Auth:** OAuth (Google/GitHub) or magic link. Do not roll password auth.
- **Conversation history** persisted per structure so a session can be resumed — with the
  caveat that a resumed session starts cold on cache.
- **Object storage** for exports, 24h signed URLs, lifecycle-deleted.

---

## 11. Cost model

Opus 5 is **$5 / $25** per MTok (input / output). The illustrative numbers below assume a
~5 000-token cached prefix, ~1 500 fresh input tokens per turn, and ~2 500 output tokens per
turn (thinking + tool-call JSON + text), with multi-turn caching on.

| Session | Model turns | Est. cost (Opus 5) | With `claude-sonnet-5` at intro pricing |
|---|---:|---:|---:|
| Simple one-shot build | 3 | ~$0.20 | ~$0.08 |
| Typical build + 3 revision rounds | 12 | ~$1.00 | ~$0.40 |
| Heavy session, large structure | 30 | ~$3.50 | ~$1.40 |

**These are estimates, not measurements.** Before setting a price, run `count_tokens`
against real transcripts — that is the only number worth pricing on.

Levers, in order of effect:

1. **Prompt caching** (§6.3) roughly halves input cost on multi-turn sessions. Non-optional.
2. **`effort`** — sweep it per route. `low`/`medium` are strong on Opus 5 and this is the
   biggest quality/cost dial. Note that effort will *not* reliably shorten the model's
   user-facing text; use a conciseness instruction for that.
3. **`task_budget`** per request (min 20 000). This is the mechanism for "a free build gets
   N tokens" — the model paces itself and finishes gracefully instead of being truncated
   mid-structure. Enforce a hard `max_tokens` ceiling on top of it.
4. **Model tier** — `claude-sonnet-5` is $3/$15, with $2/$10 introductory pricing through
   2026-08-31. A "fast/cheap" tier is a legitimate product decision; note that Sonnet 5
   does not support mid-conversation system messages if you later depend on those.

Operationally: meter output tokens per user, expose remaining budget in the UI, hard-stop at
the cap. Emit a `usage` SSE event per turn so cost is visible while it accrues — the fastest
way to lose money here is an unmetered agentic loop.

---

## 12. Security

- **Structure JSON is untrusted input** — from the model *and* from users. Validate through
  Pydantic at every boundary. Cap total voxel count (suggest 2 000 000) *before* calling
  `expand()`: a `cuboid` from `[-100000,…]` to `[100000,…]` is a trivial OOM. Cap operation
  count and per-op radius/height too, and enforce the cap inside the tool so the model gets
  an error result it can recover from.
- **`expand()` is CPU-bound.** Run exports and large expansions in a worker/thread pool with
  a timeout, not on the request path.
- **Never put the API key anywhere a client can reach it.** All Anthropic calls are
  server-side. No key in the browser bundle, no key proxied to the frontend.
- **Rate-limit `/api/chat` per user and per IP**, independently of the token budget.
- Signed, expiring, non-enumerable export URLs.
- Prompt-injection surface is small (no browsing, no code execution, no filesystem), but
  keep it that way: do not add a tool that fetches URLs on the model's behalf without
  revisiting this section.

---

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Unmetered agentic loop burns API spend | **High** | `task_budget` + `max_tokens` + per-user cap + per-turn usage events. Build this in phase 1, not later. |
| Flat colours aren't enough to judge a build | Medium | Validate with real users early; §7.2 path 2 is the escape hatch. |
| `litemapy` beta regression corrupts blueprints silently | Medium | Pinned version + round-trip test + manual in-game check per release. |
| Annotation→operation resolution feels wrong on overlapping ops | Medium | Rank by voxel count; let the user override the target op in the tray. |
| Prompt cache silently not hitting, doubling cost | Medium | Assert `cache_read_input_tokens > 0` in staging; alert on cache-hit-rate drop. |
| Coordinate-space mix-up (§5.2) mismaps annotations | Medium | Authoring coords canonical; regression test with negative coordinates. |
| Effort/verbosity defaults inflate cost | Low | Effort sweep on a real eval set before launch. |

---

## 14. Milestones

**Phase 0 — core changes (small, independently useful, ship first)**
- `expand_with_provenance()` + tests
- `to_litematic()` + `output_formats` on the MCP tool + round-trip test
- `colors.py` + generation script appended to `data/README.md`
- Voxel-count/op-count caps in the core

*Everything in phase 0 improves the existing MCP server on its own and carries no web-app
risk. It is the right first commit regardless of what happens to the rest of this plan.*

**Phase 1 — read-only web viewer**
FastAPI skeleton, `POST /api/structures` + `GET`, three.js `InstancedMesh` renderer with
orbit/pan/zoom, flat colours, no agent. Validates the single riskiest assumption — *is this
fidelity good enough to judge a build?* — before any Claude integration.

**Phase 2 — agent + streaming**
Tool-use loop, 6 tools, SSE, chat pane, live structure updates, prompt caching, usage
metering and budget caps. First end-to-end "describe it and watch it appear".

**Phase 3 — annotation loop**
Picking, point/region markup, annotation tray, `get_annotations` / `resolve_annotations`,
version history and rollback. This is the differentiating feature.

**Phase 4 — product**
Auth, Postgres, export screen with material list, per-user budgets, optional
user-supplied-resource-pack textures.

Phases 1–3 are the product; phase 4 makes it hostable. Phase 0 should land now.

---

## Appendix: decisions and their rationale

| Decision | Rationale |
|---|---|
| Python backend | `schema.py` is the tool schema; a TS rewrite guarantees drift between two geometry definitions. |
| Operations JSON as source of truth | Schematics are compiled output. Editing the JSON is what makes revision cheap and diffable. |
| Own three.js renderer over `lodestone`/`deepslate` | No asset licensing problem, no thin dependency in the critical path. Revisit `deepslate` if real block models become a requirement. |
| Six tools, no filesystem tool | Narrow, typed, auditable surface; persistence is the server's job. |
| `patch_operations` alongside `put_structure` | Surgical edits are what makes "make the roof steeper" cheap instead of a 200-op rewrite. |
| Operation provenance for annotations | Turns vague dissatisfaction into a targeted edit of one operation — the thing LLMs are good at. |
| Batched "apply notes" instead of live interruption | MCP-style and API-style loops are both request-driven; the browser cannot interrupt a turn. Batching is also better UX. |
| Flat colours by default | The only texture option that is unambiguously safe to serve from our origin. |
| Native `.litematic` | Litematica's `.schem` support is explicitly a hack and absent on 1.13–1.16. |
| MCP server retained | Two clients, one core. Free surface, and it keeps the core framework-independent. |
