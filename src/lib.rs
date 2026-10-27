//! Linear, depth-averaged gravity-capillary waves; all quantities use SI units.
//! See docs/NUMERICS.md for the model, discrete Hamiltonian and validation.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::cell::RefCell;

pub const MAX_INPUT: usize = 32 * 1024 * 1024;
const RHO: f64 = 1000.;
const MODEL: &str = "linear-shallow-capillary-v1";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default, deny_unknown_fields)]
pub struct Config {
    pub nx: usize,
    pub ny: usize,
    pub width_m: f64,
    pub depth_m: f64,
    pub gravity: f64,
    pub surface_tension: f64,
    pub damping: f64,
    pub boundary: String,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            nx: 200,
            ny: 120,
            width_m: 0.8,
            depth_m: 0.008,
            gravity: 9.81,
            surface_tension: 0.072,
            damping: 0.08,
            boundary: "sponge".into(),
        }
    }
}
fn bounded(v: f64, lo: f64, hi: f64, name: &str) -> Result<(), String> {
    if !v.is_finite() || v < lo || v > hi {
        Err(format!("{name} must be in {lo}..{hi}"))
    } else {
        Ok(())
    }
}
impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if !(32..=512).contains(&self.nx) || !(32..=512).contains(&self.ny) {
            return Err("Grid dimensions must be 32..512".into());
        }
        bounded(self.width_m, 0.1, 10., "width_m")?;
        bounded(self.depth_m, 0.0005, 0.2, "depth_m")?;
        bounded(self.gravity, 0.1, 30., "gravity")?;
        bounded(self.surface_tension, 0., 0.1, "surface_tension")?;
        bounded(self.damping, 0., 10., "damping")?;
        if !["sponge", "reflective", "periodic"].contains(&self.boundary.as_str()) {
            return Err("Unknown boundary".into());
        }
        Ok(())
    }
    pub fn dx(&self) -> f64 {
        self.width_m / self.nx as f64
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    pub x: f64,
    pub y: f64,
    pub frequency_hz: f64,
    pub amplitude_m: f64,
    pub phase_rad: f64,
    pub kind: String,
    pub enabled: bool,
    #[serde(default = "default_source_radius")]
    pub radius_m: f64,
}
fn default_source_radius() -> f64 {
    0.008
}
impl Source {
    fn validate(&self) -> Result<(), String> {
        bounded(self.x, 0., 1., "source x")?;
        bounded(self.y, 0., 1., "source y")?;
        bounded(self.frequency_hz, 0.05, 40., "frequency_hz")?;
        bounded(self.amplitude_m, 0., 0.002, "amplitude_m")?;
        bounded(self.phase_rad, -100., 100., "phase_rad")?;
        bounded(self.radius_m, 0.0005, 0.1, "radius_m")?;
        if !["point", "plane"].contains(&self.kind.as_str()) {
            return Err("Unknown source kind".into());
        }
        Ok(())
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub format: String,
    pub version: u32,
    pub model: String,
    pub config: Config,
    pub eta: Vec<f64>,
    pub ux: Vec<f64>,
    pub uy: Vec<f64>,
    pub depth: Vec<f64>,
    pub walls: Vec<u8>,
    pub sources: Vec<Source>,
    pub time_s: f64,
    pub steps: u64,
    pub intensity: Vec<f64>,
}

pub struct Tank {
    pub state: Snapshot,
    mu: Vec<f64>,
    hx: Vec<f64>,
    hy: Vec<f64>,
    right: Vec<usize>,
    down: Vec<usize>,
    left: Vec<usize>,
    up: Vec<usize>,
    sponge: Vec<f64>,
    dt: f64,
    drag_eta: Vec<f64>,
    drag_x: Vec<f64>,
    drag_y: Vec<f64>,
    source_profiles: Vec<Vec<(usize, f64)>>,
    pub pixels: Vec<u8>,
    view: String,
}

impl Tank {
    pub fn new(config: Config) -> Result<Self, String> {
        config.validate()?;
        let n = config.nx * config.ny;
        let depth = vec![config.depth_m; n];
        Self::from_snapshot(Snapshot {
            format: "flintglade-ripple".into(),
            version: 1,
            model: MODEL.into(),
            config,
            eta: vec![0.; n],
            ux: vec![0.; n],
            uy: vec![0.; n],
            depth,
            walls: vec![0; n],
            sources: vec![],
            time_s: 0.,
            steps: 0,
            intensity: vec![0.; n],
        })
    }
    pub fn from_snapshot(state: Snapshot) -> Result<Self, String> {
        if state.format != "flintglade-ripple" || state.version != 1 || state.model != MODEL {
            return Err("Unsupported state format, version or model".into());
        }
        state.config.validate()?;
        let n = state.config.nx * state.config.ny;
        for (name, a, limit) in [
            ("eta", &state.eta, 10.),
            ("ux", &state.ux, 100.),
            ("uy", &state.uy, 100.),
            ("depth", &state.depth, 0.2),
            ("intensity", &state.intensity, 100.),
        ] {
            if a.len() != n || a.iter().any(|v| !v.is_finite() || v.abs() > limit) {
                return Err(format!("Invalid {name} array"));
            }
        }
        if state.depth.iter().any(|v| *v < 0.0005) || state.intensity.iter().any(|v| *v < 0.) {
            return Err("Depth/intensity out of bounds".into());
        }
        if state.walls.len() != n || state.walls.iter().any(|v| *v > 1) {
            return Err("Invalid walls array".into());
        }
        bounded(state.time_s, 0., 1e9, "time_s")?;
        if state.steps > 1_000_000_000_000 {
            return Err("Step count out of bounds".into());
        }
        if state.sources.len() > 16 {
            return Err("At most 16 sources".into());
        }
        for s in &state.sources {
            s.validate()?;
        }
        let mut tank = Self {
            state,
            mu: vec![0.; n],
            hx: vec![0.; n],
            hy: vec![0.; n],
            right: vec![0; n],
            down: vec![0; n],
            left: vec![0; n],
            up: vec![0; n],
            sponge: vec![0.; n],
            dt: 0.,
            drag_eta: vec![1.; n],
            drag_x: vec![1.; n],
            drag_y: vec![1.; n],
            source_profiles: vec![],
            pixels: vec![0; 4 * n],
            view: "height".into(),
        };
        tank.geometry();
        // Reject inconsistent states instead of silently editing a loaded experiment.
        for i in 0..n {
            if (tank.state.walls[i] != 0
                && (tank.state.eta[i] != 0. || tank.state.intensity[i] != 0.))
                || (tank.hx[i] == 0. && tank.state.ux[i] != 0.)
                || (tank.hy[i] == 0. && tank.state.uy[i] != 0.)
            {
                return Err("State contains water or flow in a solid/closed face".into());
            }
        }
        Ok(tank)
    }
    fn geometry(&mut self) {
        let c = &self.state.config;
        let (w, h) = (c.nx, c.ny);
        let periodic = c.boundary == "periodic";
        let mut maxdepth: f64 = c.depth_m;
        for y in 0..h {
            for x in 0..w {
                let i = y * w + x;
                let r = if x + 1 < w {
                    i + 1
                } else if periodic {
                    y * w
                } else {
                    i
                };
                let d = if y + 1 < h {
                    i + w
                } else if periodic {
                    x
                } else {
                    i
                };
                let l = if x > 0 {
                    i - 1
                } else if periodic {
                    i + w - 1
                } else {
                    i
                };
                let u = if y > 0 {
                    i - w
                } else if periodic {
                    (h - 1) * w + x
                } else {
                    i
                };
                self.right[i] = if self.state.walls[r] == 0 { r } else { i };
                self.down[i] = if self.state.walls[d] == 0 { d } else { i };
                self.left[i] = if self.state.walls[l] == 0 { l } else { i };
                self.up[i] = if self.state.walls[u] == 0 { u } else { i };
                let a = self.state.depth[i];
                self.hx[i] = if self.state.walls[i] == 0 && self.state.walls[r] == 0 && r != i {
                    2. * a * self.state.depth[r] / (a + self.state.depth[r])
                } else {
                    0.
                };
                self.hy[i] = if self.state.walls[i] == 0 && self.state.walls[d] == 0 && d != i {
                    2. * a * self.state.depth[d] / (a + self.state.depth[d])
                } else {
                    0.
                };
                maxdepth = maxdepth.max(a);
                let distance = x.min(y).min(w - 1 - x).min(h - 1 - y) as f64;
                let width = (w.min(h) as f64 * 0.14).max(4.);
                // Deliberate lossy rim, never described as a reflection-free boundary.
                self.sponge[i] = if c.boundary == "sponge" {
                    12. * (1. - distance / width).max(0.).powi(2)
                } else {
                    0.
                };
            }
        }
        let lambda = 8. / c.dx().powi(2);
        self.dt = 0.8
            / (maxdepth * (c.gravity * lambda + c.surface_tension / RHO * lambda * lambda)).sqrt();
        for source in &self.state.sources {
            if source.enabled {
                self.dt = self.dt.min(1. / (32. * source.frequency_hz));
            }
        }
        for i in 0..self.sponge.len() {
            self.drag_eta[i] = (-self.sponge[i] * self.dt * 0.5).exp();
            self.drag_x[i] = (-(c.damping + (self.sponge[i] + self.sponge[self.right[i]]) * 0.5)
                * self.dt
                * 0.5)
                .exp();
            self.drag_y[i] =
                (-(c.damping + (self.sponge[i] + self.sponge[self.down[i]]) * 0.5) * self.dt * 0.5)
                    .exp();
        }
        self.source_profiles = self
            .state
            .sources
            .iter()
            .map(|s| {
                let sx = s.x * (w - 1) as f64;
                let sy = s.y * (h - 1) as f64;
                let mut profile = vec![];
                let sigma = s.radius_m / c.dx();
                let reach = (sigma * 4.).ceil() as usize + 1;
                let gaussian_cell = |center: f64, source: f64| {
                    let z = std::f64::consts::SQRT_2 * sigma;
                    sigma
                        * (std::f64::consts::PI / 2.).sqrt()
                        * (libm::erf((center + 0.5 - source) / z)
                            - libm::erf((center - 0.5 - source) / z))
                };
                let yr = if s.kind == "plane" {
                    0..h
                } else {
                    (sy as usize).saturating_sub(reach)..(sy as usize + reach + 1).min(h)
                };
                for y in yr {
                    for x in (sx as usize).saturating_sub(reach)..(sx as usize + reach + 1).min(w) {
                        let i = y * w + x;
                        if self.state.walls[i] == 0 {
                            let wx = gaussian_cell(x as f64, sx);
                            let wy = if s.kind == "plane" {
                                1.
                            } else {
                                gaussian_cell(y as f64, sy)
                            };
                            profile.push((i, wx * wy));
                        }
                    }
                }
                profile
            })
            .collect();
    }
    fn potential(&mut self) {
        let c = &self.state.config;
        let eta = &self.state.eta;
        let scale = c.surface_tension / RHO / c.dx().powi(2);
        for i in 0..eta.len() {
            self.mu[i] = c.gravity * eta[i]
                - scale
                    * (eta[self.left[i]]
                        + eta[self.right[i]]
                        + eta[self.up[i]]
                        + eta[self.down[i]]
                        - 4. * eta[i]);
        }
    }
    fn kick(&mut self, dt: f64) {
        self.potential();
        let scale = dt / self.state.config.dx();
        for i in 0..self.mu.len() {
            if self.hx[i] > 0. {
                self.state.ux[i] -= scale * (self.mu[self.right[i]] - self.mu[i]);
            }
            if self.hy[i] > 0. {
                self.state.uy[i] -= scale * (self.mu[self.down[i]] - self.mu[i]);
            }
        }
    }
    fn drag(&mut self) {
        for i in 0..self.sponge.len() {
            self.state.eta[i] *= self.drag_eta[i];
            self.state.ux[i] *= self.drag_x[i];
            self.state.uy[i] *= self.drag_y[i];
        }
    }
    pub fn step(&mut self) {
        let dt = self.dt;
        self.drag();
        self.kick(dt * 0.5);
        let c = &self.state.config;
        let (w, h) = (c.nx, c.ny);
        let periodic = c.boundary == "periodic";
        let scale = dt / c.dx();
        // Incoming face indices must refer to geometric neighbors, not Neumann ghost cells.
        for y in 0..h {
            for x in 0..w {
                let i = y * w + x;
                if self.state.walls[i] != 0 {
                    continue;
                }
                let fx = if x > 0 {
                    self.hx[i - 1] * self.state.ux[i - 1]
                } else if periodic {
                    self.hx[i + w - 1] * self.state.ux[i + w - 1]
                } else {
                    0.
                };
                let fy = if y > 0 {
                    self.hy[i - w] * self.state.uy[i - w]
                } else if periodic {
                    self.hy[(h - 1) * w + x] * self.state.uy[(h - 1) * w + x]
                } else {
                    0.
                };
                self.state.eta[i] -= scale
                    * (self.hx[i] * self.state.ux[i] - fx + self.hy[i] * self.state.uy[i] - fy);
            }
        }
        let tm = self.state.time_s + dt * 0.5;
        for (s, profile) in self.state.sources.iter().zip(&self.source_profiles) {
            if !s.enabled {
                continue;
            }
            let omega = std::f64::consts::TAU * s.frequency_hz;
            let drive = s.amplitude_m
                * omega
                * (omega * tm + s.phase_rad).sin()
                * dt
                * (1. - (-(tm * s.frequency_hz).powi(2)).exp());
            for &(i, weight) in profile {
                self.state.eta[i] += drive * weight;
            }
        }
        self.kick(dt * 0.5);
        self.drag();
        let retain = (-dt / 0.25).exp();
        for i in 0..self.state.eta.len() {
            self.state.intensity[i] =
                retain * self.state.intensity[i] + (1. - retain) * self.state.eta[i].powi(2);
        }
        self.state.time_s += dt;
        self.state.steps += 1;
    }
    pub fn clear(&mut self) {
        self.state.eta.fill(0.);
        self.state.ux.fill(0.);
        self.state.uy.fill(0.);
        self.state.intensity.fill(0.);
        self.state.time_s = 0.;
        self.state.steps = 0;
    }
    pub fn preset(&mut self, name: &str) -> Result<(), String> {
        if ![
            "double-slit",
            "single-slit",
            "two-sources",
            "lens",
            "single",
            "empty",
            "pulse",
        ]
        .contains(&name)
        {
            return Err("Unknown preset".into());
        }
        self.clear();
        self.state.walls.fill(0);
        self.state.depth.fill(self.state.config.depth_m);
        self.state.sources.clear();
        let (w, h) = (self.state.config.nx, self.state.config.ny);
        let src = |x, y, kind: &str| Source {
            x,
            y,
            frequency_hz: 3.,
            amplitude_m: 0.00015,
            phase_rad: 0.,
            kind: kind.into(),
            enabled: true,
            radius_m: default_source_radius(),
        };
        match name {
            "double-slit" | "single-slit" => {
                self.state.sources.push(src(0.18, 0.5, "plane"));
                for y in 0..h {
                    let yy = y as f64 / h as f64;
                    let gap = if name == "single-slit" {
                        (yy - 0.5).abs() < 0.07
                    } else {
                        (yy - 0.35).abs() < 0.035 || (yy - 0.65).abs() < 0.035
                    };
                    if !gap {
                        for x in w * 36 / 100..w * 36 / 100 + 2 {
                            self.state.walls[y * w + x] = 1;
                        }
                    }
                }
            }
            "two-sources" => {
                self.state.sources.push(src(0.3, 0.34, "point"));
                self.state.sources.push(src(0.3, 0.66, "point"));
            }
            "single" => self.state.sources.push(src(0.25, 0.5, "point")),
            "lens" => {
                self.state.sources.push(src(0.18, 0.5, "plane"));
                for y in 0..h {
                    for x in 0..w {
                        if ((x as f64 / w as f64 - 0.47) / 0.10).powi(2)
                            + ((y as f64 / h as f64 - 0.5) / 0.34).powi(2)
                            < 1.
                        {
                            self.state.depth[y * w + x] =
                                (self.state.config.depth_m * 0.4).max(0.0005);
                        }
                    }
                }
            }
            "pulse" => self.pulse(0.5, 0.5, 0.04, 0.0003)?,
            _ => {}
        }
        self.geometry();
        Ok(())
    }
    pub fn pulse(&mut self, x: f64, y: f64, radius: f64, amplitude: f64) -> Result<(), String> {
        bounded(x, 0., 1., "x")?;
        bounded(y, 0., 1., "y")?;
        bounded(radius, 0.002, 0.2, "radius")?;
        bounded(amplitude, -0.002, 0.002, "amplitude_m")?;
        let (w, h) = (self.state.config.nx, self.state.config.ny);
        let sigma = (radius * w as f64).max(1.);
        for yy in 0..h {
            for xx in 0..w {
                let i = yy * w + xx;
                if self.state.walls[i] == 0 {
                    let d = (xx as f64 - x * (w - 1) as f64).powi(2)
                        + (yy as f64 - y * (h - 1) as f64).powi(2);
                    self.state.eta[i] += amplitude * (-d / (2. * sigma * sigma)).exp();
                }
            }
        }
        Ok(())
    }
    pub fn paint(
        &mut self,
        x: f64,
        y: f64,
        radius: f64,
        tool: &str,
        depth: f64,
    ) -> Result<(), String> {
        bounded(x, 0., 1., "x")?;
        bounded(y, 0., 1., "y")?;
        bounded(radius, 0.002, 0.2, "radius")?;
        bounded(depth, 0.0005, 0.2, "depth_m")?;
        if !["wall", "depth", "erase"].contains(&tool) {
            return Err("Unknown paint tool".into());
        }
        let (w, h) = (self.state.config.nx, self.state.config.ny);
        for yy in 0..h {
            for xx in 0..w {
                if (xx as f64 - x * (w - 1) as f64).powi(2)
                    + (yy as f64 - y * (h - 1) as f64).powi(2)
                    > (radius * w as f64).powi(2)
                {
                    continue;
                }
                let i = yy * w + xx;
                self.state.walls[i] = u8::from(tool == "wall");
                if tool == "wall" {
                    self.state.eta[i] = 0.;
                    self.state.intensity[i] = 0.;
                }
                self.state.depth[i] = if tool == "depth" {
                    depth
                } else {
                    self.state.config.depth_m
                };
            }
        }
        self.geometry();
        for i in 0..w * h {
            if self.hx[i] == 0. {
                self.state.ux[i] = 0.;
            }
            if self.hy[i] == 0. {
                self.state.uy[i] = 0.;
            }
        }
        Ok(())
    }
    pub fn mass(&self) -> f64 {
        self.state.eta.iter().sum::<f64>() * self.state.config.dx().powi(2)
    }
    pub fn energy(&self) -> f64 {
        let c = &self.state.config;
        let dx = c.dx();
        let mut e = 0.;
        for i in 0..self.state.eta.len() {
            if self.state.walls[i] != 0 {
                continue;
            }
            let a = self.state.eta[i];
            e += RHO * c.gravity * a * a * dx * dx;
            e += c.surface_tension
                * ((self.state.eta[self.right[i]] - a).powi(2)
                    + (self.state.eta[self.down[i]] - a).powi(2));
            e += RHO
                * (self.hx[i] * self.state.ux[i].powi(2) + self.hy[i] * self.state.uy[i].powi(2))
                * dx
                * dx;
        }
        e * 0.5
    }
    pub fn diagnostics(&self) -> Value {
        let max = self.state.eta.iter().fold(0_f64, |a, b| a.max(b.abs()));
        json!({"time_s":self.state.time_s,"dt_s":self.dt,"steps":self.state.steps,"mass_m3":self.mass(),"energy_j":self.energy(),"max_height_m":max,"courant":(self.state.config.gravity*self.state.config.depth_m).sqrt()*self.dt/self.state.config.dx(),"source_count":self.state.sources.len(),"max_height_depth_ratio":self.state.eta.iter().zip(&self.state.depth).map(|(a,h)|a.abs()/h).fold(0_f64,f64::max)})
    }
    pub fn render(&mut self) {
        for i in 0..self.state.eta.len() {
            let rgb = if self.state.walls[i] != 0 {
                [160, 174, 185]
            } else if self.view == "depth" {
                let v = (self.state.depth[i] / self.state.config.depth_m / 2.).clamp(0., 1.);
                [
                    (16. + 20. * v) as u8,
                    (40. + 100. * v) as u8,
                    (55. + 175. * v) as u8,
                ]
            } else if self.view == "intensity" {
                let v = (self.state.intensity[i].sqrt() / 0.0003)
                    .clamp(0., 1.)
                    .sqrt();
                [
                    (16. + 95. * v) as u8,
                    (21. + 195. * v) as u8,
                    (27. + 225. * v) as u8,
                ]
            } else {
                let v = (self.state.eta[i] / 0.0003).clamp(-1., 1.);
                if v >= 0. {
                    [
                        (16. + 232. * v) as u8,
                        (21. + 152. * v) as u8,
                        (27. + 71. * v) as u8,
                    ]
                } else {
                    [
                        (16. - 80. * v) as u8,
                        (21. - 181. * v) as u8,
                        (27. - 223. * v) as u8,
                    ]
                }
            };
            self.pixels[4 * i..4 * i + 4].copy_from_slice(&[rgb[0], rgb[1], rgb[2], 255]);
        }
    }
    pub fn command(&mut self, v: &Value) -> Result<Value, String> {
        let op = v["op"].as_str().ok_or("Missing op")?;
        match op {
            "advance" => {
                let n = v["steps"].as_u64().ok_or("steps must be integer")?;
                if !(1..=256).contains(&n) {
                    return Err("steps must be 1..256".into());
                }
                for _ in 0..n {
                    self.step();
                }
                if self
                    .state
                    .eta
                    .iter()
                    .chain(&self.state.ux)
                    .chain(&self.state.uy)
                    .any(|x| !x.is_finite() || x.abs() > 100.)
                {
                    self.clear();
                    return Err("Numerical range exceeded; field cleared".into());
                }
            }
            "preset" => self.preset(v["name"].as_str().ok_or("Missing preset name")?)?,
            "clear" => self.clear(),
            "set" => {
                let patch = v["config"].as_object().ok_or("config must be object")?;
                let mut cfg =
                    serde_json::to_value(&self.state.config).map_err(|e| e.to_string())?;
                for (k, val) in patch {
                    if ["nx", "ny", "width_m"].contains(&k.as_str()) {
                        return Err("Grid and width changes require new".into());
                    }
                    cfg[k] = val.clone();
                }
                let c: Config = serde_json::from_value(cfg).map_err(|e| e.to_string())?;
                c.validate()?;
                let ratio = c.depth_m / self.state.config.depth_m;
                if self
                    .state
                    .depth
                    .iter()
                    .any(|d| *d * ratio < 0.0005 || *d * ratio > 0.2)
                {
                    return Err("Rescaled painted depths out of bounds".into());
                }
                self.state.depth.iter_mut().for_each(|d| *d *= ratio);
                self.state.config = c;
                self.geometry();
                for i in 0..self.hx.len() {
                    if self.hx[i] == 0. {
                        self.state.ux[i] = 0.;
                    }
                    if self.hy[i] == 0. {
                        self.state.uy[i] = 0.;
                    }
                }
            }
            "sources" => {
                let s: Vec<Source> =
                    serde_json::from_value(v["sources"].clone()).map_err(|e| e.to_string())?;
                if s.len() > 16 {
                    return Err("At most 16 sources".into());
                }
                for x in &s {
                    x.validate()?;
                }
                self.state.sources = s;
                self.geometry();
            }
            "paint" => self.paint(
                number(v, "x")?,
                number(v, "y")?,
                number(v, "radius")?,
                v["tool"].as_str().ok_or("Missing tool")?,
                v["depth_m"].as_f64().unwrap_or(self.state.config.depth_m),
            )?,
            "pulse" => self.pulse(
                number(v, "x")?,
                number(v, "y")?,
                number(v, "radius")?,
                number(v, "amplitude_m")?,
            )?,
            "view" => {
                let name = v["name"].as_str().ok_or("Missing view")?;
                if !["height", "intensity", "depth"].contains(&name) {
                    return Err("Unknown view".into());
                }
                self.view = name.into();
            }
            "probe" | "snapshot" | "csv" | "status" => {}
            _ => return Err("Unknown operation".into()),
        }
        let mut out = json!({"ok":true,"config":self.state.config,"diagnostics":self.diagnostics(),"sources":self.state.sources,"view":self.view});
        if op == "snapshot" {
            out["snapshot"] = serde_json::to_value(&self.state).map_err(|e| e.to_string())?;
        }
        if op == "probe" {
            let x = number(v, "x")?;
            let y = number(v, "y")?;
            bounded(x, 0., 1., "x")?;
            bounded(y, 0., 1., "y")?;
            let i = (y * (self.state.config.ny - 1) as f64).round() as usize * self.state.config.nx
                + (x * (self.state.config.nx - 1) as f64).round() as usize;
            out["probe"] = json!({"height_m":self.state.eta[i],"depth_m":self.state.depth[i],"solid":self.state.walls[i]!=0});
        }
        if op == "csv" {
            use std::fmt::Write;
            let mut csv = String::from("x_m,y_m,eta_m,depth_m,solid\n");
            let c = &self.state.config;
            for y in 0..c.ny {
                for x in 0..c.nx {
                    let i = y * c.nx + x;
                    writeln!(
                        csv,
                        "{:.9},{:.9},{:.12},{:.9},{}",
                        (x as f64 + 0.5) * c.dx(),
                        (y as f64 + 0.5) * c.dx(),
                        self.state.eta[i],
                        self.state.depth[i],
                        self.state.walls[i]
                    )
                    .map_err(|e| e.to_string())?;
                }
            }
            out["csv"] = Value::String(csv);
        }
        self.render();
        Ok(out)
    }
}
fn number(v: &Value, key: &str) -> Result<f64, String> {
    v[key]
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or_else(|| format!("Missing finite {key}"))
}

#[derive(Default)]
pub struct Session {
    pub tank: Option<Tank>,
}
impl Session {
    pub fn request(&mut self, bytes: &[u8]) -> Value {
        let result = (|| -> Result<Value, String> {
            if bytes.len() > MAX_INPUT {
                return Err("Request exceeds 32MiB".into());
            }
            let v: Value = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
            match v["op"].as_str() {
                Some("new") => {
                    let cfg: Config =
                        serde_json::from_value(v.get("config").cloned().unwrap_or(json!({})))
                            .map_err(|e| e.to_string())?;
                    let mut t = Tank::new(cfg)?;
                    t.preset(v["preset"].as_str().unwrap_or("double-slit"))?;
                    let out = t.command(&json!({"op":"status"}))?;
                    self.tank = Some(t);
                    Ok(out)
                }
                Some("load") => {
                    let state: Snapshot =
                        serde_json::from_value(v["snapshot"].clone()).map_err(|e| e.to_string())?;
                    let mut t = Tank::from_snapshot(state)?;
                    let out = t.command(&json!({"op":"status"}))?;
                    self.tank = Some(t);
                    Ok(out)
                }
                _ => self
                    .tank
                    .as_mut()
                    .ok_or("Create or load a tank first")?
                    .command(&v),
            }
        })();
        match result {
            Ok(v) => v,
            Err(e) => json!({"ok":false,"error":e}),
        }
    }
}

struct Abi {
    session: Session,
    input: Vec<u8>,
    output: Vec<u8>,
}
thread_local! {static ABI:RefCell<Abi>=RefCell::new(Abi{session:Session::default(),input:vec![0;MAX_INPUT],output:vec![]});}
#[no_mangle]
pub extern "C" fn ripple_input_ptr() -> *mut u8 {
    ABI.with(|a| a.borrow_mut().input.as_mut_ptr())
}
#[no_mangle]
pub extern "C" fn ripple_request(len: u32) -> u32 {
    ABI.with(|a| {
        let mut a = a.borrow_mut();
        let result = if len as usize > MAX_INPUT {
            json!({"ok":false,"error":"Request exceeds 32MiB"})
        } else {
            let Abi { session, input, .. } = &mut *a;
            session.request(&input[..len as usize])
        };
        let code = u32::from(result["ok"] != true);
        a.output = serde_json::to_vec(&result).unwrap_or_default();
        code
    })
}
#[no_mangle]
pub extern "C" fn ripple_output_ptr() -> *const u8 {
    ABI.with(|a| a.borrow().output.as_ptr())
}
#[no_mangle]
pub extern "C" fn ripple_output_len() -> u32 {
    ABI.with(|a| a.borrow().output.len() as u32)
}
#[no_mangle]
pub extern "C" fn ripple_pixels_ptr() -> *const u8 {
    ABI.with(|a| {
        a.borrow()
            .session
            .tank
            .as_ref()
            .map_or(std::ptr::null(), |t| t.pixels.as_ptr())
    })
}
#[no_mangle]
pub extern "C" fn ripple_pixels_len() -> u32 {
    ABI.with(|a| {
        a.borrow()
            .session
            .tank
            .as_ref()
            .map_or(0, |t| t.pixels.len() as u32)
    })
}
