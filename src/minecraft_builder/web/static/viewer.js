/**
 * 3D viewer for generated Minecraft structures.
 *
 * Blocks are grouped by shape: full cubes, but also stairs, slabs, fences,
 * panes, lanterns and the rest of the partial-block vocabulary, each drawn as
 * one InstancedMesh per (geometry, material) pair — a couple of dozen draw
 * calls regardless of block count. Shape and orientation are parsed from the
 * block ID itself (`oak_stairs[facing=south,half=top]`), so the server sends
 * nothing beyond the palette it already sent. Fully enclosed voxels never
 * reach the browser — the server drops them.
 *
 * Minecraft's textures are Mojang's and can't be shipped, so material feel
 * comes from generated stand-ins instead: a small procedural luminance map per
 * material family (plank grain, brick courses, stone noise) multiplied with
 * the palette colour, a deterministic per-block tint jitter, real sun shadows,
 * and a sky gradient with a grass plane so builds sit in a world instead of a
 * void.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';

/**
 * Events arrive over SSE. This slower poll is the safety net: EventSource
 * reconnects on its own, but a stream that dies quietly would otherwise leave
 * the page showing a stale build indefinitely.
 */
const STATUS_INTERVAL_MS = 5000;

/**
 * How long to wait for Claude before telling the user something is wrong. A
 * delivered prompt is not an acknowledged one — channel notifications get no
 * reply, and a session started without the channel flag discards them in
 * silence — so a timeout is the only way to surface that case.
 */
const REPLY_TIMEOUT_MS = 25000;

const canvas = document.getElementById('scene');
const titleEl = document.getElementById('title');
const subtitleEl = document.getElementById('subtitle');
const legendEl = document.getElementById('legend');
const statusEl = document.getElementById('status');
const byOperationEl = document.getElementById('by-operation');
const showGridEl = document.getElementById('show-grid');
const messagesEl = document.getElementById('messages');
const promptFormEl = document.getElementById('prompt-form');
const promptEl = document.getElementById('prompt');
const sendEl = document.getElementById('send');
const linkDotEl = document.getElementById('link-dot');
const linkLabelEl = document.getElementById('link-label');
const annotateModeEl = document.getElementById('annotate-mode');
const annotateHelpEl = document.getElementById('annotate-help');
const notesEl = document.getElementById('notes');
const notesListEl = document.getElementById('notes-list');
const notesCountEl = document.getElementById('notes-count');
const applyNotesEl = document.getElementById('apply-notes');
const noteComposerEl = document.getElementById('note-composer');
const noteTargetEl = document.getElementById('note-target');
const noteTextEl = document.getElementById('note-text');
const noteCancelEl = document.getElementById('note-cancel');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = skyTexture();
// Fog blends the ground plane into the horizon instead of ending it at a hard
// clipped edge; the distances are set per build in frameCamera().
scene.fog = new THREE.Fog(0xcfe0f5, 100, 1000);

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Hemisphere light keeps downward faces from going pure black; the directional
// light is what casts shadows and makes edges legible.
scene.add(new THREE.HemisphereLight(0xdfeaff, 0x6b7256, 1.35));
const sun = new THREE.DirectionalLight(0xffffff, 1.7);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
// Lifts shadow sampling off the surface; without it every face self-shadows
// into stripes ("shadow acne") at this scale.
sun.shadow.normalBias = 0.03;
scene.add(sun, sun.target);

/** Minecraft-ish clear day: light zenith falling to a pale horizon. */
function skyTexture() {
  const sky = document.createElement('canvas');
  sky.width = 1;
  sky.height = 256;
  const ctx = sky.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 256);
  gradient.addColorStop(0, '#78a7ff');
  gradient.addColorStop(0.7, '#a8c6f8');
  gradient.addColorStop(1, '#cfe0f5');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 1, 256);
  const texture = new THREE.CanvasTexture(sky);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

// --------------------------------------------------------------------------- //
// Block shapes
//
// Everything below turns a block ID into (geometry, orientation, material
// class). Geometries are built once in a canonical orientation — facing
// "south" (+Z), sitting in a unit cell centred on the origin — and instances
// carry their rotation and any vertical offset in the per-instance matrix.
// --------------------------------------------------------------------------- //

/** `minecraft:oak_stairs[facing=south,half=top]` → base id + state map. */
function parseBlock(id) {
  const stateStart = id.indexOf('[');
  let base = (stateStart === -1 ? id : id.slice(0, stateStart)).trim();
  base = base.replace(/^minecraft:/, '');
  const states = {};
  if (stateStart !== -1) {
    const stateEnd = id.lastIndexOf(']');
    for (const pair of id.slice(stateStart + 1, stateEnd === -1 ? id.length : stateEnd).split(',')) {
      const [key, value] = pair.split('=');
      if (key && value !== undefined) states[key.trim()] = value.trim();
    }
  }
  return { base, states };
}

/** Merge axis-aligned boxes ([cx, cy, cz, sx, sy, sz]) into one geometry. */
function boxes(...specs) {
  const parts = specs.map(([cx, cy, cz, sx, sy, sz]) => {
    const box = new THREE.BoxGeometry(sx, sy, sz);
    box.translate(cx, cy, cz);
    return box;
  });
  const merged = BufferGeometryUtils.mergeGeometries(parts);
  parts.forEach((part) => part.dispose());
  return merged;
}

/**
 * Shared shape geometries. Sixteenths, like Minecraft's own models: a fence
 * post is 4/16 wide, a trapdoor 3/16 thick. Shapes that vary by block state in
 * more than a rotation (stairs half=top) get a geometry per variant, because
 * an InstancedMesh has exactly one geometry; pure rotations and vertical
 * offsets stay in the instance matrix instead.
 */
