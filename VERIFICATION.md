# Verification — Ripple Tank 0.1.0

The numerical engine, native Qt interface, CLI and worker-based browser implementation share a tested Rust core. The measurements below were made on the Fedora target machine using synthetic experiments.

## Target

Fedora44 x86_64, Linux7.1.8, glibc2.43, Intel Corei5- 12400 (12logical CPUs). Rust1.96.1 release/LTO/codegen-units1, Python3.14.7, PySide6.11.1, PyInstaller6.16.0, Node22.23.2 and actual Chrome. Simulation is single-threaded CPU code, shared as native and WASM builds. No GPU-compute acceleration or non-Fedora compatibility claim.

## Evidence

- 12 Rust numerical, conservation, dispersion, depth-interface, source integration and malformed-state tests pass. Second-order refinement, exact discrete mode recurrence, reflective walls, sponge loss and exact native restart are covered. StrictClippy and formatting checks pass.
- Native/WebAssembly parity:11 real commands,5 complete fields compared, maximum absolute difference9.54e-18; invalid imports preserve the previous experiment. The same core renders both interfaces.
- Qt workflows: 19 original assertions and six focused regression cases pass, including actual keyboard entry while the simulation is running, source controls that preserve untouched imported precision, physical brushes, play/pause/step, saved full-state restart and invalid-file preservation. The independent save-failure probe confirms existing files survive a write failure. Independent installer probes verified user-file preservation, safe concurrent prefix/menu claims, scoped cleanup and early unsupported-path rejection.
- The actual PyInstaller executable launches in both the normal Fedora desktop session and the offscreen test backend with its bundled runtime, advances128steps, saves/reopens an experiment exactly and writes a rendered screenshot. It does not open a browser.
- CLI new/run/inspect/export succeed; attempts to overwrite an existing output fail and preserve its bytes.
- Actual Chrome tested integrated Labs at1440,390 and320px widths: no document overflow, worker operation under production-style response CSP, actual mouse pulse, keyboard wall/probe, view/grid reset, correct color keys, source activation, play/pause and step. Browser Save downloads a validated experiment; CSV downloads24001rows and matches the saved surface field.
- The Chrome extension blocks automated local file-picker selection without its additional local-file permission. That permission was not changed. The isolated browser runner also restricts direct filesystem upload paths. Its synthetic File integration test verifies the actual File.text/parse/load handler, square64×64 canvas aspect, loaded labels, view reset, exact loaded-time reset and malformed-file state preservation. Actual OS file-picker selection is not claimed tested; native import and the underlying WASM/native load protocol are verified. Real touch hardware and reduced-motion preference emulation were unavailable; pointer-event handling and narrow layouts were inspected/tested as described, without claiming a hardware touch test.

## Measured performance

| Native core workload | Time / step | RGBA render | Simulated seconds / wall second |
|---|---:|---:|---:|
|200×120,2000steps|0.306ms|0.111ms|6.11|
|512×307,200steps|2.960ms|1.006ms|0.11|

Large-workload peakRSS was23.4MiB in the earlier same-layout benchmark; the exact final `/usr/bin/time -v` measurement is retained with build evidence. Default WASM batches of8substeps were observed around4–6ms in Chrome on this device. These are bounded local measurements, not universal frame-rate guarantees. Qt/Chrome runtime memory is additional to the standalone core measurement. CPU/GPU compositor behavior and other operating systems were not benchmarked.

A100000-step driven run stayed finite through186.92simulated seconds, peak height0.254mm. The maximum512×512core grid measured4.932ms/step and1.796ms/render; its precise memory receipt is retained.

## Independent review

A fresh-context reviewer independently passed the physics gates, matched a2D discrete mode to2.78e−19m, and verified11 malformed transactions. Review findings about native atomic saves, reset/import view/grid consistency, source dragging, imported aspect ratio, view legends and trace captions were corrected. The reviewer independently checked the cell-integrated source against Pythonmath.erf to1.35e−18m and verified forcing-volume invariance across coarse grids. It also confirmed depth-interface amplitudesR=.3318022,T=1.3350873 against1/3,4/3. No further defect was found in the changed kernel/temporal logic.

A second fresh-context review identified source-parameter precision drift and stale imported-view legends. Both were independently reproduced, corrected with single-field source edits and authoritative backend view metadata, and covered by native and real-browser regressions. The focused independent recheck passed; no unresolved review finding remains in these paths.

## Interface release checks

The final calibrated browser/native layouts were independently rechecked after the visual redesign. Focused imports refresh authoritative values, ordinary running frames preserve unfinished typing, source cm values track tank dimensions, paused probe readings follow field edits, and sampled coordinates use the engine’s rounding rule. The clipping status wraps below the legend at the supported960×680 native window size. Desktop source precision and25 workflow/regression cases pass. Browser checks at320px and1440px cover source precision, SI conversions, pointer/keyboard tools, reset/view behavior, physical color keys, trace semantics, malformed imports and numeric focus. Measured small-text contrast is4.53:1 for unit labels and5.01:1 for keyboard help. No unresolved material finding remains in this bounded independent review.
