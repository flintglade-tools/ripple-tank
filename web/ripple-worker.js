// Dedicated worker owns all numerical state. Browser and Qt load the same Rust core.
let engine, running = false, timer, probe = {x: 0.72, y: 0.5}, steps = 8;
const encode = new TextEncoder(), decode = new TextDecoder();
const limit = 32 * 1024 * 1024;
function request(value) {
  const bytes = encode.encode(JSON.stringify(value));
  if (bytes.length > limit) throw Error('Experiment exceeds 32 MiB');
  const ptr = engine.ripple_input_ptr();
  new Uint8Array(engine.memory.buffer, ptr, bytes.length).set(bytes);
  engine.ripple_request(bytes.length);
  const result = JSON.parse(decode.decode(new Uint8Array(engine.memory.buffer, engine.ripple_output_ptr(), engine.ripple_output_len())));
  if (!result.ok) throw Error(result.error);
  return result;
}
function post(id, result, elapsed = 0) {
  const p = request({op: 'probe', ...probe});
  const ptr = engine.ripple_pixels_ptr();
  const pixels = new Uint8ClampedArray(engine.memory.buffer, ptr, engine.ripple_pixels_len()).slice();
  postMessage({id, result, probe: p.probe, probePosition: probe, pixels, elapsed}, [pixels.buffer]);
}
function tick() {
  if (!running) return;
  try {
    const start = performance.now();
    const result = request({op: 'advance', steps});
    post(0, result, performance.now() - start);
    timer = setTimeout(tick, 16);
  } catch (error) {
    running = false;
    postMessage({id: 0, error: error.message});
  }
}
onmessage = async ({data}) => {
  try {
    if (data.action === 'init') {
      const engineURL = new URL('./ripple.wasm', import.meta.url);
      engineURL.search = new URL(import.meta.url).search;
      const response = await fetch(engineURL);
      if (!response.ok) throw Error(`Engine download failed (${response.status})`);
      const instance = await WebAssembly.instantiate(await response.arrayBuffer(), {});
      engine = instance.instance.exports;
      post(data.id, request({op: 'new', preset: 'double-slit'}));
      return;
    }
    if (!engine) throw Error('Engine is not ready');
    if (data.action === 'run') {
      clearTimeout(timer);
      running = !!data.value;
      postMessage({id: data.id, running});
      if (running) tick();
    } else if (data.action === 'pace') {
      if (!Number.isInteger(data.value) || data.value < 1 || data.value > 32) throw Error('Pace must be 1..32');
      steps = data.value;
      postMessage({id: data.id, pace: steps});
    } else if (data.action === 'probe') {
      if (![data.x, data.y].every(v => Number.isFinite(v) && v >= 0 && v <= 1)) throw Error('Probe must lie inside tank');
      probe = {x: data.x, y: data.y};
      post(data.id, request({op: 'status'}));
    } else {
      post(data.id, request(data.command));
    }
  } catch (error) {
    postMessage({id: data.id, error: error.message});
  }
};