const GEOMETRY = {
  cube: boxes([0, 0, 0, 1, 1, 1]),
  slab: boxes([0, 0, 0, 1, 0.5, 1]),
  stairs_bottom: boxes([0, -0.25, 0, 1, 0.5, 1], [0, 0.25, 0.25, 1, 0.5, 0.5]),
  stairs_top: boxes([0, 0.25, 0, 1, 0.5, 1], [0, -0.25, 0.25, 1, 0.5, 0.5]),
  fence_post: boxes([0, 0, 0, 0.25, 1, 0.25]),
  fence_arm: boxes([0, 0.125, 0.25, 0.15, 0.55, 0.5]),
  wall_post: boxes([0, 0, 0, 0.5, 1, 0.5]),
  wall_arm: boxes([0, -0.075, 0.25, 0.375, 0.85, 0.5]),
  pane_core: boxes([0, 0, 0, 0.125, 1, 0.125]),
  pane_arm: boxes([0, 0, 0.28125, 0.125, 1, 0.4375]),
  gate: boxes([0, 0.05, 0, 1, 0.7, 0.25]),
  // Doors, open trapdoors and ladders press against the cell edge opposite
  // their facing, so the offset is baked into the geometry and rotates with it.
  door: boxes([0, 0, -0.40625, 1, 1, 0.1875]),
  trapdoor_closed: boxes([0, 0, 0, 1, 0.1875, 1]),
  trapdoor_open: boxes([0, 0, -0.40625, 1, 1, 0.1875]),
  lantern: boxes([0, -0.21875, 0, 0.375, 0.4375, 0.375], [0, 0.03125, 0, 0.25, 0.125, 0.25]),
  chain: boxes([0, 0, 0, 0.09375, 1, 0.09375]),
  torch: boxes([0, -0.1875, 0, 0.125, 0.625, 0.125]),
  campfire: boxes([0, -0.28125, 0, 0.9375, 0.4375, 0.9375]),
  candle: boxes([0, -0.3125, 0, 0.1875, 0.375, 0.1875]),
  carpet: boxes([0, -0.46875, 0, 1, 0.0625, 1]),
  rod: boxes([0, 0, 0, 0.15625, 1, 0.15625]),
  pot: boxes([0, -0.3125, 0, 0.375, 0.375, 0.375]),
  plate: boxes([0, -0.46875, 0, 0.875, 0.0625, 0.875]),
  button: boxes([0, -0.4375, 0, 0.375, 0.125, 0.25]),
};

/** Horizontal facings: rotation around +Y that maps canonical +Z onto the
 * direction, plus the neighbour offset used for connection checks. */
const FACINGS = {
  south: { angle: 0, dx: 0, dz: 1 },
  east: { angle: Math.PI / 2, dx: 1, dz: 0 },
  north: { angle: Math.PI, dx: 0, dz: -1 },
  west: { angle: -Math.PI / 2, dx: -1, dz: 0 },
};

/** Full-brightness blocks, drawn unlit so they read as light sources. */
const GLOW_EXACT = new Set([
  'lantern', 'soul_lantern', 'copper_lantern', 'sea_lantern', 'glowstone',
  'shroomlight', 'redstone_lamp', 'campfire', 'soul_campfire', 'end_rod',
  'torch', 'candle', 'magma_block', 'crying_obsidian',
]);

function isGlowing(base) {
  return GLOW_EXACT.has(base) || /(_torch|_candle|_froglight)$/.test(base);
}

function isGlass(base) {
  return base === 'glass' || base === 'tinted_glass' || base.endsWith('_glass')
    || (base.endsWith('_pane') && base.includes('glass'));
}

/** Map a base id (+states) to one of the GEOMETRY shape families. */
function kindOf(base, states) {
  if (base.endsWith('_stairs')) return 'stairs';
  if (base.endsWith('_slab')) return states.type === 'double' ? 'cube' : 'slab';
  if (base.endsWith('_fence_gate')) return 'gate';
  if (base.endsWith('_fence')) return 'fence';
  if (base.endsWith('_wall')) return 'wall';
  if (base.endsWith('_pane') || base.endsWith('_bars')) return 'pane';
  if (base.endsWith('_trapdoor')) return 'trapdoor';
  if (base.endsWith('_door') || base === 'ladder') return 'door';
  if (base.endsWith('_button')) return 'button';
  if (base.endsWith('_pressure_plate')) return 'plate';
  if (base.endsWith('_carpet') || base === 'snow' || base === 'leaf_litter') return 'carpet';
  if (base === 'chain' || base.endsWith('_chain')) return 'chain';
  if (base === 'lantern' || base === 'soul_lantern' || base === 'copper_lantern') return 'lantern';
  if (base === 'torch' || base.endsWith('_torch')) return 'torch';
  if (base === 'campfire' || base === 'soul_campfire') return 'campfire';
  if (base === 'candle' || base.endsWith('_candle')) return 'candle';
  if (base === 'end_rod' || base === 'lightning_rod') return 'rod';
  if (base === 'flower_pot' || base.endsWith('_flower_pot')) return 'pot';
  return 'cube';
}

// --------------------------------------------------------------------------- //
// Procedural textures
//
// Mojang's textures can't be shipped, so each material family gets a small
// generated luminance map instead: white pixels leave the palette colour
// untouched, darker ones shade it. The same texture serves every colour of a
// family (all planks share the plank grain), because the colour still comes
// from the per-instance palette tint.
// --------------------------------------------------------------------------- //

const TEXTURE_SIZE = 16;
const at = (x, y) => y * TEXTURE_SIZE + x;

/** Small deterministic PRNG, so a pattern looks identical on every rebuild. */
function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function noisePaint(amount) {
  return (lum, rand) => {
    for (let i = 0; i < lum.length; i++) lum[i] = 1 - rand() * amount;
  };
}

function planksPaint(lum, rand) {
  noisePaint(0.08)(lum, rand);
  for (let band = 0; band < 4; band++) {
    const seam = band * 4 + 3;
    for (let x = 0; x < TEXTURE_SIZE; x++) lum[at(x, seam)] *= 0.76;
    const joint = Math.floor(rand() * TEXTURE_SIZE);
    for (let y = band * 4; y < band * 4 + 3; y++) lum[at(joint, y)] *= 0.82;
  }
}

function bricksPaint(lum, rand) {
  noisePaint(0.08)(lum, rand);
  for (let course = 0; course < 4; course++) {
    const mortar = course * 4;
    for (let x = 0; x < TEXTURE_SIZE; x++) lum[at(x, mortar)] *= 0.72;
    for (let x = course % 2 ? 0 : 4; x < TEXTURE_SIZE; x += 8) {
      for (let y = mortar + 1; y < mortar + 4; y++) lum[at(x, y)] *= 0.72;
    }
  }
}

