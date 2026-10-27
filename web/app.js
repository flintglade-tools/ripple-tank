// Ripple Tank browser controller. All numerical state lives in the worker's Rust/WebAssembly engine;
// this module draws the engine's pixels, the calibrated overlay, the probe trace and the controls.
const $ = id => document.getElementById(id);
const canvas = $('tank'), ctx = canvas.getContext('2d'), overlay = $('tank-overlay'), oc = overlay.getContext('2d');
const trace = $('trace'), tc = trace.getContext('2d'), colorbar = $('colorbar'), cb = colorbar.getContext('2d');
const frame = $('frame'), workspace = canvas.closest('.ripple-workspace'), sourceList = $('source-list');
const sourceLegend = sourceList.querySelector('legend');
const workerURL = new URL('./ripple-worker.js', import.meta.url);
workerURL.search = new URL(import.meta.url).search;
const worker = new Worker(workerURL, {type: 'module'});
const accent = getComputedStyle(workspace).getPropertyValue('--rt-accent').trim() || '#bdccdd';
let loadedSnapshot = null;
let nextId = 1, state, wanted = false, tool = 'pulse', history = [], position = {x: 0.5, y: 0.5};
let probe = {x: 0.72, y: 0.5}, sample = null, pending = new Map(), stroke = false, paintBusy = false;
let hover = null, selected = 0, legendKey = '', elapsed = 0;
const controls = ['play', 'step', 'clear', 'reset', 'scenario', 'boundary', 'depth', 'gravity', 'tension', 'damping', 'resolution', 'view', 'save', 'open', 'csv', 'apply', 'source-remove', 'pace'];
const tools = {
  pulse: ['Pulse', 'Click the field to drop a 0.3 mm Gaussian pulse.'],
  source: ['Source', 'Click the field to place a 3 Hz point source, then edit it under Sources.'],
  wall: ['Wall', 'Click or drag to draw a solid barrier.'],
  depth: ['Depth', 'Click or drag to paint still-water depth.'],
  erase: ['Erase', 'Click or drag to remove walls and restore the base depth.'],
  probe: ['Probe', 'Click the field to move the probe. Its trace restarts.'],
};
const brushTools = ['pulse', 'wall', 'depth', 'erase'];

const status = (text, kind = '') => {$('status').textContent = text; $('status').dataset.kind = kind;};
const tidy = v => String(+(+v).toPrecision(12));
const fixed = (v, n) => {const s = v.toFixed(n); return (/^-0\.?0*$/.test(s) ? s.slice(1) : s).replace(/^-/, '−');};
const setIdle = (id, value, force = false) => {if (force || document.activeElement !== $(id)) $(id).value = value;};
// The engine places normalized coordinate v at cell coordinate v·(n−1); cell i spans [i, i+1).
const toFrac = (v, n) => (v * (n - 1) + 0.5) / n;
const toNorm = (f, n) => Math.min(1, Math.max(0, (f * n - 0.5) / (n - 1)));
const size = c => ({w: c.width_m, h: c.width_m * c.ny / c.nx});
function niceStep(raw, steps = [1, 2, 5, 10]) {const p = 10 ** Math.floor(Math.log10(raw)); return steps.find(m => m * p >= raw) * p;}
function joules(v) {
  const a = Math.abs(v);
  if (!a) return '0 J';
  const [f, p] = a >= 1 ? [1, ''] : a >= 1e-3 ? [1e-3, 'm'] : a >= 1e-6 ? [1e-6, 'µ'] : a >= 1e-9 ? [1e-9, 'n'] : [1e-12, 'p'];
  return `${(v / f).toPrecision(4).replace(/^-/, '−')} ${p}J`;
}
function numberFrom(id) {
  const input = $(id), name = input.closest('label').querySelector('span').textContent, unit = input.nextElementSibling?.textContent ?? '';
  if (input.value === '' || !input.validity.valid) throw Error(`${name} must be between ${input.min} and ${input.max} ${unit}`.trim());
  return +input.value;
}

