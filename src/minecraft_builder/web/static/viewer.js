/**
 * 3D viewer for generated Minecraft structures.
 *
 * The whole build is one InstancedMesh with a per-instance colour, so it draws in
 * a single call regardless of block count. Fully enclosed voxels never reach the
 * browser — the server drops them — so what arrives is already just the shell.
 *
 * Colours are flat: Minecraft's textures are Mojang's and can't be shipped. For
 * judging a build, directional shading over flat colour reads the silhouette and
 * material choices well enough, which is what this phase is meant to answer.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const POLL_INTERVAL_MS = 1000;

const canvas = document.getElementById('scene');
const titleEl = document.getElementById('title');
const subtitleEl = document.getElementById('subtitle');
const legendEl = document.getElementById('legend');
const statusEl = document.getElementById('status');
const byOperationEl = document.getElementById('by-operation');
const showGridEl = document.getElementById('show-grid');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Hemisphere light keeps downward faces from going pure black; the directional
// light is what makes edges legible on flat-coloured cubes.
scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 1.5));
const sun = new THREE.DirectionalLight(0xffffff, 1.5);
sun.position.set(0.6, 1, 0.35);
scene.add(sun);

const CUBE = new THREE.BoxGeometry(1, 1, 1);

/** Current payload and the scene objects built from it. */
let payload = null;
let mesh = null;
let grid = null;
let axes = null;
let lastVersion = -1;

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle('error', isError);
}

function disposeBuild() {
  for (const object of [mesh, grid, axes]) {
    if (!object) continue;
    scene.remove(object);
    // Instanced meshes hold GPU buffers; dropping the reference is not enough.
    if (object.dispose) object.dispose();
    // A mesh's dispose() leaves its material alone, since materials are often
    // shared. Ours is built per structure, and the viewer rebuilds on every
    // revision, so it has to go too or each new version leaks one.
    if (object.material && object.material.dispose) object.material.dispose();
  }
  mesh = grid = axes = null;
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

  const paletteColors = palette.map((entry) => new THREE.Color(entry.color));
  const material = new THREE.MeshLambertMaterial();
  mesh = new THREE.InstancedMesh(CUBE, material, count);

  const matrix = new THREE.Matrix4();
  const scratch = new THREE.Color();
  const useOperation = byOperationEl.checked;

  for (let i = 0; i < count; i++) {
    const base = i * stride;
    // +0.5 centres the cube in its cell, matching how a Minecraft block
    // occupies the volume between its coordinate and the next.
    matrix.setPosition(
      voxels[base] + 0.5,
      voxels[base + 1] + 0.5,
      voxels[base + 2] + 0.5,
    );
    mesh.setMatrixAt(i, matrix);
    const color = useOperation
      ? operationColor(voxels[base + 4], scratch)
      : paletteColors[voxels[base + 3]];
    mesh.setColorAt(i, color);
  }
  mesh.instanceMatrix.needsUpdate = true;
  mesh.instanceColor.needsUpdate = true;
  scene.add(mesh);

  addHelpers(bounds);
  frameCamera(bounds);
}

function addHelpers(bounds) {
  const [minX, minY, minZ] = bounds.min;
  const [sizeX, , sizeZ] = bounds.size;
  const span = Math.max(sizeX, sizeZ) + 8;
  const centreX = minX + sizeX / 2;
  const centreZ = minZ + sizeZ / 2;

  grid = new THREE.GridHelper(span, span, 0x3a3f47, 0x272b31);
  grid.position.set(centreX, minY, centreZ);
  grid.visible = showGridEl.checked;
  scene.add(grid);

  // Anchored at the build's own origin corner so X/Z orientation is readable,
  // which matters when comparing against the coordinates in the source JSON.
  axes = new THREE.AxesHelper(Math.min(6, span / 3));
  axes.position.set(minX, minY, minZ);
  scene.add(axes);
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
  if (!mesh || !payload) return;
  const { voxels, stride, palette } = payload;
  const paletteColors = palette.map((entry) => new THREE.Color(entry.color));
  const scratch = new THREE.Color();
  const useOperation = byOperationEl.checked;
  for (let i = 0; i < voxels.length / stride; i++) {
    const base = i * stride;
    mesh.setColorAt(i, useOperation
      ? operationColor(voxels[base + 4], scratch)
      : paletteColors[voxels[base + 3]]);
  }
  mesh.instanceColor.needsUpdate = true;
}

async function fetchPayload() {
  const response = await fetch('/api/structure', { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  applyPayload(await response.json());
}

/**
 * Poll for a new version rather than pushing. The version endpoint is a single
 * integer, so this is cheap, and it keeps this phase free of a streaming
 * transport that the two-way channel will bring its own design for.
 */
async function poll() {
  try {
    const response = await fetch('/api/version', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const { version } = await response.json();
    if (version !== lastVersion) {
      lastVersion = version;
      await fetchPayload();
    }
  } catch (error) {
    setStatus(`Lost contact with the viewer server (${error.message}).`, true);
  }
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

resize();
tick();
poll();
setInterval(poll, POLL_INTERVAL_MS);