function stoneBricksPaint(lum, rand) {
  noisePaint(0.1)(lum, rand);
  for (let i = 0; i < TEXTURE_SIZE; i++) {
    lum[at(i, 0)] *= 0.78;
    lum[at(i, 8)] *= 0.78;
    lum[at(0, i)] *= 0.78;
    lum[at(8, i)] *= 0.78;
  }
}

function logPaint(lum, rand) {
  for (let x = 0; x < TEXTURE_SIZE; x++) {
    const grain = 1 - rand() * 0.2;
    for (let y = 0; y < TEXTURE_SIZE; y++) lum[at(x, y)] = grain * (1 - rand() * 0.08);
  }
}

function specklePaint(lum, rand) {
  noisePaint(0.14)(lum, rand);
  for (let i = 0; i < 10; i++) {
    const x = Math.floor(rand() * (TEXTURE_SIZE - 1));
    const y = Math.floor(rand() * (TEXTURE_SIZE - 1));
    const shade = 0.75 + rand() * 0.15;
    lum[at(x, y)] *= shade;
    lum[at(x + 1, y)] *= shade;
    lum[at(x, y + 1)] *= shade;
  }
}

function leavesPaint(lum, rand) {
  for (let i = 0; i < lum.length; i++) {
    const v = rand();
    lum[i] = v < 0.18 ? 0.55 + rand() * 0.15 : 1 - rand() * 0.3;
  }
}

function woolPaint(lum, rand) {
  noisePaint(0.07)(lum, rand);
  for (let y = 0; y < TEXTURE_SIZE; y += 2) {
    for (let x = 0; x < TEXTURE_SIZE; x++) lum[at(x, y)] *= 0.95;
  }
}

/** jitter: per-block colour variation, so large same-material faces get the
 * subtle patchwork Minecraft terrain has. Strong on natural materials, near
 * zero on manufactured ones. */
const PATTERNS = {
  stone: { paint: noisePaint(0.13), jitter: 0.05 },
  speckle: { paint: specklePaint, jitter: 0.06 },
  soil: { paint: noisePaint(0.2), jitter: 0.07 },
  smooth: { paint: noisePaint(0.045), jitter: 0.015 },
  planks: { paint: planksPaint, jitter: 0.025 },
  log: { paint: logPaint, jitter: 0.03 },
  bricks: { paint: bricksPaint, jitter: 0.03 },
  stonebricks: { paint: stoneBricksPaint, jitter: 0.04 },
  leaves: { paint: leavesPaint, jitter: 0.09 },
  wool: { paint: woolPaint, jitter: 0.02 },
};

const textureCache = new Map();

function textureFor(pattern) {
  let texture = textureCache.get(pattern);
  if (texture) return texture;
  const source = document.createElement('canvas');
  source.width = source.height = TEXTURE_SIZE;
  const ctx = source.getContext('2d');
  const rand = mulberry32([...pattern].reduce((h, c) => h * 31 + c.charCodeAt(0), 7));
  const lum = new Float32Array(TEXTURE_SIZE * TEXTURE_SIZE).fill(1);
  PATTERNS[pattern].paint(lum, rand);
  // A one-pixel darker rim on every face: the poor man's ambient occlusion,
  // and what keeps individual blocks readable in a same-colour wall.
  for (let i = 0; i < TEXTURE_SIZE; i++) {
    for (const edge of [at(i, 0), at(i, TEXTURE_SIZE - 1), at(0, i), at(TEXTURE_SIZE - 1, i)]) {
      lum[edge] *= 0.9;
    }
  }
  const image = ctx.createImageData(TEXTURE_SIZE, TEXTURE_SIZE);
  lum.forEach((value, i) => {
    const v = Math.round(255 * Math.max(0, Math.min(1, value)));
    image.data.set([v, v, v, 255], i * 4);
  });
  ctx.putImageData(image, 0, 0);
  texture = new THREE.CanvasTexture(source);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  texture.colorSpace = THREE.SRGBColorSpace;
  textureCache.set(pattern, texture);
  return texture;
}

const WOOD_SPECIES = /^(?:stripped_)?(oak|spruce|birch|jungle|acacia|dark_oak|mangrove|cherry|bamboo|crimson|warped|pale_oak)_/;

/** Thin metal fittings read better untextured. */
const UNTEXTURED = new Set([
  'lantern', 'soul_lantern', 'copper_lantern', 'torch', 'soul_torch',
  'redstone_torch', 'copper_torch', 'chain', 'iron_chain', 'copper_chain',
  'end_rod', 'lightning_rod', 'iron_bars', 'copper_bars',
]);

function patternOf(base) {
  if (isGlass(base) || UNTEXTURED.has(base)) return null;
  if (base.includes('stone_brick') || base.includes('deepslate_brick')
    || base.includes('deepslate_tile') || base.includes('blackstone_brick')
    || base.includes('nether_brick')) return 'stonebricks';
  if (base.includes('brick')) return 'bricks';
  if (base.includes('log') || base.includes('stem') || base === 'bamboo_block'
    || base.includes('basalt') || base.includes('pillar')) return 'log';
  if (base.endsWith('_leaves') || base === 'moss_block' || base.includes('azalea')) return 'leaves';
  if (base.includes('cobble') || base === 'gravel' || base === 'tuff'
    || base === 'andesite' || base === 'diorite' || base === 'granite') return 'speckle';
  if (base.includes('concrete') || base.includes('quartz') || base.includes('terracotta')
    || base === 'calcite' || base.includes('smooth_') || base.includes('polished_')) return 'smooth';
  if (base.includes('wool') || base.endsWith('_carpet')) return 'wool';
  if (base.includes('dirt') || base.includes('sand') || base.includes('grass')
    || base === 'podzol' || base === 'mud' || base === 'clay') return 'soil';
  if (WOOD_SPECIES.test(base) || base.includes('plank')) return 'planks';
  return 'stone';
}