function send(data) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    const timeout = setTimeout(() => {pending.delete(id); reject(Error('Engine response timed out'));}, 30000);
    pending.set(id, {resolve, reject, timeout, force: data.action === 'init' || ['new', 'preset', 'load'].includes(data.command?.op)});
    worker.postMessage({id, ...data});
  });
}
const command = data => send({command: data});
const attempt = async f => {try {return await f();} catch (e) {status(e.message, 'error'); return null;}};

// Mirrors the engine's RGBA colormap (src/lib.rs render) so the key matches the field exactly.
function colormap(view, t) {
  if (view === 'depth') return [16 + 20 * t, 40 + 100 * t, 55 + 175 * t];
  if (view === 'intensity') {const v = Math.sqrt(t); return [16 + 95 * v, 21 + 195 * v, 27 + 225 * v];}
  const v = 2 * t - 1;
  return v >= 0 ? [16 + 232 * v, 21 + 152 * v, 27 + 71 * v] : [16 - 80 * v, 21 - 181 * v, 27 - 223 * v];
}
function drawLegend(view, c, force = false) {
  const key = `${view}:${c.depth_m}:${colorbar.clientWidth}`;
  if (!force && key === legendKey) return;
  legendKey = key;
  $('scale-quantity').textContent = view === 'height' ? 'Surface height' : view === 'depth' ? 'Water depth' : 'RMS height';
  $('scale-low').textContent = view === 'height' ? '−0.3 mm' : '0 mm';
  $('scale-high').textContent = view === 'height' ? '+0.3 mm' : view === 'depth' ? `${(c.depth_m * 2000).toFixed(1)} mm` : '0.3 mm';
  const dpr = devicePixelRatio || 1, w = Math.max(1, Math.round(colorbar.clientWidth * dpr)), h = Math.max(1, Math.round(colorbar.clientHeight * dpr));
  colorbar.width = w; colorbar.height = h;
  for (let i = 0; i < w; i++) {
    const [r, g, b] = colormap(view, w > 1 ? i / (w - 1) : 0).map(Math.floor);
    cb.fillStyle = `rgb(${r},${g},${b})`; cb.fillRect(i, 0, 1, h);
  }
}

function syncConfig(c, force = false) {
  for (const [id, key, f] of [['depth', 'depth_m', 1000], ['gravity', 'gravity', 1], ['tension', 'surface_tension', 1000], ['damping', 'damping', 1]]) setIdle(id, tidy(c[key] * f), force);
  setIdle('boundary', c.boundary, force);
  const gridValue = c.ny === Math.round(c.nx * 0.6) && [128, 200, 320, 512].includes(c.nx) ? `${c.nx}` : `${c.nx}x${c.ny}`;
  if (![...$('resolution').options].some(o => o.value === gridValue)) $('resolution').add(new Option(`${c.nx} × ${c.ny} (opened file)`, gridValue));
  $('resolution').value = gridValue;
  const {w, h} = size(c), wmm = w * 1000;
  for (const id of ['x', 'source-x']) $(id).max = tidy(w * 100);
  for (const id of ['y', 'source-y']) $(id).max = tidy(h * 100);
  $('brush').min = tidy(Math.ceil(wmm * 0.2) / 100);
  $('brush').max = tidy(Math.floor(wmm * 20) / 100);
  const brush = Math.min(+$('brush').max, Math.max(+$('brush').min, +$('brush').value || wmm * 0.03));
  if (brush !== +$('brush').value) $('brush').value = tidy(brush);
  $('grid-label').textContent = `${c.nx} × ${c.ny} cells`;
  $('grid-dx').textContent = `Δx ${fixed(w / c.nx * 1000, 2)} mm`;
  canvas.setAttribute('aria-label', `Water field, ${fixed(w * 100, 1)} by ${fixed(h * 100, 1)} cm`);
}
function updateEditor(force = false) {
  const s = state?.sources[selected];
  for (const id of ['frequency', 'amplitude', 'phase', 'source-x', 'source-y', 'source-radius', 'source-enabled', 'source-remove']) $(id).disabled = !s;
  if (!s) return;
  const c = state.config, {w, h} = size(c);
  $('source-enabled').checked = s.enabled;
  setIdle('frequency', tidy(s.frequency_hz), force);
  setIdle('amplitude', tidy(s.amplitude_m * 1000), force);
  setIdle('source-radius', tidy(s.radius_m * 1000), force);
  setIdle('phase', tidy(+((((s.phase_rad * 180 / Math.PI + 180) % 360 + 360) % 360 - 180).toFixed(2))), force);
  setIdle('source-x', tidy(+(toFrac(s.x, c.nx) * w * 100).toFixed(2)), force);
  setIdle('source-y', tidy(+(toFrac(s.y, c.ny) * h * 100).toFixed(2)), force);
  $('source-y').disabled = s.kind === 'plane';
}
function syncSources(force = false) {
  const sources = state.sources, focused = sourceList.contains(document.activeElement);
  selected = Math.max(0, Math.min(selected, sources.length - 1));
  $('source-count').textContent = sources.length;
  $('source-empty').hidden = sources.length > 0;
  $('source-editor').hidden = !sources.length;
  sourceList.replaceChildren(sourceLegend, ...sources.map((s, i) => {
    const row = document.createElement('label'), input = document.createElement('input');
    row.className = `rt-source${s.enabled ? '' : ' rt-off'}`;
    Object.assign(input, {type: 'radio', name: 'source', value: `${i}`, checked: i === selected});
    input.setAttribute('aria-label', `Source ${i + 1}: ${s.kind === 'plane' ? 'plane wave' : 'point'}, ${tidy(+s.frequency_hz.toFixed(3))} Hz, ${s.enabled ? `${fixed(s.amplitude_m * 1000, 3)} mm` : 'off'}`);
    const n = document.createElement('b'), kind = document.createElement('span'), detail = document.createElement('small');
    n.textContent = `${i + 1}`;
    kind.textContent = `${s.kind === 'plane' ? 'Plane wave' : 'Point'}, ${tidy(+s.frequency_hz.toFixed(3))} Hz`;
    detail.textContent = s.enabled ? `${fixed(s.amplitude_m * 1000, 3)} mm` : 'Off';
    row.append(input, n, kind, detail);
    return row;
  }));
  if (focused) sourceList.querySelector('input:checked')?.focus();
  updateEditor(force);
}

