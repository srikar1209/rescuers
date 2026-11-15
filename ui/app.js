const $ = id => document.getElementById(id);
const canvas = $('mapCanvas');
const ctx = canvas.getContext('2d', {alpha: false});
const Z = 14;
const TILE = 256;
const WORLD = TILE * 2 ** Z;
const DEFAULT_CENTER = {lat: 42.37023, lon: -72.539};
const COLORS = [
  [222, 229, 195], [229, 218, 191], [250, 248, 234], [111, 125, 112],
  [112, 164, 183], [139, 184, 196], [177, 197, 143], [139, 174, 135],
  [117, 130, 112], [207, 193, 207], [224, 226, 201], [118, 173, 192]
];
const state = {
  center: geoToWorld(DEFAULT_CENTER), zoom: 14.25, pick: null, drag: null,
  run: null, case: null, evidence: [], notes: [], demoClues: [], revealed: null, minute: 150, version: 0,
  summaryRequest: 0, suggestedPlaces: [], showWalkerDots: true
};
const baseTiles = new Map();
const streetTiles = new Map();
const heatTiles = new Map();
const walkerPointCache = new Map();
const walkerSmudge = document.createElement('canvas');
walkerSmudge.width = walkerSmudge.height = 72;
const smudgeCtx = walkerSmudge.getContext('2d');
const smudgeGradient = smudgeCtx.createRadialGradient(36, 36, 2, 36, 36, 35);
smudgeGradient.addColorStop(0, 'rgba(172, 23, 23, .9)');
smudgeGradient.addColorStop(.25, 'rgba(199, 34, 29, .72)');
smudgeGradient.addColorStop(.6, 'rgba(222, 53, 41, .26)');
smudgeGradient.addColorStop(1, 'rgba(222, 53, 41, 0)');
smudgeCtx.fillStyle = smudgeGradient;
smudgeCtx.fillRect(0, 0, 72, 72);
const AREA_DETAIL_ZOOM = 15;
const LABEL_DETAIL_ZOOM = 15.2;
let drawing = false;
let reopenClueAfterPin = false;
let clueOpener = null;
let cameraMove = null;
let startDescriptionRequest = 0;
let suppressPickClick = false;
const isDarkTheme = () => document.documentElement.dataset.theme === 'dark';
function applyTheme(theme) {
  const dark = theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const label = dark ? 'Switch to light mode' : 'Switch to dark mode';
  $('themeToggle').setAttribute('aria-label', label);
  $('themeToggle').setAttribute('aria-pressed', String(dark));
  $('themeToggle').title = label;
  document.querySelector('meta[name="theme-color"]').content = dark ? '#090b0d' : '#ffffff';
  try { localStorage.setItem('rescuers-theme', dark ? 'dark' : 'light'); } catch { /* Storage may be disabled. */ }
  requestDraw();
}
$('themeToggle').addEventListener('click', () => applyTheme(isDarkTheme() ? 'light' : 'dark'));
applyTheme(isDarkTheme() ? 'dark' : 'light');
$('startLabel').addEventListener('input', () => { startDescriptionRequest++; });

function stopCameraMove() {
  if (!cameraMove) return;
  cancelAnimationFrame(cameraMove.frame);
  cameraMove.resolve();
  cameraMove = null;
}
function animateCamera(center, zoom, duration = 850) {
  stopCameraMove();
  const targetZoom = Math.max(13.5, Math.min(16, zoom));
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    state.center = {...center}; state.zoom = targetZoom; requestDraw();
    return Promise.resolve();
  }
  const from = {...state.center}, fromZoom = state.zoom;
  return new Promise(resolve => {
    const move = {frame: 0, resolve};
    cameraMove = move;
    let started;
    function frame(now) {
      if (cameraMove !== move) return;
      started ??= now;
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      state.center = {x: from.x + (center.x - from.x) * eased,
                      y: from.y + (center.y - from.y) * eased};
      state.zoom = fromZoom + (targetZoom - fromZoom) * eased;
      requestDraw();
      if (t < 1) move.frame = requestAnimationFrame(frame);
      else { cameraMove = null; resolve(); }
    }
    move.frame = requestAnimationFrame(frame);
  });
}

function closeCaseDrawer() {
  document.querySelector('.workspace').classList.remove('case-drawer-open');
  $('caseBackdrop').hidden = true;
  $('closeCasePanel').hidden = true;
  $('caseToggle').setAttribute('aria-expanded', 'false');
  $('casePanel').removeAttribute('role');
  $('casePanel').removeAttribute('aria-modal');
}
function setCaseCollapsed(collapsed) {
  closeCaseDrawer();
  document.querySelector('.workspace').classList.toggle('case-collapsed', collapsed);
  $('caseToggle').hidden = !collapsed;
  requestDraw();
}
function setTimelineOpen(open) {
  $('timeline').classList.toggle('is-open', open);
  $('timelineToggle').setAttribute('aria-expanded', String(open));
  $('timelineToggle').setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' location estimate time controls');
}
$('timelineToggle').addEventListener('click', () =>
  setTimelineOpen(!$('timeline').classList.contains('is-open')));