/** Everything the renderer needs to know about one palette entry. */
function describeBlock(block) {
  const { base, states } = parseBlock(block);
  const kind = kindOf(base, states);
  const material = isGlowing(base) ? 'glow' : isGlass(base) ? 'glass' : 'solid';
  const pattern = patternOf(base);
  const jitter = pattern ? PATTERNS[pattern].jitter : 0;
  return { kind, material, pattern, jitter, states };
}

/** What fences, walls and panes visually attach to. */
function connectsTo(kind, neighbour) {
  if (!neighbour) return false;
  if (neighbour.kind === 'cube') return true;
  if (kind === 'pane') return neighbour.kind === 'pane';
  if (kind === 'fence') return neighbour.kind === 'fence' || neighbour.kind === 'gate';
  if (kind === 'wall') return ['wall', 'fence', 'gate', 'pane'].includes(neighbour.kind);
  return false;
}

// Materials are shared across rebuilds — the set is bounded by (class,
// pattern) combinations — so disposeBuild leaves them alone.
const materialCache = new Map();

function materialFor(materialKind, pattern) {
  const key = `${materialKind}|${pattern}`;
  let material = materialCache.get(key);
  if (material) return material;
  const map = pattern ? textureFor(pattern) : null;
  if (materialKind === 'glass') {
    material = new THREE.MeshLambertMaterial({ map, transparent: true, opacity: 0.55 });
  } else if (materialKind === 'glow') {
    // Unlit, so light sources render at full brightness and read as glowing.
    material = new THREE.MeshBasicMaterial({ map });
  } else {
    material = new THREE.MeshLambertMaterial({ map });
  }
  materialCache.set(key, material);
  return material;
}

const UP = new THREE.Vector3(0, 1, 0);

/** Current payload and the scene objects built from it. */
let payload = null;
let buildMeshes = [];
let paletteColors = [];
let grid = null;
let axes = null;
let lastVersion = -1;

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', isError);
}

function disposeBuild() {
  for (const object of [...buildMeshes, grid, axes]) {
    if (!object) continue;
    scene.remove(object);
    // Instanced meshes hold GPU buffers; dropping the reference is not enough.
    // dispose() releases the per-instance buffers and leaves the shared
    // GEOMETRY entries alone. Materials live in materialCache and deliberately
    // survive rebuilds; the helpers' dispose() handles their own materials.
    if (object.dispose) object.dispose();
  }
  buildMeshes = [];
  grid = axes = null;
  if (ground) ground.visible = false;
}

/**
 * Distinct hue per operation index, spaced by the golden angle so adjacent
 * operations never land on similar colours.
 */
function operationColor(index, target) {
  if (index < 0) return target.setHex(0x888888);
  return target.setHSL(((index * 0.61803398875) % 1), 0.62, 0.55);
}