function render(data, force = false) {
  const r = data.result;
  if (!r) return;
  const configChanged = !state || JSON.stringify(state.config) !== JSON.stringify(r.config);
  const sourcesChanged = configChanged || JSON.stringify(state.sources) !== JSON.stringify(r.sources);
  state = r;
  if (data.probePosition) probe = data.probePosition;
  if (data.probe) sample = data.probe;
  if (data.elapsed) elapsed = data.elapsed;
  $('view').value = r.view;
  const c = r.config, d = r.diagnostics, {w, h} = size(c);
  if (canvas.width !== c.nx || canvas.height !== c.ny) {canvas.width = c.nx; canvas.height = c.ny;}
  if (configChanged || force) {workspace.style.setProperty('--aspect', `${c.nx / c.ny}`); syncConfig(c, force);}
  ctx.putImageData(new ImageData(data.pixels, c.nx, c.ny), 0, 0);
  drawLegend(r.view, c);
  $('scale-clip').hidden = !(r.view === 'height' && d.max_height_m > 0.0003);
  $('time').textContent = `${d.time_s.toFixed(3)} s`;
  $('steps').textContent = `${d.steps.toLocaleString('en')} steps`;
  $('dt').textContent = `${(d.dt_s * 1000).toFixed(3)} ms`;
  $('courant').textContent = Number.isFinite(d.courant) ? d.courant.toFixed(3) : '—';
  const batch = document.createElement('small');
  batch.textContent = `per ${$('pace').value}-step batch`;
  $('compute').replaceChildren(elapsed ? `${elapsed.toFixed(1)} ms` : '—', ...(elapsed ? [batch] : []));
  $('energy').textContent = joules(d.energy_j);
  $('volume').textContent = `${fixed(d.mass_m3 * 1e6, 4)} mL`;
  $('height').textContent = `${(d.max_height_m * 1000).toFixed(3)} mm`;
  const ratio = d.max_height_depth_ratio;
  $('ratio').textContent = Number.isFinite(ratio) ? `${(ratio * 100).toFixed(2)} %` : '—';
  $('ratio').classList.toggle('rt-warn', ratio > 0.1);
  if (sample) {
    const ix = Math.round(probe.x * (c.nx - 1)), iy = Math.round(probe.y * (c.ny - 1));
    $('probe-pos').textContent = `x ${fixed((ix + 0.5) / c.nx * w * 100, 1)} cm, y ${fixed((iy + 0.5) / c.ny * h * 100, 1)} cm`;
    $('probe-depth').textContent = sample.solid ? 'Inside a wall' : `H ${fixed(sample.depth_m * 1000, 2)} mm`;
    $('probe-value').textContent = `${fixed(sample.height_m * 1000, 4)} mm`;
    if (!history.length || d.time_s > history.at(-1)[0]) history.push([d.time_s, sample.height_m]);
    history = history.slice(-600);
  }
  if (sourcesChanged || force) syncSources(force);
  drawOverlay();
  drawTrace();
}

