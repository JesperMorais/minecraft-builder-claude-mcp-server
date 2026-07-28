"""Resolve Minecraft block IDs to their real face textures from a resource pack.

Bring-your-own-pack: the pack (Mojang's assets) is read locally and never
committed. Given a block id (+ optional state), resolve() walks the pack's
blockstate -> model -> parent chain the way the game does, and returns which
texture PNG belongs on each face, plus the model archetype so the frontend can
map it onto the geometry it already draws.

CLI:
    python textures.py <pack.zip> [--out DIR] [--blocks a,b,c | --all]
writes DIR/atlas.json (the id->faces map) and DIR/textures/*.png (only the ones
referenced). Nothing here is meant to live in git alongside real textures.
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FACES = ("down", "up", "north", "south", "east", "west")

# Model archetype -> how its texture variables map onto the six faces.
# Resolved after the parent chain, so e.g. cobblestone (parent cube_all) is easy.
_ARCHETYPES = {
    "cube_all":        {f: "all" for f in FACES},
    "cube":            {"down": "down", "up": "up", "north": "north",
                        "south": "south", "east": "east", "west": "west"},
    "cube_column":     {"up": "end", "down": "end", "north": "side",
                        "south": "side", "east": "side", "west": "side"},
    "cube_column_horizontal": {"up": "side", "down": "side", "north": "end",
                               "south": "end", "east": "side", "west": "side"},
    "cube_bottom_top": {"up": "top", "down": "bottom", "north": "side",
                        "south": "side", "east": "side", "west": "side"},
    "cube_top":        {"up": "top", "down": "side", "north": "side",
                        "south": "side", "east": "side", "west": "side"},
    "orientable":      {"up": "top", "down": "top", "north": "front",
                        "south": "side", "east": "side", "west": "side"},
    "orientable_vertical": {"up": "top", "down": "bottom", "north": "front",
                            "south": "side", "east": "side", "west": "side"},
    "cross":           {f: "cross" for f in FACES},
    "tinted_cross":    {f: "cross" for f in FACES},
    "template_glass_pane_post": {f: "pane" for f in FACES},
}
# Shape families whose geometry the viewer already knows; give it the material
# textures by role and let it place them.
_SHAPE_ROLES = {
    "stairs": ("bottom", "top", "side"),
    "inner_stairs": ("bottom", "top", "side"),
    "outer_stairs": ("bottom", "top", "side"),
    "slab": ("bottom", "top", "side"),
    "slab_top": ("bottom", "top", "side"),
    "fence_post": ("texture",),
    "fence_side": ("texture",),
    "wall_post": ("wall",),
    "door_bottom": ("bottom",),
    "door_top": ("top",),
    "trapdoor": ("texture",),
    "lantern": ("lantern",),
    "carpet": ("wool",),
}


class Pack:
    def __init__(self, zip_path: str):
        self.zf = zipfile.ZipFile(zip_path)
        self.names = set(self.zf.namelist())

    def _json(self, path: str) -> Optional[dict]:
        if path not in self.names:
            return None
        return json.loads(self.zf.read(path))

    def blockstate(self, block: str) -> Optional[dict]:
        return self._json(f"assets/minecraft/blockstates/{block}.json")

    def model(self, ref: str) -> Optional[dict]:
        ref = ref.split(":", 1)[-1]
        return self._json(f"assets/minecraft/models/{ref}.json")

    def texture_bytes(self, name: str) -> Optional[bytes]:
        path = f"assets/minecraft/textures/block/{name}.png"
        return self.zf.read(path) if path in self.names else None


def _texname(val) -> Optional[str]:
    """'minecraft:block/oak_log_top' -> 'oak_log_top'. Non-strings -> None."""
    if not isinstance(val, str):
        return None
    return val.split(":", 1)[-1].split("/")[-1]


def _deref(textures: Dict[str, str], val: Optional[str]) -> Optional[str]:
    seen = set()
    while isinstance(val, str) and val.startswith("#"):
        key = val[1:]
        if key in seen:
            return None
        seen.add(key)
        val = textures.get(key)
    return val


def _resolve_model(pack: Pack, ref: str) -> Tuple[List[str], Dict[str, str]]:
    """Walk parent chain; return (chain of short names, merged texture vars)."""
    chain: List[str] = []
    textures: Dict[str, str] = {}
    cur: Optional[str] = ref
    guard = 0
    while cur and guard < 20:
        guard += 1
        model = pack.model(cur)
        chain.append(cur.split("/")[-1])
        if model is None:
            break
        for k, v in model.get("textures", {}).items():
            textures.setdefault(k, v)      # child wins (we go child->parent)
        cur = model.get("parent")
    return chain, textures


def _first_model_ref(state: dict) -> Optional[str]:
    """Pick one representative model ref from a blockstate (textures are
    rotation-invariant, so any variant / the base multipart part will do)."""
    if "variants" in state:
        first = next(iter(state["variants"].values()))
        if isinstance(first, list):
            first = first[0]
        return first.get("model")
    if "multipart" in state:
        for part in state["multipart"]:
            apply = part.get("apply")
            if isinstance(apply, list):
                apply = apply[0]
            model = apply.get("model", "")
            if model and not model.endswith(("_side", "_side_alt")):
                return model
        return state["multipart"][0]["apply"].get("model")
    return None


def _archetype(chain: List[str]) -> Optional[str]:
    for name in chain:
        if name in _ARCHETYPES:
            return name
    for name in chain:
        for shape in _SHAPE_ROLES:
            if name == shape or name.endswith("_" + shape):
                return shape
    return None


def resolve(pack: Pack, block_id: str) -> Optional[dict]:
    """Return {archetype, faces:{face:png}, roles:{role:png}} or None."""
    base = block_id.split("[", 1)[0].split(":")[-1]
    if base.endswith("air"):
        return None
    state = pack.blockstate(base)
    if state is None:
        return None
    ref = _first_model_ref(state)
    if not ref:
        return None
    chain, tex = _resolve_model(pack, ref)
    # Resolve every texture var to a concrete png name (drop unresolved ones).
    roles: Dict[str, str] = {}
    for key, val in tex.items():
        name = _texname(_deref(tex, val))
        if name:
            roles[key] = name

    arch = _archetype(chain)
    faces: Dict[str, str] = {}
    if arch in _ARCHETYPES:
        for face, role in _ARCHETYPES[arch].items():
            png = roles.get(role) or roles.get("all") or roles.get("texture")
            if png:
                faces[face] = png
    # Infer from the semantic role names present (covers custom-element models
    # like grass_block that don't use a known parent archetype).
    side, top = roles.get("side"), roles.get("top")
    end, front, bottom = roles.get("end"), roles.get("front"), roles.get("bottom")
    if not faces and top and side:
        faces = {"up": top, "down": bottom or side,
                 "north": side, "south": side, "east": side, "west": side}
        arch = arch or "cube_bottom_top*"
    elif not faces and end and side:
        faces = {"up": end, "down": end,
                 "north": side, "south": side, "east": side, "west": side}
        arch = arch or "cube_column*"
    elif not faces and front and side:
        faces = {"north": front, "south": side, "east": side, "west": side,
                 "up": top or side, "down": bottom or side}
        arch = arch or "orientable*"
    if not faces:
        only = (roles.get("all") or roles.get("texture") or roles.get("pane")
                or roles.get("cross") or next(iter(roles.values()), None))
        if only:
            faces = {f: only for f in FACES}
    if not faces and "glass" in base:
        # Transparent glass/panes use a custom model; texture name is trivial.
        tex_name = base[:-5] if base.endswith("_pane") else base
        faces = {f: tex_name for f in FACES}
        roles = {"all": tex_name}
        arch = "glass*"
    return {"archetype": arch, "faces": faces, "roles": roles}


def build_atlas(pack: Pack, blocks: List[str], out: Path) -> dict:
    tex_dir = out / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    atlas: Dict[str, dict] = {}
    needed = set()
    unresolved = []
    for b in blocks:
        r = resolve(pack, b)
        if not r or not r["faces"]:
            unresolved.append(b)
            continue
        atlas[b] = {"archetype": r["archetype"], "faces": r["faces"], "roles": r["roles"]}
        needed.update(r["faces"].values())
        needed.update(r["roles"].values())
    for name in needed:
        data = pack.texture_bytes(name)
        if data:
            (tex_dir / f"{name}.png").write_bytes(data)
    (out / "atlas.json").write_text(json.dumps(atlas, indent=1))
    return {"resolved": len(atlas), "textures": len(needed), "unresolved": unresolved}


def _all_blocks(pack: Pack) -> List[str]:
    prefix = "assets/minecraft/blockstates/"
    return sorted(n[len(prefix):-5] for n in pack.names
                  if n.startswith(prefix) and n.endswith(".json"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("--out", default="texturepack_out")
    ap.add_argument("--blocks", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    pack = Pack(args.pack)
    if args.all:
        blocks = _all_blocks(pack)
    elif args.blocks:
        blocks = args.blocks.split(",")
    else:
        blocks = _all_blocks(pack)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    stats = build_atlas(pack, blocks, out)
    print(json.dumps(stats, indent=1)[:2000])


if __name__ == "__main__":
    main()
