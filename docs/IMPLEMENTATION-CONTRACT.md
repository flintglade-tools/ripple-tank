# Shared engine interface v1

## Engine
Linear depth-averaged gravity-capillary waves in SI units: eta_t=-div(H v), v_t=-grad(g eta - (sigma/rho) lap eta). Cell-centered eta, staggered face velocities, harmonic depth fluxes, Strang/velocity-Verlet integration, reflecting solid obstacles, reflecting/periodic/sponge perimeter, exponential drag. The model is linear shallow water with capillary dispersion; no nonlinear or full-depth claim. Useful presets, editable depth/walls, sinusoidal sources, Gaussian pulses, trace probes, deterministic full-state persistence. Browser and desktop call the SAME Rust engine.

## ABI
Shared lib target/release/libflintglade_ripple.so; WASM web/ripple.wasm (built by scripts/build.py). Exports: ripple_input_ptr() -> pointer to 32MiB input buffer; ripple_request(len:u32)->u32 (0 success,1 error; always JSON response); ripple_output_ptr()->pointer; ripple_output_len()->u32; ripple_pixels_ptr()->pointer; ripple_pixels_len()->u32. Copy UTF8 JSON into input buffer, invoke request, read output; get pointers AFTER each call (WASM memory may grow). Pixel data is RGBA width*height*4. Native ctypes MUST set restype c_void_p for pointers, c_uint32 for lengths and request. Rust cdylib has internal thread-local state; call from the SAME thread. No third-party network calls.

Responses: {ok:true,config:{...},diagnostics:{time_s,dt_s,steps,mass_m3,energy_j,max_height_m,courant,source_count},sources:[...],view:"height"|"depth"|"intensity"} or {ok:false,error:"..."}. Pixels refreshed each successful request. config: nx (32..512),ny (32..512), width_m (0.1..10),depth_m (0.0005..0.2),gravity (0.1..30),surface_tension (0..0.1 N/m),damping (0..10 /s),boundary (reflective|sponge|periodic). Density1000 fixed. Default nx200 ny120 width_m0.8 depth_m0.008 gravity9.81 sigma0.072 damping0.08 boundary sponge. Height follows width*ny/nx. JSON numbers finite; all requests bounded32MiB. State files format flintglade-ripple,version1,model linear-shallow-capillary-v1.

Requests:
- {op:"new",config:{...optional config fields},preset:"double-slit"} resets all, validates config.
- {op:"preset",name:"double-slit"|"single-slit"|"two-sources"|"lens"|"single"|"empty"|"pulse"} resets field, geometry,sources; preserves config.
- {op:"advance",steps:4} bounded1..256; all substeps have automatically stable dt; stop on error. Response diagnostics includes actual sim time. Do not tie simulation time to frame count without labeling speed.
- {op:"set",config:{gravity:9.81,depth_m:0.008,surface_tension:0.072,damping:0.08,boundary:"sponge"}} preserves field; changing grid/width uses new only.
- {op:"sources",sources:[{x:0.25,y:0.5,frequency_hz:3,amplitude_m:0.00015,phase_rad:0,kind:"point"|"plane",enabled:true}]} normalized coordinates, at most16.
- {op:"paint",x:0.5,y:0.5,radius:0.03,tool:"wall"|"depth"|"erase",depth_m:0.003} normalized radius relative to width; point edits/running okay, max radius0.2. Wall edits zero face velocities and affected height. Erase restores base depth.
- {op:"pulse",x:0.5,y:0.5,radius:0.04,amplitude_m:0.0003} injects Gaussian displaced height.
- {op:"clear"} clears waves/time, retains sources/geometry.
- {op:"view",name:"height"|"intensity"|"depth"} display only.
- {op:"probe",x:0.7,y:0.5} response adds probe:{height_m,depth_m,solid} for trace plotting; use once/frame at most.
- {op:"snapshot"} response additionally snapshot:{format,version,model,config,eta,ux,uy,depth,walls,sources,time_s,steps, intensity}; save exact JSON snapshot to .ripple.json.
- {op:"load",snapshot:{...}} validates fully before replacing current state, including finite values, lengths and physical bounds; ignores no missing versions.
- {op:"csv"} response additionally csv string x_m,y_m,eta_m,depth_m,solid rows; bounded supported size.

Worker should own WASM instantiation, scheduling and input; main handles accessible controls/canvas/probe trace. Canvas transferable ImageData copy (Uint8ClampedArray of RGBA) acceptable. Browser CSP must add worker-src self; WebAssembly compile requires script-src wasm-unsafe-eval. Native Qt QWidget image/trace via ctypes, not local web wrapper. Optional desktop QTimer advances same engine, file dialogs save/load/export, controls match units. The standalone CLI supports batch work through the same Session command protocol. UI must stay operational if loading fails and clearly expose actual error, no fake canvas fallback.