function drawOverlay() {
  if (!state) return;
  const dpr = devicePixelRatio || 1, fw = frame.clientWidth, fh = frame.clientHeight;
  if (overlay.width !== Math.round(fw * dpr) || overlay.height !== Math.round(fh * dpr)) {overlay.width = Math.round(fw * dpr); overlay.height = Math.round(fh * dpr);}
  oc.setTransform(dpr, 0, 0, dpr, 0, 0);
  oc.clearRect(0, 0, fw, fh);
  const c = state.config, {w, h} = size(c), wc = w * 100, hc = h * 100;
  const L = canvas.offsetLeft, T = canvas.offsetTop, W = canvas.clientWidth, H = canvas.clientHeight;
  const at = p => [L + toFrac(p.x, c.nx) * W, T + toFrac(p.y, c.ny) * H];
  // Rulers in centimetres along the top and left edges of the tank.
  const step = niceStep(wc * 46 / W);
  oc.font = '10.5px "Public Sans", system-ui, sans-serif';
  oc.fillStyle = '#8a9096'; oc.strokeStyle = '#3d444c'; oc.lineWidth = 1;
  oc.beginPath();
  for (let i = 0; i * step / 2 <= wc + 1e-9; i++) {const x = Math.round(L + i * step / 2 / wc * W) + 0.5; oc.moveTo(x, T - 1); oc.lineTo(x, T - (i % 2 ? 3 : 6));}
  for (let i = 0; i * step / 2 <= hc + 1e-9; i++) {const y = Math.round(T + i * step / 2 / hc * H) + 0.5; oc.moveTo(L - 1, y); oc.lineTo(L - (i % 2 ? 3 : 6), y);}
  oc.stroke();
  oc.textAlign = 'center'; oc.textBaseline = 'alphabetic';
  for (let v = step; v <= wc + 1e-9; v += step) {const x = L + v / wc * W; if (x < L + W - 12) oc.fillText(tidy(+v.toFixed(6)), x, T - 8);}
  oc.textAlign = 'right'; oc.textBaseline = 'middle';
  for (let v = step; v <= hc + 1e-9; v += step) {const y = T + v / hc * H; if (y < T + H - 6) oc.fillText(tidy(+v.toFixed(6)), L - 8, y);}
  oc.textBaseline = 'alphabetic'; oc.fillText('cm', L - 6, T - 7);
  oc.save();
  oc.beginPath(); oc.rect(L, T, W, H); oc.clip();
  const ink = (path, color, width, dash = []) => {
    oc.setLineDash(dash);
    oc.strokeStyle = 'rgba(6,9,12,.72)'; oc.lineWidth = width + 2.5; path(); oc.stroke();
    oc.strokeStyle = color; oc.lineWidth = width; path(); oc.stroke();
    oc.setLineDash([]);
  };
  const label = (text, x, y, color) => {oc.font = '600 11px "Public Sans", system-ui, sans-serif'; oc.textAlign = 'left'; oc.lineWidth = 3; oc.strokeStyle = 'rgba(6,9,12,.8)'; oc.strokeText(text, x, y); oc.fillStyle = color; oc.fillText(text, x, y);};
  state.sources.forEach((s, i) => {
    const [x, y] = at(s), chosen = i === selected, color = chosen ? accent : '#eef0f3', dash = s.enabled ? [] : [3, 3];
    if (s.kind === 'plane') {
      ink(() => {oc.beginPath(); oc.moveTo(x, T); oc.lineTo(x, T + H);}, color, chosen ? 2 : 1.2, dash);
      label(`${i + 1}`, x + 5, T + 14, color);
    } else {
      const r = Math.max(5, s.radius_m / w * W);
      ink(() => {oc.beginPath(); oc.arc(x, y, r, 0, Math.PI * 2);}, color, chosen ? 2 : 1.3, dash);
      label(`${i + 1}`, x + r * 0.75 + 3, y - r * 0.75 - 2, color);
    }
  });
  const cross = ([x, y], color, arm = 9, gap = 3.5) => ink(() => {
    oc.beginPath(); oc.moveTo(x - arm, y); oc.lineTo(x - gap, y); oc.moveTo(x + gap, y); oc.lineTo(x + arm, y);
    oc.moveTo(x, y - arm); oc.lineTo(x, y - gap); oc.moveTo(x, y + gap); oc.lineTo(x, y + arm);
  }, color, 1.4);
  cross(at(probe), '#eef0f3');
  const footprint = (p, dash) => {
    const [x, y] = at(p);
    if (tool === 'probe') return cross([x, y], accent, 7, 2.5);
    const r = tool === 'source' ? Math.max(5, 0.008 / w * W) : Math.max(2, brushRadius(false) * W);
    ink(() => {oc.beginPath(); oc.arc(x, y, r, 0, Math.PI * 2);}, accent, 1.2, dash);
  };
  if (document.activeElement === canvas) {
    const [x, y] = at(position);
    ink(() => {oc.beginPath(); oc.rect(x - 6, y - 6, 12, 12);}, accent, 1.4);
    footprint(position, [4, 3]);
  }
  if (hover) footprint(hover, [4, 3]);
  oc.restore();
}

