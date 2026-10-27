# Numerical model and verification

Ripple Tank 0.1 uses a linear, depth-averaged gravity–capillary model. It solves a specified physical system in SI units. It is not a nonlinear free-surface solver or a full-depth water-wave solver.

## Equations

Surface displacement η (metres) and horizontal velocity v (m/s) obey

    ∂t η = −∇·(H v) + Q
    ∂t v = −∇(g η − (σ/ρ) ∇²η) − γ v

H is a prescribed positive still-water depth; ρ = 1000 kg/m³, g is gravitational acceleration, σ surface tension in N/m, γ linear velocity drag in s⁻¹. Q is an explicitly imposed volume source. There is no advection, overturning, breaking, wetting/drying or moving-bottom coupling. Parameters and source values are saved with the state. Waves should be small compared with local depth for the physical linearization to apply.

For uniform depth, the model's continuum dispersion relation is

    ω² = H(g |k|² + (σ/ρ) |k|⁴).

Full-depth linear water waves instead use `(g k + σ k³/ρ) tanh(kH)`. The engine implements the shallow-water limit `tanh(kH) ≈ k`, including the capillary term; it does not implement the full-depth relation. This distinction matters when wavelength is comparable to depth. Changing the mesh does not remove this model error.

Primary references for the underlying limits and physical dispersion:

- Richard Fitzpatrick, University of Texas, [Gravity Waves in Shallow Water](https://farside.ph.utexas.edu/teaching/336L/Fluidhtml/node149.html).
- Richard Fitzpatrick, University of Texas, [Capillary Waves](https://farside.ph.utexas.edu/teaching/336L/Fluidhtml/node157.html).
- University of Waterloo, [Surface gravity waves](https://uwaterloo.ca/applied-mathematics/current-undergraduates/continuum-and-fluid-mechanics-students/amath-463/surface-gravity-waves).

The following discrete method is the implementation's own specification. The references describe physical wave theory, not an endorsement or verification of this software.

## Spatial discretization

A square mesh has dx = domain width/nx. Its height is `ny dx`. Displacement is cell-centered; x/y velocities occupy the east/south face of each cell. Positive face depths use the harmonic mean of adjacent H. A solid cell closes every adjoining face. Surface-tension derivatives use a five-point Laplacian with zero normal displacement gradient at solid or reflecting boundaries. Flux divergence uses geometric neighbors, without double-counting closed ghost faces. Periodic edges wrap both directions.

This conservative flux construction preserves the integral of η when there is no source or damped rim. Mass is density times that displacement-volume integral; the UI reports displacement volume in mL relative to the undisturbed surface. Editing a wall removes the water displacement at that cell, and sources and the damped rim exchange displacement volume with the tank. Those actions are not closed-system conservation experiments.

The diagnostic energy is

    E = ½ Σcells ρ g η² dx²
      + ½ Σopen_faces σ (ηneighbor − η)²
      + ½ Σopen_faces ρ Hface vface² dx².

Forcing, damping and geometry edits change energy. This is a model diagnostic, not a measured laboratory energy.

## Time integration and stability

The conservative step is velocity Verlet: half potential-gradient kick, one conservative displacement drift, half kick. Velocities and displacement are synchronized at each saved step. Exact exponential velocity drag and a deliberate exponential rim loss are split around that step. The closed unforced method is second order and symplectic. It has bounded oscillatory energy error rather than exact conservation of the physical discrete energy.

A conservative spectral bound is `ωmax² ≤ Hmax [g Λ + (σ/ρ) Λ²]`, with `Λ=8/dx²`. We choose `dt=0.8/ωmax`, below the Verlet stability limit `ωmax dt<2`. Enabled harmonic sources additionally cap dt to at most 1/(32 f). Grid, depth, gravity, tension, boundary or source changes recompute derived geometry, kernels and dt. Sources are volumetric sinusoidal drivers with a smooth startup envelope. `amplitude_m` is a drive-displacement scale, not a guaranteed outgoing amplitude. Each source has a physical Gaussian radius `radius_m`, default0.008m; plane sources extend along the full y direction. Their truncated Gaussian kernels are integrated over cell areas using error functions, then precomputed; a source narrower than one cell retains its integrated strength instead of disappearing between cell centers. This preserves forcing volume across grid changes, but a coarse mesh still cannot resolve the resulting short waves. Source frequency, phase, spatial placement, radius, kind and enabled state persist. The interfaces show phase modulo a full turn. Editing one source parameter preserves the exact imported values of every other parameter, even when controls display rounded values.

The damped rim is a spatial sponge over14% of the smaller grid dimension, with maximum12/s loss. It substantially reduces reflections in the supplied test; it is not a mathematically reflection-free open boundary. The periodic and reflective modes supply closed alternatives.

## Display

Height colors map −0.3 to +0.3mm. Intensity is an exponential average of η² with0.25s time constant; its color key is RMS height0–0.3mm, with a nonlinear brightness mapping. Depth colors span0–2H. Colors clip outside those scales; exact peak height and probe values remain numerical. Probe traces use simulation time and an autoscaled vertical range. Simulation pace is substeps per displayed frame, with actual dt and compute time visible; this is not an asserted real-time wall-clock rate.

## Verified gates

`cargo test --release --locked` runs analytic gravity and capillary standing modes and second-order refinement, an exact discrete dispersion recurrence, variable-depth displacement-volume and energy checks, an impermeable-barrier experiment, reflective normal modes, depth/speed scaling, sponge/drag loss, deterministic full-state restart, malformed-load transactionality and closed-face validation. `scripts/verify-wasm.mjs` compares real native and WASM commands, fields, time and invalid imports. `scripts/verify-desktop.py` exercises real Qt controls, keyboard editing, saving and reloading without controlling another desktop window.

The first refinement result had normalized gravity-mode errors0.005981/0.001496/0.000366 at48/96/192 cells; capillary-mode errors0.005951/0.001549/0.000389. The variable-depth3000-step fixture's peak energy drift was0.000166 relative and absolute displacement-volume error1.35e−21m³. The1600-step damped-rim pulse retained1.73e−6 of initial energy, while the reflective counterpart retained0.999519. These are bounded reproducible fixtures, not universal accuracy guarantees. Final release evidence and target-device measurements are in VERIFICATION.md.

## Formats and resource bounds

A full `.ripple.json` state has format`flintglade-ripple`, version1 and model`linear-shallow-capillary-v1`, and includes mesh/physical parameters, η, synchronized face velocities, depths, walls, sources, intensity history, simulation time and step count. It deliberately does not store UI selection, probe history or playback state. Loading validates all required fields, finite values, array lengths, bounds, solids/closed faces and versions before replacing the active experiment. Native JSON uses exact float round trips. Native saves use same-directory temporary files and atomic replacement; CLI outputs refuse overwrite.

Import/request limit32MiB. Mesh32–512 cells per axis. Sources≤16. Interactive requests≤256 substeps, GUI≤32 per frame, CLI batch≤10million steps. Heights/velocities are finite and bounded at load. Long-running numerical excursions beyond100 in field/velocity trigger a visible error and clear the field. Browser work runs in a worker. No account, network API, paid service or provider credentials are part of an experiment.