function buildScene(data) {
  disposeBuild();

  const { voxels, stride, palette, bounds } = data;
  const count = voxels.length / stride;
  if (count === 0) {
    setStatus('Structure is empty.');
    return;
  }

  paletteColors = palette.map((entry) => new THREE.Color(entry.color));
  const descriptors = palette.map((entry) => describeBlock(entry.block));

  // Occupancy by cell, for the shapes that reach toward their neighbours.
  const occupied = new Map();
  for (let i = 0; i < count; i++) {
    const base = i * stride;
    occupied.set(
      `${voxels[base]},${voxels[base + 1]},${voxels[base + 2]}`,
      descriptors[voxels[base + 3]],
    );
  }
  const neighbourAt = (x, y, z, facing) =>
    occupied.get(`${x + facing.dx},${y},${z + facing.dz}`);

  // One bucket per (geometry, material class, texture); each becomes an
  // InstancedMesh.
  const buckets = new Map();
  const addInstance = (shape, desc, x, y, z, paletteIndex, operationIndex, angle = 0, lift = 0) => {
    const key = `${shape}|${desc.material}|${desc.pattern}`;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { shape, materialKind: desc.material, pattern: desc.pattern, records: [] };
      buckets.set(key, bucket);
    }
    bucket.records.push({ x, y, z, angle, lift, jitter: desc.jitter, paletteIndex, operationIndex });
  };

  for (let i = 0; i < count; i++) {
    const base = i * stride;
    const [x, y, z] = [voxels[base], voxels[base + 1], voxels[base + 2]];
    const paletteIndex = voxels[base + 3];
    const operationIndex = voxels[base + 4];
    const descriptor = descriptors[paletteIndex];
    const { kind, states } = descriptor;
    const facing = FACINGS[states.facing] || FACINGS.south;
    const add = (shape, angle = 0, lift = 0) =>
      addInstance(shape, descriptor, x, y, z, paletteIndex, operationIndex, angle, lift);

    switch (kind) {
      case 'slab':
        add('slab', 0, states.type === 'top' ? 0.25 : -0.25);
        break;
      case 'stairs':
        add(states.half === 'top' ? 'stairs_top' : 'stairs_bottom', facing.angle);
        break;
      case 'fence':
      case 'wall':
      case 'pane': {
        const post = { fence: 'fence_post', wall: 'wall_post', pane: 'pane_core' }[kind];
        const arm = { fence: 'fence_arm', wall: 'wall_arm', pane: 'pane_arm' }[kind];
        const connected = Object.values(FACINGS)
          .filter((dir) => connectsTo(kind, neighbourAt(x, y, z, dir)));
        add(post);
        // An unconnected pane still reads best as a small cross, like in-game.
        const arms = connected.length || kind !== 'pane' ? connected : Object.values(FACINGS);
        for (const dir of arms) add(arm, dir.angle);
        break;
      }
      case 'gate':
        add('gate', facing.angle);
        break;
      case 'trapdoor':
        if (states.open === 'true') add('trapdoor_open', facing.angle);
        else add('trapdoor_closed', 0, states.half === 'top' ? 0.40625 : -0.40625);
        break;
      case 'door':
        add('door', facing.angle);
        break;
      case 'lantern':
        add('lantern', 0, states.hanging === 'true' ? 0.4 : 0);
        break;
      default:
        // cube, chain, torch, campfire, candle, carpet, rod, pot, plate, button
        add(GEOMETRY[kind] ? kind : 'cube', facing.angle);
        break;
    }
  }

  const matrix = new THREE.Matrix4();
  const rotation = new THREE.Quaternion();
  const position = new THREE.Vector3();
  const unit = new THREE.Vector3(1, 1, 1);
  const scratch = new THREE.Color();

  for (const bucket of buckets.values()) {
    const mesh = new THREE.InstancedMesh(
      GEOMETRY[bucket.shape],
      materialFor(bucket.materialKind, bucket.pattern),
      bucket.records.length,
    );
    // Glass shadows read as solid-block shadows (the map is binary), and
    // glowing blocks casting shadows looks contradictory — solids only.
    mesh.castShadow = bucket.materialKind === 'solid';
    mesh.receiveShadow = bucket.materialKind === 'solid';
    bucket.records.forEach((record, index) => {
      rotation.setFromAxisAngle(UP, record.angle);
      // +0.5 centres the shape in its cell, matching how a Minecraft block
      // occupies the volume between its coordinate and the next.
      position.set(record.x + 0.5, record.y + 0.5 + record.lift, record.z + 0.5);
      matrix.compose(position, rotation, unit);
      mesh.setMatrixAt(index, matrix);
      mesh.setColorAt(index, instanceColor(record, scratch));
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.instanceColor.needsUpdate = true;
    mesh.userData.records = bucket.records;
    scene.add(mesh);
    buildMeshes.push(mesh);
  }

  addHelpers(bounds);
  frameCamera(bounds);
}

function instanceColor(record, target) {
  if (byOperationEl.checked) return operationColor(record.operationIndex, target);
  target.copy(paletteColors[record.paletteIndex]);
  if (record.jitter) {
    target.multiplyScalar(1 - record.jitter + 2 * record.jitter * hash3(record.x, record.y, record.z));
  }
  return target;
}

/** Deterministic 0..1 from a cell coordinate; stable across rebuilds, so a
 * block keeps its tint when the build is revised around it. */
function hash3(x, y, z) {
  let h = (x * 374761393 + y * 668265263 + z * 1274126177) | 0;
  h = Math.imul(h ^ (h >>> 13), 1103515245);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

let ground = null;
let groundTexture = null;

/** Grass plane the build sits on; created once, repositioned per build. */
function ensureGround() {
  if (ground) return;
  groundTexture = textureFor('soil').clone();
  groundTexture.wrapS = THREE.RepeatWrapping;
  groundTexture.wrapT = THREE.RepeatWrapping;
  groundTexture.needsUpdate = true;
  ground = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshLambertMaterial({ color: 0x7fae63, map: groundTexture }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);
}

function addHelpers(bounds) {
  const [minX, minY, minZ] = bounds.min;
  const [sizeX, sizeY, sizeZ] = bounds.size;
  const span = Math.max(sizeX, sizeZ) + 8;
  const centreX = minX + sizeX / 2;
  const centreZ = minZ + sizeZ / 2;

  ensureGround();
  const groundSpan = span * 24; // runs to the fog, not to a visible edge
  ground.scale.set(groundSpan, groundSpan, 1);
  groundTexture.repeat.set(groundSpan, groundSpan); // one texture tile per block
  ground.position.set(centreX, minY - 0.02, centreZ);
  ground.visible = true;

  grid = new THREE.GridHelper(span, span, 0x3a3f47, 0x272b31);
  grid.position.set(centreX, minY + 0.02, centreZ);
  grid.visible = showGridEl.checked;
  scene.add(grid);

  // Anchored at the build's own origin corner so X/Z orientation is readable,
  // which matters when comparing against the coordinates in the source JSON.
  axes = new THREE.AxesHelper(Math.min(6, span / 3));
  axes.position.set(minX, minY, minZ);
  scene.add(axes);

  // Size the sun's shadow frustum to the build, so the shadow map's texels
  // are spent on the build instead of a fixed world-sized box.
  const radius = Math.max(sizeX, sizeY, sizeZ);
  sun.position.set(centreX + radius * 1.4, minY + radius * 2.2, centreZ + radius * 0.8);
  sun.target.position.set(centreX, minY, centreZ);
  const shadowCam = sun.shadow.camera;
  shadowCam.left = -radius * 1.8;
  shadowCam.right = radius * 1.8;
  shadowCam.top = radius * 1.8;
  shadowCam.bottom = -radius * 1.8;
  shadowCam.near = 0.5;
  shadowCam.far = radius * 6 + 20;
  shadowCam.updateProjectionMatrix();
}

function frameCamera(bounds) {
  const [sizeX, sizeY, sizeZ] = bounds.size;
  const centre = new THREE.Vector3(
    bounds.min[0] + sizeX / 2,
    bounds.min[1] + sizeY / 2,
    bounds.min[2] + sizeZ / 2,
  );
  const radius = Math.max(Math.hypot(sizeX, sizeY, sizeZ) / 2, 2);
  const distance = radius / Math.sin((camera.fov * Math.PI) / 360) * 1.25;

  camera.position.set(
    centre.x + distance * 0.62,
    centre.y + distance * 0.55,
    centre.z + distance * 0.62,
  );
  camera.far = distance * 12;
  camera.updateProjectionMatrix();
  controls.target.copy(centre);
  controls.update();

  // Keep the fog proportional to the framing: far enough to never tint the
  // build itself, close enough that the ground plane fades before its edge.
  scene.fog.near = distance * 4;
  scene.fog.far = distance * 10;
}

function renderLegend(data) {
  const { voxels, stride, palette } = data;
  const drawn = new Array(palette.length).fill(0);
  for (let i = 0; i < voxels.length; i += stride) drawn[voxels[i + 3]]++;

  const entries = palette
    .map((entry, index) => ({ ...entry, count: drawn[index] }))
    .sort((a, b) => b.count - a.count);

  // Block IDs come from model-generated JSON, so the legend is built with
  // createElement/textContent throughout rather than assembled as markup.
  legendEl.replaceChildren();
  const heading = document.createElement('div');
  heading.className = 'legend-entry';
  const headingLabel = document.createElement('span');
  headingLabel.className = 'name';
  headingLabel.textContent = 'Visible blocks';
  heading.appendChild(headingLabel);
  legendEl.appendChild(heading);

  for (const entry of entries) {
    const row = document.createElement('div');
    row.className = 'legend-entry';

    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = entry.color;

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = entry.block.replace(/^minecraft:/, '');
    name.title = entry.block;

    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = entry.count.toLocaleString();

    row.append(swatch, name, count);
    legendEl.appendChild(row);
  }
}

function applyPayload(data) {
  payload = data;

  // A new version invalidates any selection in progress: the coordinate may hold
  // a different operation now, and a note about it would resolve against the
  // build that just replaced what the user was looking at. Saved notes are
  // untouched — they already carry the version they were drawn on.
  cancelSelection();

  if (data.empty) {
    disposeBuild();
    titleEl.textContent = 'Waiting for a structure…';
    subtitleEl.textContent = data.message || '';
    legendEl.replaceChildren();
    setStatus('');
    return;
  }

  const [w, h, l] = data.bounds.size;
  titleEl.textContent = data.name;
  subtitleEl.textContent =
    `${w}x${h}x${l} · ${data.counts.total.toLocaleString()} blocks ` +
    `(${data.counts.drawn.toLocaleString()} visible, ` +
    `${data.counts.hidden.toLocaleString()} enclosed) · v${data.version}` +
    (data.description ? ` · ${data.description}` : '');

  buildScene(data);
  renderLegend(data);
  setStatus(`${data.operations.length} operation(s)`);
}

/** Recolour in place, without rebuilding geometry. */
function recolor() {
  const scratch = new THREE.Color();
  for (const mesh of buildMeshes) {
    mesh.userData.records.forEach((record, index) => {
      mesh.setColorAt(index, instanceColor(record, scratch));
    });
    mesh.instanceColor.needsUpdate = true;
  }
}

async function fetchPayload() {
  const response = await fetch('/api/structure', { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  applyPayload(await response.json());
}

async function syncVersion(version) {
  if (version === lastVersion) return;
  lastVersion = version;
  await fetchPayload();
}

// --------------------------------------------------------------------------- //
// Chat
// --------------------------------------------------------------------------- //

/** Ids already rendered. SSE replays a snapshot on every reconnect. */
const seenMessages = new Set();
let awaitingReplySince = null;
let warnedAboutSilence = false;

function renderMessage(message) {
  if (seenMessages.has(message.id)) return;
  seenMessages.add(message.id);

  const item = document.createElement('li');
  item.className = `msg ${message.role}`;
  if (message.role === 'user' && message.delivered === false) {
    item.classList.add('undelivered');
  }

  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = { user: 'you', assistant: 'claude', system: 'viewer' }[message.role]
    || message.role;

  const body = document.createElement('span');
  body.className = 'body';
  // Message text is model-authored, so it is never treated as markup.
  body.textContent = message.text;

  item.append(who, body);
  messagesEl.appendChild(item);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  if (message.role === 'assistant') {
    awaitingReplySince = null;
    warnedAboutSilence = false;
  }
}

/** A note from the page itself; not part of the server transcript. */
function localNote(text) {
  renderMessage({ id: `local-${Date.now()}`, role: 'system', text });
}

/**
 * Paint the link indicator from an /api/status-shaped object.
 *
 * Three colours, not two, because there are three genuinely different states
 * and the middle one used to be painted as the good one.
 *
 * Green is reserved for evidence that a prompt gets collected: `waiting` (an
 * await_prompt call is blocked on the queue right now), `polling` (one was
 * blocked within the grace window, so the loop is between rounds and will be
 * back), or `confirmed` (an event we pushed came back answered, the only proof
 * the channel round trip closes).
 *
 * `attached` is none of those. It says an MCP session exists over stdio, with or
 * without the channel enabled; when org policy blocks channels its pushes are
 * discarded in silence, and nothing on the outbound side can tell that from
 * success. So it gets amber: something is there, nothing has proven it. ORing it
 * into green is what let this dot report a healthy link for an entire debugging
 * session in which not one prompt was delivered.
 */
function setLink(status) {
  const proven = status.waiting === true
    || status.polling === true
    || status.confirmed === true;
  const attached = status.attached === true;

  linkDotEl.classList.toggle('live', proven);
  linkDotEl.classList.toggle('pending', !proven && attached);
  linkDotEl.classList.toggle('down', !proven && !attached);

  if (status.waiting === true) {
    linkLabelEl.textContent = 'Claude is listening';
    linkDotEl.title = 'An await_prompt call is waiting on your next message.';
  } else if (status.polling === true) {
    linkLabelEl.textContent = 'Claude is busy, still listening';
    linkDotEl.title = 'Claude is between await_prompt rounds — probably building '
      + 'or replying. Your prompt will be picked up.';
  } else if (status.confirmed === true) {
    linkLabelEl.textContent = 'connected to Claude';
    linkDotEl.title = 'The channel has answered an event, so prompts are '
      + 'reaching this session.';
  } else if (attached) {
    linkLabelEl.textContent = 'attached, but delivery unproven';
    linkDotEl.title = 'An MCP session exists, but nothing has confirmed it '
      + 'receives anything — channel events are not acknowledged, so a session '
      + 'with channels disabled or blocked by org policy looks identical from '
      + 'here. Your prompt is queued as well: ask Claude in the terminal to '
      + 'listen with its await_prompt tool and it will be collected.';
  } else {
    linkLabelEl.textContent = 'no Claude session listening';
    linkDotEl.title = 'Nothing is collecting prompts. Ask Claude in the terminal '
      + 'to listen with its await_prompt tool.';
  }
}

async function sendPrompt(text) {
  sendEl.disabled = true;
  try {
    const response = await fetch('/api/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    // The reply carries the same link fields as /api/status, so the dot is
    // repainted from what the server actually knows rather than inferred from
    // "delivered" — which cannot distinguish an unproven push from a real one.
    const result = await response.json();
    // The server echoes the prompt back over SSE, so it is not rendered here.
    awaitingReplySince = result.delivered ? Date.now() : null;
    warnedAboutSilence = false;
    setLink(result);
  } catch (error) {
    localNote(`Could not send that prompt: ${error.message}`);
  } finally {
    sendEl.disabled = false;
    promptEl.focus();
  }
}

function checkForSilence() {
  if (awaitingReplySince === null || warnedAboutSilence) return;
  if (Date.now() - awaitingReplySince < REPLY_TIMEOUT_MS) return;
  warnedAboutSilence = true;
  // No trailing punctuation after the flag: this text gets copy-pasted, and a
  // sentence period lands inside the server name, which Claude Code then reports
  // as "no MCP server configured with that name".
  localNote(
    'No response yet. Claude may still be working — or nothing is listening. '
    + 'Ask Claude in the terminal to listen with its await_prompt tool (works '
    + 'without any flag), or restart Claude Code from the project root with:\n'
    + '--dangerously-load-development-channels server:minecraft-builder',
  );
}

// --------------------------------------------------------------------------- //
// Markup
//
// The whole point of marking a build is to turn a coordinate into an operation.
// "The block at [7,4,3] is wrong" makes Claude guess which of forty operations
// to edit; "operation #4, the roof pyramid" is a targeted change. The server
// does the resolving (against the version on screen, not the current one), but
// the payload already carries a per-voxel operation index and the operation
// labels, so the page can name the target before it posts anything.
// --------------------------------------------------------------------------- //

const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();

/** Pixels of pointer travel that make a gesture a drag rather than a click. */
const CLICK_SLOP = 5;

const markerMaterial = new THREE.LineBasicMaterial({ color: 0xe0b341 });

/** Server-owned note list, plus the in-progress selection. */
let notes = [];
let pendingCorner = null;   // first Shift-click of a region
let pendingTarget = null;   // what the composer is about to attach a note to
let marker = null;          // wireframe box over the current selection
let pointerDownAt = null;   // for telling a click from an orbit drag

function annotating() {
  return annotateModeEl.checked;
}

/**
 * The voxel under the pointer, or null.
 *
 * buildScene() leaves its per-instance records on each mesh, so an
 * intersection's instanceId indexes straight back to the voxel that produced
 * it. That matters more than it looks: rounding the intersection point to a
 * cell would be wrong for every partial block, whose geometry does not fill its
 * cell and whose surface can therefore sit inside a neighbour.
 */
function pickVoxel(event) {
  if (!buildMeshes.length) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  pointerNdc.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointerNdc.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointerNdc, camera);
  for (const hit of raycaster.intersectObjects(buildMeshes, false)) {
    const record = hit.object.userData.records?.[hit.instanceId];
    if (record) return record;
  }
  return null;
}

function operationLabel(index) {
  if (index === undefined || index === null || index < 0) return null;
  return payload?.operations?.find((entry) => entry.index === index)?.label || null;
}

/** Describe a target the way the tray and composer both want it. */
function describeTarget(target) {
  const where = target.kind === 'region'
    ? `region [${target.start}] to [${target.end}]`
    : `block [${target.pos}]`;
  const label = operationLabel(target.operationIndex);
  if (target.operationIndex === null || target.operationIndex === undefined) {
    return `${where} — no operation placed this`;
  }
  return `${where} — operation #${target.operationIndex}${label ? ` (${label})` : ''}`;
}

function clearMarker() {
  if (!marker) return;
  scene.remove(marker);
  marker.geometry.dispose();
  marker = null;
}

/** Wireframe box over an inclusive coordinate range. */
function showMarker(low, high) {
  clearMarker();
  const size = [0, 1, 2].map((i) => Math.abs(high[i] - low[i]) + 1);
  const min = [0, 1, 2].map((i) => Math.min(low[i], high[i]));
  const box = new THREE.BoxGeometry(size[0], size[1], size[2]);
  marker = new THREE.LineSegments(new THREE.EdgesGeometry(box), markerMaterial);
  box.dispose();  // EdgesGeometry copied what it needed
  marker.position.set(
    min[0] + size[0] / 2,
    min[1] + size[1] / 2,
    min[2] + size[2] / 2,
  );
  scene.add(marker);
}

function cancelSelection() {
  pendingCorner = null;
  pendingTarget = null;
  clearMarker();
  noteComposerEl.hidden = true;
  noteTextEl.value = '';
}

function openComposer(target) {
  pendingTarget = target;
  noteTargetEl.textContent = describeTarget(target);
  noteComposerEl.hidden = false;
  noteTextEl.focus();
}

function onSceneClick(event) {
  if (!annotating()) return;
  const record = pickVoxel(event);
  if (!record) {
    // Clicking past the build is how you dismiss a half-made region, so it is
    // not worth an error message.
    if (pendingCorner) cancelSelection();
    return;
  }

  const here = [record.x, record.y, record.z];

  if (event.shiftKey) {
    if (!pendingCorner) {
      pendingCorner = { pos: here, operationIndex: record.operationIndex };
      showMarker(here, here);
      setStatus('Shift-click the opposite corner of the region.');
      return;
    }
    const low = [0, 1, 2].map((i) => Math.min(pendingCorner.pos[i], here[i]));
    const high = [0, 1, 2].map((i) => Math.max(pendingCorner.pos[i], here[i]));
    showMarker(low, high);
    setStatus('');
    // The server decides which operation dominates a region; showing the corner
    // block's operation here would often disagree with the note that comes back.
    openComposer({ kind: 'region', start: low, end: high });
    pendingCorner = null;
    return;
  }

  showMarker(here, here);
  openComposer({ kind: 'point', pos: here, operationIndex: record.operationIndex });
}

async function saveNote(text) {
  if (!pendingTarget) return;
  const body = {
    kind: pendingTarget.kind,
    note: text,
    structure_version: payload?.version,
  };
  if (pendingTarget.kind === 'region') {
    body.start = pendingTarget.start;
    body.end = pendingTarget.end;
  } else {
    body.pos = pendingTarget.pos;
  }

  try {
    const response = await fetch('/api/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await errorText(response));
    cancelSelection();
    await refreshNotes();
  } catch (error) {
    setStatus(`Could not save that note: ${error.message}`, true);
  }
}

/** The server's error text, which says what was actually wrong with the input. */
async function errorText(response) {
  // http.server puts send_error's message in the status line and an HTML body
  // around it; the status line is the readable half.
  return response.statusText || `HTTP ${response.status}`;
}

async function refreshNotes() {
  try {
    const response = await fetch('/api/annotations', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    notes = data.annotations || [];
    renderNotes();
  } catch {
    // A failed refresh leaves the previous list on screen, which is better than
    // blanking it: nothing has been lost, the page just did not hear back.
  }
}

function renderNotes() {
  const open = notes.filter((note) => note.status === 'open');
  notesEl.hidden = notes.length === 0;
  applyNotesEl.disabled = open.length === 0;
  notesCountEl.textContent = open.length
    ? `${open.length} open note${open.length === 1 ? '' : 's'}`
    : 'all notes applied';

  notesListEl.replaceChildren();
  for (const note of notes) {
    const item = document.createElement('li');
    item.className = `note ${note.status}`;

    const text = document.createElement('div');
    const where = document.createElement('span');
    where.className = 'where';
    where.textContent = noteWhere(note);
    const body = document.createElement('span');
    body.className = 'body';
    // User-authored, so never interpreted as markup.
    body.textContent = note.note;
    text.append(where, body);

    const drop = document.createElement('button');
    drop.className = 'drop';
    drop.type = 'button';
    drop.textContent = '×';
    drop.title = 'Delete this note';
    drop.addEventListener('click', () => dropNote(note.id));

    item.append(text, drop);
    notesListEl.appendChild(item);
  }
}

function noteWhere(note) {
  // Compared against null/undefined rather than truthiness: operation #0 is a
  // real operation, and the obvious `note.op_index ? …` would file every note on
  // the first one as if it belonged to the whole build.
  const resolved = note.op_index !== null && note.op_index !== undefined;
  if (note.kind === 'global') return 'whole build';
  // A point or region that landed on nothing is not a note about the whole
  // build; it is a note with no operation to edit, and saying so is the honest
  // version.
  const target = resolved ? `op #${note.op_index}` : 'no op';
  if (note.kind === 'region') return `${target} · region`;
  if (note.kind === 'point') return `${target} · [${note.pos}]`;
  return target;
}

async function dropNote(id) {
  try {
    const response = await fetch(`/api/annotations/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error(await errorText(response));
    await refreshNotes();
  } catch (error) {
    setStatus(`Could not delete that note: ${error.message}`, true);
  }
}

async function applyNotes() {
  applyNotesEl.disabled = true;
  try {
    const response = await fetch('/api/apply-notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (!response.ok) throw new Error(await errorText(response));
    // The prompt echoes back over SSE like any other, so the transcript shows
    // what was asked on the user's behalf. The dot is repainted from the same
    // link fields a typed prompt returns.
    setLink(await response.json());
  } catch (error) {
    setStatus(`Could not ask Claude to apply the notes: ${error.message}`, true);
  } finally {
    renderNotes();
  }
}

// --------------------------------------------------------------------------- //
// Transport
// --------------------------------------------------------------------------- //

function connectEvents() {
  const source = new EventSource('/api/events');

  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'snapshot') {
      setLink(data);
      for (const message of data.messages) renderMessage(message);
      syncVersion(data.version).catch(() => {});
      setStatus('');
    } else if (data.type === 'message') {
      renderMessage(data.message);
    } else if (data.type === 'structure') {
      syncVersion(data.version).catch((error) => setStatus(error.message, true));
    }
  };

  // EventSource retries by itself; this only reports the gap.
  source.onerror = () => setStatus('Reconnecting to the viewer server…', true);
  source.onopen = () => setStatus('');
}

/** Fallback and liveness: catches a silently dead stream and refreshes the dot. */
async function refreshStatus() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const status = await response.json();
    setLink(status);
    // Claude resolves notes as it applies them, and that happens server-side
    // with no event of its own. Comparing the counts is enough to notice, and
    // avoids refetching the list on every poll.
    if (status.notes_total !== notes.length
        || status.notes_open !== notes.filter((n) => n.status === 'open').length) {
      await refreshNotes();
    }
    await syncVersion(status.version);
  } catch (error) {
    setStatus(`Lost contact with the viewer server (${error.message}).`, true);
  }
  checkForSilence();
}

function resize() {
  const { clientWidth, clientHeight } = document.documentElement;
  renderer.setSize(clientWidth, clientHeight, false);
  camera.aspect = clientWidth / Math.max(clientHeight, 1);
  camera.updateProjectionMatrix();
}

function tick() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}

byOperationEl.addEventListener('change', recolor);
showGridEl.addEventListener('change', () => {
  if (grid) grid.visible = showGridEl.checked;
});
window.addEventListener('resize', resize);

promptFormEl.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = promptEl.value.trim();
  if (!text) return;
  promptEl.value = '';
  sendPrompt(text);
});

// --------------------------------------------------------------------------- //
// Markup input
// --------------------------------------------------------------------------- //

annotateModeEl.addEventListener('change', () => {
  annotateHelpEl.hidden = !annotating();
  document.body.classList.toggle('annotating', annotating());
  if (!annotating()) cancelSelection();
});

// Marking shares the left button with orbiting, so a click only counts if the
// pointer barely moved. Without this every orbit that ends on the build would
// open the note composer.
canvas.addEventListener('pointerdown', (event) => {
  pointerDownAt = { x: event.clientX, y: event.clientY };
});

canvas.addEventListener('pointerup', (event) => {
  const start = pointerDownAt;
  pointerDownAt = null;
  if (!start || event.button !== 0) return;
  const travelled = Math.hypot(event.clientX - start.x, event.clientY - start.y);
  if (travelled > CLICK_SLOP) return;
  onSceneClick(event);
});

noteComposerEl.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = noteTextEl.value.trim();
  if (!text) return;
  saveNote(text);
});

noteCancelEl.addEventListener('click', cancelSelection);
applyNotesEl.addEventListener('click', applyNotes);

window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  // Escape from a half-made region or an open composer, not from the whole mode:
  // losing the marking mode on a stray keypress would be more annoying.
  if (pendingCorner || pendingTarget) {
    cancelSelection();
    setStatus('');
  }
});

resize();
tick();
connectEvents();
refreshStatus();
refreshNotes();
setInterval(refreshStatus, STATUS_INTERVAL_MS);