function drawTrace() {
  const dpr = devicePixelRatio || 1, cw = trace.clientWidth, ch = trace.clientHeight;
  if (!cw || !ch) return;
  if (trace.width !== Math.round(cw * dpr) || trace.height !== Math.round(ch * dpr)) {trace.width = Math.round(cw * dpr); trace.height = Math.round(ch * dpr);}
  tc.setTransform(dpr, 0, 0, dpr, 0, 0);
  tc.clearRect(0, 0, cw, ch);
  const x0 = 50, x1 = cw - 2, y0 = 4, y1 = ch - 18, mid = (y0 + y1) / 2;
  tc.fillStyle = '#10151b'; tc.fillRect(x0, y0, x1 - x0, y1 - y0);
  tc.font = '10.5px "Public Sans", system-ui, sans-serif'; tc.fillStyle = '#8a9096';
  const ready = history.length >= 2 && history.at(-1)[0] > history[0][0];
  const scale = ready ? niceStep(Math.max(1e-5, ...history.map(p => Math.abs(p[1]))), [1, 2, 2.5, 5, 10]) : 1e-4;
  const Y = v => mid - v / scale * (y1 - y0) / 2;
  tc.strokeStyle = '#262d34'; tc.lineWidth = 1; tc.beginPath();
  for (const f of [-1, -0.5, 0.5, 1]) {const y = Math.round(Y(f * scale)) + 0.5; tc.moveTo(x0, y); tc.lineTo(x1, y);}
  tc.stroke();
  tc.strokeStyle = '#3d444c'; tc.beginPath(); tc.moveTo(x0, Math.round(mid) + 0.5); tc.lineTo(x1, Math.round(mid) + 0.5); tc.stroke();
  tc.textAlign = 'right'; tc.textBaseline = 'middle';
  const mm = tidy(+(scale * 1000).toPrecision(3));
  tc.fillText(`+${mm}`, x0 - 6, Y(scale) + 4); tc.fillText('0', x0 - 6, mid); tc.fillText(`−${mm}`, x0 - 6, Y(-scale) - 4); tc.fillText('mm', x0 - 6, (Y(scale / 2) + mid) / 2 + 1);
  if (!ready) {$('trace-scale').textContent = 'Waiting for simulation time'; return;}
  const t0 = history[0][0], span = history.at(-1)[0] - t0, X = t => x0 + (t - t0) / span * (x1 - x0);
  tc.textBaseline = 'alphabetic'; tc.textAlign = 'left'; tc.fillText(`${t0.toFixed(2)} s`, x0, ch - 3);
  tc.textAlign = 'right'; tc.fillText(`${history.at(-1)[0].toFixed(2)} s`, x1, ch - 3);
  const curve = () => {tc.beginPath(); history.forEach(([t, v], i) => i ? tc.lineTo(X(t), Y(v)) : tc.moveTo(X(t), Y(v)));};
  // Area above zero in the crest color, below zero in the trough color, as in the field colormap.
  for (const [top, color] of [[true, 'rgba(248,173,98,.26)'], [false, 'rgba(96,202,250,.24)']]) {
    tc.save(); tc.beginPath(); tc.rect(x0, top ? y0 : mid, x1 - x0, top ? mid - y0 : y1 - mid); tc.clip();
    curve(); tc.lineTo(X(history.at(-1)[0]), mid); tc.lineTo(X(t0), mid); tc.closePath(); tc.fillStyle = color; tc.fill(); tc.restore();
  }
  curve(); tc.strokeStyle = '#d9e3ea'; tc.lineWidth = 1.4; tc.lineJoin = 'round'; tc.stroke();
  const [lt, lv] = history.at(-1);
  tc.fillStyle = '#eef0f3'; tc.beginPath(); tc.arc(X(lt), Y(lv), 2.6, 0, Math.PI * 2); tc.fill();
  $('trace-scale').textContent = `Probe height, full scale ±${mm} mm, over the last ${span.toFixed(2)} s of simulation time`;
}