function toggleCaseDrawer() {
  const workspace = document.querySelector('.workspace');
  if (workspace.classList.contains('case-drawer-open')) {
    closeCaseDrawer();
    return;
  }
  workspace.classList.add('case-drawer-open');
  $('caseBackdrop').hidden = false;
  $('closeCasePanel').hidden = false;
  $('caseToggle').setAttribute('aria-expanded', 'true');
  $('casePanel').setAttribute('role', 'dialog');
  $('casePanel').setAttribute('aria-modal', 'true');
  $('closeCasePanel').focus();
}
$('caseToggle').onclick = toggleCaseDrawer;
$('caseBackdrop').onclick = () => { closeCaseDrawer(); $('caseToggle').focus(); };
$('closeCasePanel').onclick = () => { closeCaseDrawer(); $('caseToggle').focus(); };
document.addEventListener('keydown', event => {
  if (!document.querySelector('.workspace').classList.contains('case-drawer-open')) return;
  if (event.key === 'Escape') {
    closeCaseDrawer();
    $('caseToggle').focus();
  } else if (event.key === 'Tab') {
    const controls = [...$('casePanel').querySelectorAll('button, input, select, textarea, a[href]')]
      .filter(element => !element.disabled && element.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  }
});

function openClueDialog() {
  const fromCaseDrawer = document.querySelector('.workspace').classList.contains('case-drawer-open');
  closeCaseDrawer();
  if (!$('clueDialog').open) {
    clueOpener = fromCaseDrawer ? $('menuButton') : document.activeElement;
    $('clueDialog').showModal();
  }
}
$('menuButton').onclick = openClueDialog;
$('openClueButton').onclick = openClueDialog;
$('closeClueButton').onclick = () => $('clueDialog').close();
$('dismissEvidence').onclick = () => $('clueDialog').close();
$('clueDialog').addEventListener('click', e => {
  const box = $('clueDialog').getBoundingClientRect();
  if (e.target === $('clueDialog') &&
      (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom))
    $('clueDialog').close();
});
$('clueDialog').addEventListener('close', () => {
  if (!reopenClueAfterPin) (clueOpener?.isConnected ? clueOpener : $('menuButton')).focus();
});
function geoToWorld(p) {
  const sin = Math.sin(p.lat * Math.PI / 180);
  return {x: (p.lon + 180) / 360 * WORLD, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * WORLD};
}
function worldToGeo(p) {
  const lon = p.x / WORLD * 360 - 180;
  const lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * p.y / WORLD))) * 180 / Math.PI;
  return {lat, lon};
}
function scale() { return 2 ** (state.zoom - Z); }
function screenToWorld(x, y) {
  const s = scale();
  return {x: state.center.x + (x - canvas.clientWidth / 2) / s,
          y: state.center.y + (y - canvas.clientHeight / 2) / s};
}
function geoToScreen(p) {
  const w = geoToWorld(p), s = scale();
  return {x: canvas.clientWidth / 2 + (w.x - state.center.x) * s,
          y: canvas.clientHeight / 2 + (w.y - state.center.y) * s};
}
function requestDraw() {
  if (drawing) return;
  drawing = true;
  requestAnimationFrame(() => { drawing = false; draw(); });
}
function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Tile unavailable'));
    img.src = url;
  });
}
function pixels(img) {
  const off = document.createElement('canvas');
  off.width = off.height = TILE;
  const c = off.getContext('2d', {willReadFrequently: true});
  c.drawImage(img, 0, 0);
  return c.getImageData(0, 0, TILE, TILE).data;
}
function baseTile(x, y) {
  const key = x + '/' + y;
  if (baseTiles.has(key)) return baseTiles.get(key);
  const item = {status: 'loading'};
  baseTiles.set(key, item);
  Promise.all([
    loadImage('/api/grid-class/' + Z + '/' + x + '/' + y),
    loadImage('/api/terrain/' + Z + '/' + x + '/' + y)
  ]).then(([classImage, terrainImage]) => {
    const classes = pixels(classImage);
    const terrain = pixels(terrainImage);
    const output = document.createElement('canvas');
    output.width = output.height = TILE;
    const c = output.getContext('2d');
    const image = c.createImageData(TILE, TILE);
    const height = i => terrain[i] * 256 + terrain[i + 1] + terrain[i + 2] / 256 - 32768;
    for (let y0 = 0; y0 < TILE; y0++) {
      for (let x0 = 0; x0 < TILE; x0++) {
        const n = y0 * TILE + x0, i = n * 4;
        const klass = classes[i];
        const color = COLORS[klass] || [226, 233, 222];
        const east = Math.min(TILE - 1, x0 + 1) * 4 + y0 * TILE * 4;
        const south = (Math.min(TILE - 1, y0 + 1) * TILE + x0) * 4;
        const gradient = (height(i) - height(east)) + (height(i) - height(south)) * 0.7;
        const shade = Math.max(-22, Math.min(22, gradient * 1.4));
        image.data[i] = Math.max(0, Math.min(255, color[0] + shade));
        image.data[i + 1] = Math.max(0, Math.min(255, color[1] + shade));
        image.data[i + 2] = Math.max(0, Math.min(255, color[2] + shade));
        image.data[i + 3] = 255;
      }
    }
    c.putImageData(image, 0, 0);
    item.canvas = output;
    item.status = 'ready';
    $('mapError').hidden = true;
    requestDraw();
  }).catch(() => {
    item.status = 'error';
    requestDraw();
  });
  return item;
}
function streetTile(z, x, y) {
  const key = z + '/' + x + '/' + y;
  if (streetTiles.has(key)) return streetTiles.get(key);
  const item = {status: 'loading'};
  streetTiles.set(key, item);
  loadImage('https://tile.openstreetmap.org/' + key + '.png').then(img => {
    item.image = img;
    item.status = 'ready';
    requestDraw();
  }).catch(() => { item.status = 'error'; requestDraw(); });
  return item;
}
function heatTile(x, y) {
  if (!state.run || state.run.status !== 'ready') return null;
  const key = state.run.id + '/' + state.version + '/' + state.minute + '/' + x + '/' + y;
  if (heatTiles.has(key)) return heatTiles.get(key);
  const item = {status: 'loading'};
  heatTiles.set(key, item);
  const path = '/api/runs/' + state.run.id + '/heat/' + Z + '/' + x + '/' + y
    + '?minute=' + state.minute + '&version=' + state.version;
  loadImage(path).then(img => {
    item.image = img; item.status = 'ready'; requestDraw();
  }).catch(() => { item.status = 'error'; requestDraw(); });
  return item;
}
function sampledWalkerPoints() {
  if (state.run?.status !== 'ready' || !state.showWalkerDots) return null;
  const key = state.run.id + ':' + state.version + ':' + state.minute;
  if (walkerPointCache.has(key)) return walkerPointCache.get(key);
  const item = {status: 'loading', points: []};
  walkerPointCache.set(key, item);
  api('/api/runs/' + state.run.id + '/walkers?minute=' + state.minute + '&version=' + state.version)
    .then(result => {
      item.points = result.points;
      item.status = 'ready';
      requestDraw();
    }).catch(() => { item.status = 'error'; });
  return item;
}
function drawWalkerSmudges() {
  const sample = sampledWalkerPoints();
  if (sample?.status !== 'ready') return;
  ctx.save();
  const diameter = Math.max(30, Math.min(58, 36 * 2 ** ((state.zoom - 14.5) * .35)));
  ctx.globalAlpha = .58;
  for (const [lat, lon] of sample.points) {
    const p = geoToScreen({lat, lon});
    if (p.x < -diameter || p.y < -diameter || p.x > canvas.clientWidth + diameter || p.y > canvas.clientHeight + diameter) continue;
    ctx.drawImage(walkerSmudge, p.x - diameter / 2, p.y - diameter / 2, diameter, diameter);
  }
  ctx.restore();
}
function drawMarker(p, label, color, size = 7, labels = []) {
  if (!p || !Number.isFinite(Number(p.lat)) || !Number.isFinite(Number(p.lon))) return;
  const s = geoToScreen(p);
  if (s.x < -100 || s.y < -100 || s.x > canvas.clientWidth + 100 || s.y > canvas.clientHeight + 100) return;
  ctx.beginPath(); ctx.arc(s.x, s.y, size + 4, 0, Math.PI * 2);
  ctx.fillStyle = isDarkTheme() ? '#101214' : '#fffdfa'; ctx.fill();
  ctx.beginPath(); ctx.arc(s.x, s.y, size, 0, Math.PI * 2);
  ctx.fillStyle = color; ctx.fill();
  if (label && state.zoom >= LABEL_DETAIL_ZOOM)
    labels.push({x: s.x, y: s.y, text: label.charAt(0) + label.slice(1).toLowerCase(), kind: 'point',
                 priority: label === 'LAST SEEN' ? 0 : label === 'FICTIONAL OUTCOME' ? 1 : 3});
}
function drawSearchCircle(item) {
  const p = geoToScreen(item);
  const metersPerPixel = 156543.03392 * Math.cos(Number(item.lat) * Math.PI / 180) / 2 ** state.zoom;
  const radius = Number(item.radius_m) / metersPerPixel;
  ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = '#d6804d22'; ctx.fill();
  ctx.strokeStyle = isDarkTheme() ? '#f2a06e' : '#b96e3d'; ctx.lineWidth = 2; ctx.setLineDash([5, 5]); ctx.stroke(); ctx.setLineDash([]);
}
function drawProbabilityCircle(circle) {
  if (!circle) return;
  const p = geoToScreen(circle);
  const metersPerPixel = 156543.03392 * Math.cos(Number(circle.lat) * Math.PI / 180) / 2 ** state.zoom;
  const radius = circle.radius_m / metersPerPixel;
  ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.strokeStyle = isDarkTheme() ? '#ff9478' : '#81251f';
  ctx.lineWidth = 2.5;
  ctx.setLineDash([9, 6]);
  ctx.stroke(); ctx.setLineDash([]);
}
function drawSearchArea(area, index, selected = false, labels = []) {
  const p = geoToScreen(area);
  const metersPerPixel = 156543.03392 * Math.cos(Number(area.lat) * Math.PI / 180) / 2 ** state.zoom;
  const radius = area.radius_m / metersPerPixel;
  ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = selected ? '#e28a4640' : '#e8a45b22';
  ctx.fill();
  ctx.strokeStyle = isDarkTheme() ? (selected ? '#ffb08a' : '#ec9272') : (selected ? '#8b3528' : '#a45035');
  ctx.lineWidth = selected ? 3 : 1.75;
  ctx.stroke();
  if (state.zoom >= LABEL_DETAIL_ZOOM)
    labels.push({x: p.x, y: p.y, text: 'Area ' + (index + 1), kind: 'area',
                 priority: selected ? 2 : 4 + index});
}
function rectanglesOverlap(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}
function drawMapLabels(labels) {
  if (state.zoom < LABEL_DETAIL_ZOOM || !labels.length) return;
  ctx.save();
  ctx.font = '700 11px Inter, Arial, sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3.5;
  const occupied = [];
  const canvasRect = canvas.getBoundingClientRect();
  for (const id of ['resultsPanel', 'placeDetail', 'timeline', 'pinHint', 'mapError']) {
    const element = $(id);
    if (element.hidden) continue;
    const rect = element.getBoundingClientRect();
    occupied.push({left: rect.left - canvasRect.left - 5, top: rect.top - canvasRect.top - 5,
                   right: rect.right - canvasRect.left + 5, bottom: rect.bottom - canvasRect.top + 5});
  }
  for (const selector of ['.map-controls', '.walker-dots-toggle', '.map-help', '.map-attribution']) {
    const element = document.querySelector(selector);
    if (!element || element.hidden) continue;
    const rect = element.getBoundingClientRect();
    occupied.push({left: rect.left - canvasRect.left - 5, top: rect.top - canvasRect.top - 5,
                   right: rect.right - canvasRect.left + 5, bottom: rect.bottom - canvasRect.top + 5});
  }
  labels.sort((a, b) => a.priority - b.priority);
  for (const label of labels) {
    const width = ctx.measureText(label.text).width;
    const {x, y} = label;
    const candidates = label.kind === 'area'
      ? [[x - width / 2, y - 24], [x - width / 2, y + 24], [x + 18, y], [x - width - 18, y],
         [x + 18, y - 21], [x - width - 18, y - 21]]
      : [[x + 17, y], [x - width - 17, y], [x - width / 2, y - 24], [x - width / 2, y + 24],
         [x + 17, y - 21], [x - width - 17, y - 21]];
    for (const [tx, ty] of candidates) {
      const box = {left: tx - 5, right: tx + width + 5, top: ty - 11, bottom: ty + 11};
      if (box.left < 8 || box.top < 8 || box.right > canvas.clientWidth - 8 || box.bottom > canvas.clientHeight - 8) continue;
      if (occupied.some(other => rectanglesOverlap(box, other))) continue;
      if (labels.some(other => other !== label && rectanglesOverlap(box,
          {left: other.x - 9, right: other.x + 9, top: other.y - 9, bottom: other.y + 9}))) continue;
      ctx.strokeStyle = isDarkTheme() ? '#101214f2' : '#fffffff2';
      ctx.fillStyle = isDarkTheme() ? '#fff' : '#171717';
      ctx.strokeText(label.text, tx, ty);
      ctx.fillText(label.text, tx, ty);
      occupied.push(box);
      break;
    }
  }
  ctx.restore();
}
function draw() {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const dark = isDarkTheme();
  ctx.filter = 'none';
  ctx.fillStyle = dark ? '#111315' : '#e3ebdf'; ctx.fillRect(0, 0, width, height);
  const s = scale();
  const left = state.center.x - width / (2 * s), top = state.center.y - height / (2 * s);
  const firstX = Math.floor(left / TILE), firstY = Math.floor(top / TILE);
  const lastX = Math.ceil((left + width / s) / TILE), lastY = Math.ceil((top + height / s) / TILE);
  ctx.filter = dark ? 'brightness(.4) saturate(.6)' : 'none';
  for (let y = firstY; y < lastY; y++) for (let x = firstX; x < lastX; x++) {
    const px = Math.round((x * TILE - left) * s), py = Math.round((y * TILE - top) * s);
    const sz = Math.ceil(TILE * s + 1);
    const base = baseTile(x, y);
    if (base.status === 'ready') ctx.drawImage(base.canvas, px, py, sz, sz);
  }
  // Street tiles are only requested for the visible viewport. The local model
  // raster above stays visible if the remote map is unavailable.
  const streetZ = Math.max(14, Math.min(16, Math.round(state.zoom)));
  const ratio = 2 ** (streetZ - Z);
  const span = TILE / ratio;
  const startX = Math.floor(left / span), startY = Math.floor(top / span);
  const endX = Math.ceil((left + width / s) / span), endY = Math.ceil((top + height / s) / span);
  ctx.filter = dark ? 'invert(1) hue-rotate(180deg) brightness(.78) contrast(.92)' : 'none';
  for (let y = startY; y < endY; y++) for (let x = startX; x < endX; x++) {
    if (x < 0 || y < 0 || x >= 2 ** streetZ || y >= 2 ** streetZ) continue;
    const tile = streetTile(streetZ, x, y);
    if (tile.status === 'ready') {
      const px = Math.round((x * span - left) * s), py = Math.round((y * span - top) * s);
      ctx.drawImage(tile.image, px, py, Math.ceil(span * s + 1), Math.ceil(span * s + 1));
    }
  }
  // Keep probability colors and annotations unchanged by the basemap filter.
  ctx.filter = 'none';
  if (state.run?.status === 'ready') {
    for (let y = firstY; y < lastY; y++) for (let x = firstX; x < lastX; x++) {
      const overlay = heatTile(x, y);
      if (overlay?.status !== 'ready') continue;
      const px = Math.round((x * TILE - left) * s), py = Math.round((y * TILE - top) * s);
      ctx.drawImage(overlay.image, px, py, Math.ceil(TILE * s + 1), Math.ceil(TILE * s + 1));
    }
    drawWalkerSmudges();
    if (state.zoom >= AREA_DETAIL_ZOOM) drawProbabilityCircle(state.circle80);
  }
  const labels = [];
  if (state.case?.start) drawMarker(state.case.start, 'LAST SEEN', '#1b6750', 7, labels);
  if (state.case?.goal) drawMarker(state.case.goal, 'POSSIBLE GOAL', '#527c9b', 6, labels);
  for (const item of state.evidence) {
    if (item.type === 'area_searched') drawSearchCircle(item);
    drawMarker(item, item.type === 'area_searched' ? 'SEARCHED' : item.type === 'sighting' ? 'SIGHTING' : 'CAMERA', '#bb6b3e', 5, labels);
  }
  if (state.revealed) drawMarker(state.revealed, 'FICTIONAL OUTCOME', '#26392f', 8, labels);
  if (state.zoom >= AREA_DETAIL_ZOOM) state.suggestedPlaces.forEach((area, index) =>
    drawSearchArea(area, index, state.selectedPlace?.index === index, labels));
  if (!state.case && $('startLat').value && $('startLon').value)
    drawMarker({lat: Number($('startLat').value), lon: Number($('startLon').value)}, 'LAST SEEN', '#1b6750', 7, labels);
  if (!state.case && $('goalLat').value && $('goalLon').value)
    drawMarker({lat: Number($('goalLat').value), lon: Number($('goalLon').value)}, 'POSSIBLE GOAL', '#527c9b', 6, labels);
  drawMapLabels(labels);
}
function setPick(kind) {
  state.pick = state.pick === kind ? null : kind;
  $('pinHint').hidden = !state.pick;
  document.querySelectorAll('[data-pin]').forEach(button => button.classList.toggle('active', button.dataset.pin === state.pick));
  canvas.style.cursor = state.pick ? 'crosshair' : 'grab';
  if (state.pick && matchMedia('(max-width: 700px)').matches)
    document.querySelector('.map-stage').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function describeStartPoint(point) {
  const request = ++startDescriptionRequest;
  const coordinateLabel = 'Map point · ' + point.lat.toFixed(6) + ', ' + point.lon.toFixed(6);
  $('startLabel').value = coordinateLabel;
  try {
    const result = await api('/api/place?lat=' + point.lat.toFixed(6) + '&lon=' + point.lon.toFixed(6));
    if (request === startDescriptionRequest && result.name)
      $('startLabel').value = result.description.slice(0, 120);
  } catch {
    // The coordinate description remains useful if the optional name lookup fails.
  }
}
function setPin(kind, point) {
  stopCameraMove();
  const ids = kind === 'start' ? ['startLat', 'startLon'] : kind === 'goal' ? ['goalLat', 'goalLon'] : ['evidenceLat', 'evidenceLon'];
  $(ids[0]).value = point.lat.toFixed(6); $(ids[1]).value = point.lon.toFixed(6);
  if (kind === 'start') {
    state.center = geoToWorld(point);
    describeStartPoint(point);
  }
  if (kind !== 'evidence') $(ids[0]).dispatchEvent(new Event('input', {bubbles: true}));
  setPick(null);
  if (kind === 'start') status('runStatus', 'Last-seen point set to ' + point.lat.toFixed(6) + ', ' + point.lon.toFixed(6) + '.');
  requestDraw();
  if (kind === 'evidence' && reopenClueAfterPin) {
    reopenClueAfterPin = false;
    openClueDialog();
  } else if (matchMedia('(max-width: 700px)').matches) {
    $('caseForm').scrollIntoView({behavior: 'smooth', block: 'start'});
  }
}
canvas.addEventListener('pointerdown', e => {
  stopCameraMove();
  state.userMovedMap = true;
  canvas.setPointerCapture(e.pointerId);
  state.drag = {x: e.clientX, y: e.clientY, cx: state.center.x, cy: state.center.y, moved: false};
});
canvas.addEventListener('pointermove', e => {
  if (!state.drag) return;
  const dx = e.clientX - state.drag.x, dy = e.clientY - state.drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 5) state.drag.moved = true;
  if (state.drag.moved) {
    state.center.x = state.drag.cx - dx / scale();
    state.center.y = state.drag.cy - dy / scale();
    requestDraw();
  }
});
canvas.addEventListener('pointerup', e => {
  const dragged = !!state.drag?.moved;
  if (state.drag && !dragged && state.pick) {
    const box = canvas.getBoundingClientRect();
    setPin(state.pick, worldToGeo(screenToWorld(e.clientX - box.left, e.clientY - box.top)));
  }
  state.drag = null;
  if (dragged) {
    suppressPickClick = true;
    setTimeout(() => { suppressPickClick = false; }, 0);
  }
});
canvas.addEventListener('pointercancel', () => { state.drag = null; });
canvas.addEventListener('click', e => {
  if (suppressPickClick || !state.pick) return;
  const box = canvas.getBoundingClientRect();
  setPin(state.pick, worldToGeo(screenToWorld(e.clientX - box.left, e.clientY - box.top)));
});
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  stopCameraMove();
  state.userMovedMap = true;
  const box = canvas.getBoundingClientRect();
  const x = e.clientX - box.left, y = e.clientY - box.top;
  const before = screenToWorld(x, y);
  state.zoom = Math.max(13.5, Math.min(16, state.zoom + (e.deltaY < 0 ? 0.25 : -0.25)));
  const after = screenToWorld(x, y);
  state.center.x += before.x - after.x;
  state.center.y += before.y - after.y;
  requestDraw();
}, {passive: false});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !state.pick) return;
  const returnToClue = state.pick === 'evidence' && reopenClueAfterPin;
  setPick(null);
  reopenClueAfterPin = false;
  if (returnToClue) openClueDialog();
});
document.querySelectorAll('[data-pin]').forEach(button => button.addEventListener('click', () => {
  if (button.dataset.pin === 'evidence' && $('clueDialog').open) {
    reopenClueAfterPin = true;
    $('clueDialog').close();
  }
  if (button.dataset.pin !== 'evidence') closeCaseDrawer();
  setPick(button.dataset.pin);
}));
$('zoomIn').onclick = () => { stopCameraMove(); state.userMovedMap = true; state.zoom = Math.min(16, state.zoom + 0.5); requestDraw(); };
$('zoomOut').onclick = () => { stopCameraMove(); state.userMovedMap = true; state.zoom = Math.max(13.5, state.zoom - 0.5); requestDraw(); };
$('recenter').onclick = () => {
  stopCameraMove();
  state.userMovedMap = true;
  const lat = Number($('startLat').value), lon = Number($('startLon').value);
  animateCamera(geoToWorld(lat && lon ? {lat, lon} : DEFAULT_CENTER), 14.25);
};
$('focusEstimate').onclick = () => {
  if (!state.peakPlace) return;
  const radius = state.circle80?.radius_m || 500;
  const obscured = matchMedia('(max-width: 700px)').matches ? 0 : $('resultsPanel').getBoundingClientRect().width + 18;
  const available = Math.max(260, Math.min(canvas.clientWidth - obscured - 48, canvas.clientHeight - 150));
  const metersPerPixel = (2 * radius) / available;
  const zoom = Math.log2(156543.03392 * Math.cos(state.peakPlace.lat * Math.PI / 180) / metersPerPixel);
  const targetZoom = Math.max(13.5, Math.min(15.5, zoom));
  const center = geoToWorld(state.peakPlace);
  center.x += obscured / (2 * 2 ** (targetZoom - Z));
  animateCamera(center, targetZoom, 1000);
};
$('walkerDotsToggle').addEventListener('click', () => {
  state.showWalkerDots = !state.showWalkerDots;
  $('walkerDotsToggle').setAttribute('aria-pressed', String(state.showWalkerDots));
  requestDraw();
});
new ResizeObserver(requestDraw).observe(canvas);

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function status(id, message, error = false) {
  $(id).textContent = message;
  $(id).classList.toggle('error', error);
}
function minutesBetween(start, end) {
  const a = start.split(':').map(Number), b = end.split(':').map(Number);
  return ((b[0] * 60 + b[1]) - (a[0] * 60 + a[1]) + 1440) % 1440;
}
function addMinutes(time, minutes) {
  const parts = time.split(':').map(Number);
  const total = (parts[0] * 60 + parts[1] + minutes) % 1440;
  return String(Math.floor(total / 60)).padStart(2, '0') + ':' + String(total % 60).padStart(2, '0');
}
function formCase() {
  const start = {lat: Number($('startLat').value), lon: Number($('startLon').value),
                 time: $('lastSeenTime').value, label: $('startLabel').value.trim()};
  if (!$('startLat').value || !$('startLon').value) throw new Error('Set a last-seen point in Amherst.');
  if (!start.time || !$('analysisTime').value) throw new Error('Enter last-seen and estimate-as-of times.');
  const elapsed = minutesBetween(start.time, $('analysisTime').value);
  if (elapsed > 240) throw new Error('Estimate-as-of time must be within four hours of last seen.');
  const goalPresent = $('goalLat').value || $('goalLon').value;
  if (goalPresent && (!$('goalLat').value || !$('goalLon').value)) throw new Error('Set both goal coordinates.');
  const goal = goalPresent ? {lat: Number($('goalLat').value), lon: Number($('goalLon').value),
                              label: $('goalLabel').value.trim()} : null;
  return {name: $('personName').value.trim(), age: $('personAge').value || null,
          condition: $('personCondition').value.trim(), start, analysis_time: $('analysisTime').value,
          heading: $('heading').value === '' ? null : Number($('heading').value), goal};
}
async function runCase(event) {
  event?.preventDefault();
  try {
    const value = formCase();
    setCaseCollapsed(false);
    $('runButton').disabled = true;
    state.hasFocusedRun = false;
    state.focusOnNextSummary = false;
    state.userMovedMap = false;
    state.peakPlace = null;
    state.circle80 = null;
    state.selectedPlace = null;
    state.suggestedPlaces = [];
    $('placeDetail').hidden = true;
    $('placeList').replaceChildren();
    $('placeListStatus').hidden = true;
    $('addEvidence').disabled = true;
    $('clueRunHint').textContent = 'Your draft is saved here. Run the walkers before applying it to the heatmap.';
    $('evidenceSection').hidden = true;
    $('resultsPanel').hidden = true;
    setTimelineOpen(false);
    $('timeline').hidden = true;
    $('focusEstimate').hidden = true;
    $('walkerDotsToggle').hidden = true;
    status('runStatus', 'Running 5,000 Amherst walkers. This can take a little while…');
    state.run = null;
    state.case = value;
    state.evidence = [];
    state.revealed = null;
    state.version = 0;
    heatTiles.clear();
    walkerPointCache.clear();
    state.initialCameraMove = animateCamera(geoToWorld(value.start), Math.max(state.zoom + 0.55, 15.15));
    const newRun = await api('/api/runs', {method: 'POST', body: JSON.stringify(value)});
    state.run = newRun; state.evidence = []; state.revealed = null; state.version = 0;
    $('revealMessage').hidden = true;
    state.minute = minutesBetween(value.start.time, value.analysis_time);
    heatTiles.clear();
    requestDraw();
    await waitForRun(newRun.id);
  } catch (error) {
    setCaseCollapsed(false);
    status('runStatus', error.message, true);
    $('runButton').disabled = false;
  }
}
async function waitForRun(id) {
  while (state.run?.id === id) {
    const run = await api('/api/runs/' + id);
    state.run = run;
    if (run.status === 'error') throw new Error(run.error || 'Simulation failed');
    if (run.status === 'ready') {
      $('runButton').disabled = false;
      $('addEvidence').disabled = false;
      $('clueRunHint').textContent = 'Review the pin, time, and assumptions before applying this clue.';
      status('runStatus', 'Heatmap ready. Calibrated walkers account for no public report by ' + state.case.analysis_time + '. Add clues to update it.');
      $('evidenceSection').hidden = false;
      $('resultsPanel').hidden = false;
      setTimelineOpen(false);
      $('placeListStatus').textContent = 'Ranking search areas…';
      $('placeListStatus').hidden = false;
      $('timeline').hidden = false;
      $('focusEstimate').hidden = false;
      $('walkerDotsToggle').hidden = false;
      $('timeStart').textContent = state.case.start.time;
      $('timeEnd').textContent = state.case.analysis_time;
      $('minuteSlider').max = state.minute;
      $('minuteSlider').value = state.minute;
      $('timeLabel').textContent = addMinutes(state.case.start.time, state.minute);
      renderEvidence();
      setCaseCollapsed(true);
      await updateSummary();
      requestDraw();
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 850));
  }
}
$('caseForm').addEventListener('submit', runCase);
$('caseForm').addEventListener('input', event => {
  const modelFields = new Set(['lastSeenTime', 'analysisTime', 'startLat', 'startLon', 'heading', 'goalLat', 'goalLon']);
  if (!modelFields.has(event.target.id) || !state.run) {
    if (state.run?.status === 'ready') renderEvidence();
    return;
  }
  state.demoClues = [];
  state.run = null; state.case = null; state.evidence = []; state.notes = []; state.revealed = null; state.version = 0;
  setCaseCollapsed(false);
  state.circle80 = null; state.selectedPlace = null; $('placeDetail').hidden = true;
  state.suggestedPlaces = [];
  $('addEvidence').disabled = true;
  $('clueRunHint').textContent = 'You can draft a clue now. Run the walkers before applying it to the heatmap.';
  $('evidenceSection').hidden = true; $('resultsPanel').hidden = true; $('timeline').hidden = true;
  setTimelineOpen(false);
  $('focusEstimate').hidden = true;
  $('walkerDotsToggle').hidden = true;
  heatTiles.clear();
  walkerPointCache.clear();
  status('runStatus', 'Starting inputs changed. Run the walkers again.');
  requestDraw();
});
function renderEvidence() {
  const list = $('evidenceList');
  list.replaceChildren();
  $('evidenceCount').textContent = state.evidence.length;
  for (const item of state.evidence) {
    const box = document.createElement('div'); box.className = 'evidence-item';
    const info = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = item.type === 'sighting' ? 'Sighting' : item.type === 'camera_negative' ? 'Camera: no match' : 'Area searched';
    const detail = document.createElement('small');
    detail.textContent = (item.text || (Number(item.lat).toFixed(5) + ', ' + Number(item.lon).toFixed(5)))
      + ' · ' + (item.time || item.window.join('–'));
    info.append(title, detail);
    const actions = document.createElement('div');
    const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Edit';
    edit.onclick = () => editEvidence(item);
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove';
    remove.onclick = () => replaceEvidence(state.evidence.filter(x => x.id !== item.id));
    actions.append(edit, remove); box.append(info, actions); list.append(box);
  }
  state.notes.forEach((note, index) => {
    const box = document.createElement('div'); box.className = 'evidence-item';
    const info = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = 'Note · not used in model';
    const detail = document.createElement('small'); detail.textContent = note;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove';
    remove.onclick = () => { state.notes.splice(index, 1); renderEvidence(); };
    info.append(title, detail); box.append(info, remove); list.append(box);
  });
  const demos = $('demoClues'); demos.replaceChildren();
  const pending = state.demoClues.filter(c => !state.evidence.some(e => String(e.id) === String(c.id)));
  demos.hidden = !pending.length;
  $('revealButton').hidden = !state.demoClues.length || !!pending.length || !!state.revealed;
  pending.slice(0, 1).forEach(clue => {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Add demo clue ' + clue.id + ': ' + clue.text;
    button.onclick = () => addDemoClue(clue);
    demos.append(button);
  });
  requestDraw();
}
function editEvidence(item) {
  $('evidenceType').value = item.type;
  showKindFields();
  $('evidenceText').value = item.text || '';
  $('evidenceLat').value = item.lat;
  $('evidenceLon').value = item.lon;
  if (item.type === 'sighting') {
    $('sightingTime').value = item.time; $('reliability').value = item.reliability; $('errorMeters').value = item.error_m;
  } else if (item.type === 'camera_negative') {
    $('cameraFrom').value = item.window[0]; $('cameraTo').value = item.window[1];
    $('cameraRange').value = item.range_m; $('cameraMiss').value = item.miss_rate;
  } else {
    $('searchTime').value = item.time; $('searchRadius').value = item.radius_m; $('searchPod').value = item.pod;
  }
  state.editingId = item.id;
  $('addEvidence').firstChild.textContent = 'Save evidence ';
  openClueDialog();
}
function showKindFields() {
  const type = $('evidenceType').value;
  $('sightingFields').hidden = type !== 'sighting';
  $('cameraFields').hidden = type !== 'camera_negative';
  $('searchFields').hidden = type !== 'area_searched';
  $('sightingTime').required = type === 'sighting';
  $('cameraFrom').required = $('cameraTo').required = type === 'camera_negative';
  $('searchTime').required = $('searchRadius').required = type === 'area_searched';
  $('weightRule').textContent = type === 'sighting'
    ? 'Weight update: paths near this pin around the reported time gain relative weight. Witness uncertainty keeps other paths possible.'
    : type === 'camera_negative'
      ? 'Weight update: paths passing within camera range during this window lose weight according to the miss rate.'
      : 'Weight update: paths inside the searched circle at completion lose weight according to the detection estimate.';
}
$('evidenceType').addEventListener('change', showKindFields);
function formEvidence() {
  if (!$('evidenceLat').value || !$('evidenceLon').value) throw new Error('Place an evidence pin on the Amherst map.');
  const type = $('evidenceType').value;
  const item = {id: state.editingId || String(Date.now()) + Math.random().toString(16).slice(2),
                type, lat: Number($('evidenceLat').value), lon: Number($('evidenceLon').value),
                text: $('evidenceText').value.trim()};
  if (type === 'sighting') Object.assign(item, {time: $('sightingTime').value,
    reliability: Number($('reliability').value), error_m: Number($('errorMeters').value)});
  else if (type === 'camera_negative') Object.assign(item, {window: [$('cameraFrom').value, $('cameraTo').value],
    range_m: Number($('cameraRange').value), miss_rate: Number($('cameraMiss').value)});
  else Object.assign(item, {time: $('searchTime').value, radius_m: Number($('searchRadius').value),
    pod: Number($('searchPod').value)});
  return item;
}
async function replaceEvidence(items, focusPoint = null) {
  if (!state.run || state.run.status !== 'ready') return;
  $('addEvidence').disabled = true;
  try {
    const run = await api('/api/runs/' + state.run.id + '/evidence',
      {method: 'PUT', body: JSON.stringify(items)});
    state.run = run; state.evidence = run.evidence; state.version = run.version;
    state.editingId = null; $('addEvidence').firstChild.textContent = 'Accept and update map ';
    state.focusOnNextSummary = !focusPoint;
    heatTiles.clear(); walkerPointCache.clear(); renderEvidence(); await updateSummary();
    const effect = run.weight_update;
    const change = effect ? ' Effective walkers: ' + Math.round(effect.ess_before).toLocaleString()
      + ' → ' + Math.round(effect.ess_after).toLocaleString() + '.' : '';
    const message = 'Estimate updated from ' + state.evidence.length + ' accepted clue(s).' + change;
    status('evidenceStatus', message);
    status('runStatus', message);
    if ($('clueDialog').open) $('clueDialog').close();
    if (focusPoint) animateCamera(geoToWorld(focusPoint), Math.max(state.zoom, 15.6));
  } catch (error) {
    status('evidenceStatus', error.message, true);
  } finally { $('addEvidence').disabled = false; }
}
$('evidenceForm').addEventListener('submit', e => {
  e.preventDefault();
  try {
    const item = formEvidence();
    const others = state.evidence.filter(x => x.id !== item.id);
    replaceEvidence([...others, item], item);
  } catch (error) { status('evidenceStatus', error.message, true); }
});
async function addDemoClue(clue) {
  const item = {...clue, id: String(clue.id)};
  if (item.type === 'sighting') { item.reliability = 0.8; item.error_m = 100; }
  if (item.type === 'camera_negative') { item.range_m = 30; item.miss_rate = 0.1; }
  await replaceEvidence([...state.evidence, item], item);
}
$('revealButton').onclick = async () => {
  try {
    const outcome = await api('/api/demo/reveal');
    state.revealed = outcome;
    $('revealMessage').textContent = 'Fictional outcome: ' + outcome.label
      + '. This location was never provided to the walkers or clue weighting.';
    $('revealMessage').hidden = false;
    animateCamera(geoToWorld(outcome), 15.25);
    renderEvidence(); requestDraw();
  } catch (error) { status('evidenceStatus', error.message, true); }
};
function areaRelativeName(place) {
  const start = state.case?.start;
  if (!start) return 'Search area';
  const north = (place.lat - start.lat) * 111200;
  const east = (place.lon - start.lon) * 111200 * Math.cos(start.lat * Math.PI / 180);
  const distance = Math.hypot(north, east);
  if (distance < 20) return 'Near last-seen point';
  const directions = ['North', 'Northeast', 'East', 'Southeast', 'South', 'Southwest', 'West', 'Northwest'];
  const bearing = (Math.atan2(east, north) * 180 / Math.PI + 360) % 360;
  const direction = directions[Math.round(bearing / 45) % directions.length];
  return direction + ' of last seen · ~' + (Math.round(distance / 10) * 10) + ' m';
}
async function selectSuggestedPlace(place, index) {
  state.selectedPlace = {...place, index};
  animateCamera(geoToWorld(place), 15.25);
  $('placeDetail').hidden = false;
  $('placeName').textContent = 'Area ' + String(index + 1).padStart(2, '0') + ' · ' + areaRelativeName(place);
  $('placeContext').textContent = 'Local concentration rank ' + (index + 1) + ' · Predominant model terrain: ' + place.terrain;
  $('placeCoordinates').textContent = place.radius_m + ' m radius · ' + (place.probability * 100).toFixed(1) + '% of total modeled location probability in this circle';
  $('placeOsmLink').href = 'https://www.openstreetmap.org/?mlat=' + place.lat.toFixed(6)
    + '&mlon=' + place.lon.toFixed(6) + '#map=18/' + place.lat.toFixed(6) + '/' + place.lon.toFixed(6);
  requestDraw();
  try {
    const response = await fetch('/api/place?lat=' + place.lat.toFixed(6) + '&lon=' + place.lon.toFixed(6));
    if (response.status === 404)
      throw new Error('Place lookup is missing from the running server. Restart the local server.');
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || 'Place lookup failed (HTTP ' + response.status + ').');
    }
    const result = await response.json();
    if (typeof result.description !== 'string') throw new Error('Place lookup returned an invalid response.');
    if (state.selectedPlace?.lat !== place.lat || state.selectedPlace?.lon !== place.lon) return;
    if (result.name) $('placeName').textContent = 'Area ' + String(index + 1).padStart(2, '0') + ' · ' + result.description;
  } catch (error) {
    if (state.selectedPlace?.lat === place.lat && state.selectedPlace?.lon === place.lon)
      $('placeName').textContent = 'Area ' + String(index + 1).padStart(2, '0') + ' · ' + areaRelativeName(place);
  }
}
$('closePlaceDetail').onclick = () => {
  state.selectedPlace = null;
  $('placeDetail').hidden = true;
  requestDraw();
};
async function updateSummary() {
  if (!state.run || state.run.status !== 'ready') return;
  const request = ++state.summaryRequest;
  try {
    const result = await api('/api/runs/' + state.run.id + '/summary?minute=' + state.minute);
    if (request !== state.summaryRequest || result.version !== state.version) return;
    $('area80').textContent = Number(result.area80_km2).toFixed(2) + ' km²';
    $('ess').textContent = Math.round(result.ess).toLocaleString();
    $('essWarning').hidden = result.ess >= 1000;
    state.selectedPlace = null;
    $('placeDetail').hidden = true;
    const places = Array.isArray(result.areas) ? result.areas.slice(0, 3) : [];
    state.suggestedPlaces = places;
    const list = $('placeList'); list.replaceChildren();
    places.forEach((place, index) => {
      const li = document.createElement('li'), number = document.createElement('b'), button = document.createElement('button');
      number.textContent = String(index + 1).padStart(2, '0');
      button.type = 'button';
      const terrain = document.createElement('strong'), detail = document.createElement('small');
      terrain.textContent = areaRelativeName(place);
      detail.textContent = place.radius_m + ' m radius · ' + ['Highest', 'Second-highest', 'Third-highest'][index] + ' local concentration  ↗';
      button.append(terrain, detail);
      button.title = 'Focus this search area on the map';
      button.onclick = () => selectSuggestedPlace(place, index);
      li.append(number, button); list.append(li);
    });
    state.peakPlace = places[0] || null;
    state.circle80 = result.circle80 || null;
    $('circleRadius').textContent = state.circle80
      ? (state.circle80.radius_m / 1000).toFixed(2) + ' km' : 'Unavailable';
    const listStatus = $('placeListStatus');
    listStatus.hidden = places.length === 3 && !!state.circle80;
    if (!places.length) listStatus.textContent = 'No search areas returned. Restart the local server and run the case again.';
    else if (!state.circle80) listStatus.textContent = 'Search areas loaded. Restart the local server to update the distance ring.';
    else if (places.length < 3) listStatus.textContent = 'This estimate has ' + places.length + ' strong heatmap peak' + (places.length === 1 ? '' : 's') + ' large enough to show.';
    if ((!state.hasFocusedRun || state.focusOnNextSummary) && state.peakPlace) {
      const focusAfterEvidence = state.focusOnNextSummary;
      state.hasFocusedRun = true;
      state.focusOnNextSummary = false;
      await state.initialCameraMove;
      if (request !== state.summaryRequest) return;
      if (!state.userMovedMap || focusAfterEvidence) $('focusEstimate').click();
    }
    requestDraw();
  } catch (error) {
    status('runStatus', error.message, true);
    $('placeListStatus').textContent = 'Could not load search areas: ' + error.message;
    $('placeListStatus').hidden = false;
  }
}
$('minuteSlider').addEventListener('input', e => {
  state.minute = Number(e.target.value);
  $('timeLabel').textContent = addMinutes(state.case.start.time, state.minute);
  if (heatTiles.size > 100) heatTiles.clear();
  if (walkerPointCache.size > 16) walkerPointCache.clear();
  requestDraw();
  clearTimeout(state.summaryTimer);
  state.summaryTimer = setTimeout(updateSummary, 180);
});
$('extractButton').onclick = async () => {
  const text = $('evidenceText').value.trim();
  if (!text) { $('extractStatus').textContent = 'Enter clue text first.'; return; }
  $('extractButton').disabled = true;
  $('extractStatus').textContent = 'Extracting a draft for review…';
  try {
    const result = await api('/api/extract', {method: 'POST', body: JSON.stringify({text})});
    const draft = result.draft;
    if (!['sighting', 'camera_negative', 'area_searched'].includes(draft.type)) {
      $('extractStatus').textContent = 'No supported clue type found. Keep this as a note or enter fields manually.';
      return;
    }
    $('evidenceType').value = draft.type; showKindFields();
    for (const id of ['sightingTime', 'cameraFrom', 'cameraTo', 'searchTime', 'searchRadius',
                      'evidenceLat', 'evidenceLon']) $(id).value = '';
    if (draft.time && draft.type !== 'camera_negative')
      $(draft.type === 'area_searched' ? 'searchTime' : 'sightingTime').value = draft.time;
    if (Array.isArray(draft.window) && draft.window.length === 2) {
      $('cameraFrom').value = draft.window[0]; $('cameraTo').value = draft.window[1];
    }
    if (draft.radius_m != null && draft.type === 'area_searched') $('searchRadius').value = draft.radius_m;
    if (draft.lat != null && draft.lon != null) {
      $('evidenceLat').value = Number(draft.lat).toFixed(6);
      $('evidenceLon').value = Number(draft.lon).toFixed(6);
    }
    requestDraw();
    $('extractStatus').textContent = 'Draft ready' + (draft.location_text ? ' for ' + draft.location_text : '')
      + '. Confirm the time, search radius if relevant, and map pin before accepting. Missing facts were left blank.';
  } catch (error) { $('extractStatus').textContent = error.message + ' Use the fields below instead.'; }
  finally { $('extractButton').disabled = false; }
};
$('saveNote').onclick = () => {
  const note = $('evidenceText').value.trim();
  if (!note) { $('extractStatus').textContent = 'Enter a note first.'; return; }
  state.notes.push(note);
  $('evidenceText').value = '';
  $('extractStatus').textContent = 'Saved as context only. It did not change the model.';
  renderEvidence();
};
$('demoButton').onclick = async () => {
  try {
    const demo = await api('/api/demo');
    state.notes = [];
    $('personName').value = demo.person.name;
    $('personAge').value = demo.person.age;
    $('personCondition').value = demo.person.condition;
    $('lastSeenTime').value = demo.start.last_seen_time;
    $('analysisTime').value = '21:00';
    $('startLat').value = demo.start.lat;
    $('startLon').value = demo.start.lon;
    $('startLabel').value = demo.start.label;
    $('heading').value = '';
    $('goalLabel').value = '';
    $('goalLat').value = ''; $('goalLon').value = '';
    state.demoClues = demo.clues;
    await runCase();
  } catch (error) { status('runStatus', error.message, true); }
};
showKindFields();
api('/api/health').then(health => {
  if (!health.grid) {
    $('mapError').hidden = false;
    $('mapError').textContent = 'The Amherst grid is missing. Add data/grid.npz and restart the server.';
  }
}).catch(() => {
  $('mapError').hidden = false;
  $('mapError').textContent = 'Start the local server with python3 ui/serve.py, then reload this page.';
});
requestDraw();