worker.onmessage = ({data}) => {
  const entry = pending.get(data.id);
  if (data.error) {
    status(data.error, 'error');
    if (!data.id) {wanted = false; syncPlay();}
  } else if (data.result) {render(data, entry?.force); if (data.id) status('Ready');}
  if (entry) {clearTimeout(entry.timeout); pending.delete(data.id); data.error ? entry.reject(Error(data.error)) : entry.resolve(data);}
};
worker.onerror = event => {
  wanted = false; syncPlay(); status(`Engine unavailable: ${event.message}`, 'error');
  for (const entry of pending.values()) {clearTimeout(entry.timeout); entry.reject(Error('Worker stopped'));}
  pending.clear();
};
function syncPlay() {$('play-label').textContent = wanted ? 'Pause' : 'Play'; $('play').setAttribute('aria-pressed', String(wanted));}
async function pause() {wanted = false; syncPlay(); await send({action: 'run', value: false});}
const togglePlay = () => attempt(async () => {wanted = !wanted; syncPlay(); await send({action: 'run', value: wanted && !document.hidden});});
for (const id of controls) $(id).disabled = true;
$('play').addEventListener('click', togglePlay);
$('step').addEventListener('click', () => attempt(async () => {await pause(); await command({op: 'advance', steps: 1});}));
$('reset').addEventListener('click', () => attempt(async () => {
  await pause(); history = [];
  if ($('scenario').value === 'loaded' && loadedSnapshot) {$('view').value = 'height'; await command({op: 'load', snapshot: loadedSnapshot});}
  else await command({op: 'preset', name: $('scenario').value});
}));
$('clear').addEventListener('click', () => attempt(async () => {history = []; await command({op: 'clear'});}));
$('scenario').addEventListener('change', () => attempt(async () => {if ($('scenario').value === 'loaded') return; history = []; await command({op: 'preset', name: $('scenario').value});}));
for (const [id, key, factor] of [['depth', 'depth_m', 1000], ['gravity', 'gravity', 1], ['tension', 'surface_tension', 1000], ['damping', 'damping', 1]]) {
  $(id).addEventListener('change', () => attempt(async () => {await command({op: 'set', config: {[key]: numberFrom(id) / factor}}); status('Parameters updated');}));
}
$('boundary').addEventListener('change', () => attempt(async () => {await command({op: 'set', config: {boundary: $('boundary').value}}); status('Parameters updated');}));
$('resolution').addEventListener('change', () => attempt(async () => {
  await pause(); history = []; $('view').value = 'height';
  const dims = $('resolution').value.split('x').map(Number), n = dims[0], ny = dims[1] || Math.round(n * 0.6);
  if ($('scenario').value === 'loaded') $('scenario').value = 'empty';
  await command({op: 'new', config: {...state.config, nx: n, ny}, preset: $('scenario').value});
}));
$('pace').addEventListener('change', () => attempt(async () => {
  const value = +$('pace').value;
  if (!Number.isInteger(value) || value < 1 || value > 32) throw Error('Pace must be a whole number of steps from 1 to 32');
  await send({action: 'pace', value});
}));
$('view').addEventListener('change', () => attempt(() => command({op: 'view', name: $('view').value})));

function setTool(value) {
  tool = value;
  const [name, hint] = tools[value];
  $('tool-name').textContent = name; $('tool-hint').textContent = hint;
  for (const row of document.querySelectorAll('[data-tools]')) row.hidden = !row.dataset.tools.split(' ').includes(value);
  $('apply').textContent = value === 'probe' ? 'Move probe here' : value === 'source' ? 'Place source here' : `Apply ${name.toLowerCase()} here`;
  drawOverlay();
}
for (const input of document.querySelectorAll('input[name=tool]')) input.addEventListener('change', () => setTool(input.value));
// Strict for edits (rejects out-of-range input); lenient for the hover footprint.
const brushRadius = (strict = true) => Math.min(0.2, Math.max(0.002, (strict ? numberFrom('brush') : +$('brush').value || 0) / 1000 / state.config.width_m));
$('brush').addEventListener('input', drawOverlay);

// Sources: send the whole list but change only the one field the user edited, so exact imported values survive.
const sourceFields = {
  frequency: v => ({frequency_hz: v}), amplitude: v => ({amplitude_m: v / 1000}), 'source-radius': v => ({radius_m: v / 1000}),
  phase: v => ({phase_rad: v * Math.PI / 180}),
  'source-x': v => ({x: toNorm(v / 100 / size(state.config).w, state.config.nx)}),
  'source-y': v => ({y: toNorm(v / 100 / size(state.config).h, state.config.ny)}),
};
for (const id of [...Object.keys(sourceFields), 'source-enabled']) $(id).addEventListener('change', () => attempt(async () => {
  const sources = state.sources.map(s => ({...s})), s = sources[selected];
  if (!s) return;
  if (id === 'source-enabled') s.enabled = $(id).checked;
  else Object.assign(s, sourceFields[id](numberFrom(id)));
  await command({op: 'sources', sources});
}));
sourceList.addEventListener('change', e => {if (e.target.name === 'source') {selected = +e.target.value; updateEditor(); drawOverlay();}});
$('source-remove').addEventListener('click', () => attempt(async () => {
  const n = selected + 1;
  await command({op: 'sources', sources: state.sources.filter((s, i) => i !== selected)});
  status(`Source ${n} removed`);
}));

async function apply(x, y) {
  if (!state) return;
  const c = state.config, {w, h} = size(c);
  position = {x, y};
  $('x').value = tidy(+(toFrac(x, c.nx) * w * 100).toFixed(2)); $('y').value = tidy(+(toFrac(y, c.ny) * h * 100).toFixed(2));
  if (tool === 'probe') {history = []; return send({action: 'probe', x, y});}
  if (tool === 'pulse') return command({op: 'pulse', x, y, radius: brushRadius(), amplitude_m: 0.0003});
  if (tool === 'source') {
    const result = await command({op: 'sources', sources: [...state.sources, {x, y, frequency_hz: 3, amplitude_m: 0.00015, phase_rad: 0, kind: 'point', enabled: true}]});
    selected = state.sources.length - 1; syncSources(); drawOverlay();
    status(`Source ${selected + 1} added`);
    return result;
  }
  return command({op: 'paint', x, y, radius: brushRadius(), tool, depth_m: numberFrom('paint-depth') / 1000});
}
$('apply').addEventListener('click', () => attempt(() => {
  const c = state.config, {w, h} = size(c);
  return apply(toNorm(numberFrom('x') / 100 / w, c.nx), toNorm(numberFrom('y') / 100 / h, c.ny));
}));
function pointer(e) {
  const r = canvas.getBoundingClientRect(), c = state.config;
  return {x: toNorm((e.clientX - r.left) / r.width, c.nx), y: toNorm((e.clientY - r.top) / r.height, c.ny)};
}
canvas.addEventListener('pointerdown', e => {
  if (!state || e.button > 0) return;
  canvas.focus({preventScroll: true}); canvas.setPointerCapture(e.pointerId); stroke = true;
  const p = pointer(e); attempt(() => apply(p.x, p.y));
});
canvas.addEventListener('pointermove', e => {
  if (!state) return;
  const p = pointer(e);
  if (e.pointerType === 'mouse') {hover = p; drawOverlay();}
  if (!stroke || paintBusy || !['wall', 'depth', 'erase'].includes(tool)) return;
  paintBusy = true; attempt(() => apply(p.x, p.y)).finally(() => {paintBusy = false;});
});
canvas.addEventListener('pointerleave', () => {hover = null; drawOverlay();});
for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(name, () => {stroke = false;});
canvas.addEventListener('keydown', e => {
  if (e.key === 'Enter') {e.preventDefault(); attempt(() => apply(position.x, position.y)); return;}
  if (e.key === ' ') {e.preventDefault(); if (!$('play').disabled) togglePlay(); return;}
  const k = e.shiftKey ? 0.05 : 0.01, delta = {ArrowLeft: [-k, 0], ArrowRight: [k, 0], ArrowUp: [0, -k], ArrowDown: [0, k]}[e.key];
  if (!delta || !state) return;
  e.preventDefault();
  const c = state.config, {w, h} = size(c);
  position = {x: Math.max(0, Math.min(1, position.x + delta[0])), y: Math.max(0, Math.min(1, position.y + delta[1]))};
  $('x').value = tidy(+(toFrac(position.x, c.nx) * w * 100).toFixed(2)); $('y').value = tidy(+(toFrac(position.y, c.ny) * h * 100).toFixed(2));
  drawOverlay();
});
canvas.addEventListener('focus', drawOverlay);
canvas.addEventListener('blur', drawOverlay);

const tabs = [...document.querySelectorAll('.rt-tabs [role=tab]')];
function selectTab(tab, focus = false) {
  for (const t of tabs) {const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; $(t.getAttribute('aria-controls')).hidden = !on;}
  if (focus) tab.focus();
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', e => {
    const j = {ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1}[e.key];
    if (j !== undefined) {e.preventDefault(); selectTab(tabs[j], true);}
  });
});

function download(text, type, name) {const url = URL.createObjectURL(new Blob([text], {type})); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);}
$('save').addEventListener('click', () => attempt(async () => {await pause(); const d = await command({op: 'snapshot'}); download(JSON.stringify(d.result.snapshot), 'application/json', 'tank.ripple.json'); status('Experiment saved as tank.ripple.json');}));
$('csv').addEventListener('click', () => attempt(async () => {await pause(); const d = await command({op: 'csv'}); download(d.result.csv, 'text/csv', 'ripple-field.csv'); status('Field exported as ripple-field.csv');}));
$('open').addEventListener('click', () => {$('file').click();});
$('file').addEventListener('change', () => attempt(async () => {
  const f = $('file').files[0]; $('file').value = '';
  if (!f) return;
  if (f.size > 32 * 1024 * 1024) throw Error('Experiment exceeds 32 MiB');
  await pause();
  const snapshot = JSON.parse(await f.text());
  const response = await command({op: 'load', snapshot});
  loadedSnapshot = snapshot; history = []; drawTrace();
  if (![...$('scenario').options].some(o => o.value === 'loaded')) $('scenario').add(new Option('Opened file', 'loaded'));
  $('scenario').value = 'loaded'; $('view').value = 'height'; status(`Loaded ${f.name}`); $('file').value = '';
  return response;
}));
document.addEventListener('visibilitychange', () => attempt(() => send({action: 'run', value: wanted && !document.hidden})));
const resized = new ResizeObserver(() => {if (state) {drawLegend(state.view, state.config, true); drawOverlay(); drawTrace();}});
resized.observe(frame); resized.observe(trace);
setTool(document.querySelector('input[name=tool]:checked')?.value || 'pulse');
attempt(async () => {
  await send({action: 'init'});
  for (const id of controls) $(id).disabled = false;
  updateEditor(); status('Ready');
  if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {wanted = true; syncPlay(); await send({action: 'run', value: !document.hidden});}
  else status('Ready. Press Play to run.');
});
