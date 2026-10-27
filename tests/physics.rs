use flintglade_ripple::{Config, Session, Tank};
use serde_json::json;
use std::f64::consts::TAU;

fn config(n: usize) -> Config {
    Config {
        nx: n,
        ny: 32,
        width_m: 0.8,
        depth_m: 0.005,
        gravity: 9.81,
        surface_tension: 0.,
        damping: 0.,
        boundary: "periodic".into(),
    }
}
fn mode(n: usize, m: usize, sigma: f64) -> Tank {
    let mut t = Tank::new(Config {
        surface_tension: sigma,
        ..config(n)
    })
    .unwrap();
    for y in 0..32 {
        for x in 0..n {
            t.state.eta[y * n + x] = 0.0001 * (TAU * m as f64 * (x as f64 + 0.5) / n as f64).cos();
        }
    }
    t
}
fn mode_error(n: usize, sigma: f64) -> f64 {
    let m = 3;
    let mut t = mode(n, m, sigma);
    let k = TAU * m as f64 / 0.8;
    let omega = (t.state.config.depth_m * (9.81 * k * k + sigma / 1000. * k.powi(4))).sqrt();
    let target = 1.4 / omega;
    while t.state.time_s < target {
        t.step();
    }
    let factor = (omega * t.state.time_s).cos();
    (0..n)
        .map(|x| {
            let expected = 0.0001 * (TAU * m as f64 * (x as f64 + 0.5) / n as f64).cos() * factor;
            (t.state.eta[x] - expected).powi(2)
        })
        .sum::<f64>()
        .sqrt()
        / (n as f64).sqrt()
        / 0.0001
}
#[test]
fn analytic_gravity_and_capillary_modes_converge_quadratically() {
    for sigma in [0., 0.072] {
        let a = mode_error(48, sigma);
        let b = mode_error(96, sigma);
        let c = mode_error(192, sigma);
        eprintln!("sigma={sigma}: errors={a},{b},{c}");
        assert!(a / b > 3.5 && b / c > 3.5);
        assert!(c < 0.0015);
    }
}
#[test]
fn dispersion_matches_discrete_reference() {
    // Short mode: capillary term materially changes omega. This detects an omitted or wrong-sign biharmonic term.
    let (n, m) = (128, 12);
    let mut t = mode(n, m, 0.072);
    let dx = t.state.config.dx();
    let lambda = 4. * (std::f64::consts::PI * m as f64 / n as f64).sin().powi(2) / (dx * dx);
    let omega = (0.005 * (9.81 * lambda + 0.072 / 1000. * lambda * lambda)).sqrt();
    let dt = t.diagnostics()["dt_s"].as_f64().unwrap();
    let theta = 2. * (omega * dt * 0.5).asin();
    for _ in 0..731 {
        t.step();
    }
    let expected = 0.0001 * (TAU * m as f64 * 0.5 / n as f64).cos() * (731. * theta).cos();
    assert!((t.state.eta[0] - expected).abs() < 2e-16);
}
#[test]
fn closed_variable_depth_mass_and_energy() {
    let mut t = mode(96, 2, 0.072);
    t.paint(0.5, 0.5, 0.12, "depth", 0.002).unwrap();
    let mass = t.mass();
    let energy = t.energy();
    let mut maxdrift: f64 = 0.;
    for _ in 0..3000 {
        t.step();
        maxdrift = maxdrift.max((t.energy() / energy - 1.).abs());
    }
    eprintln!(
        "mass error {}, max energy drift {maxdrift}",
        t.mass() - mass
    );
    assert!((t.mass() - mass).abs() < 1e-17);
    assert!(maxdrift < 0.003);
}
#[test]
fn impermeable_barrier_prevents_transmission() {
    let mut t = Tank::new(Config {
        nx: 96,
        ny: 64,
        boundary: "reflective".into(),
        damping: 0.,
        surface_tension: 0.072,
        ..Config::default()
    })
    .unwrap();
    for y in 0..64 {
        t.state.walls[y * 96 + 48] = 1;
    }
    t = Tank::from_snapshot(t.state.clone()).unwrap();
    t.pulse(0.25, 0.5, 0.025, 0.0002).unwrap();
    // Compact support on the left removes the Gaussian's tiny tail from the protected right compartment.
    for y in 0..64 {
        for x in 49..96 {
            t.state.eta[y * 96 + x] = 0.;
        }
    }
    for _ in 0..1500 {
        t.step();
    }
    assert!((0..64).all(|y| (49..96).all(|x| t.state.eta[y * 96 + x] == 0.)));
}
#[test]
fn reflective_normal_mode_has_neumann_boundary() {
    let n = 96;
    let m = 3;
    let mut t = Tank::new(Config {
        boundary: "reflective".into(),
        ..config(n)
    })
    .unwrap();
    for y in 0..32 {
        for x in 0..n {
            t.state.eta[y * n + x] =
                0.0001 * (std::f64::consts::PI * m as f64 * (x as f64 + 0.5) / n as f64).cos();
        }
    }
    let dt = t.diagnostics()["dt_s"].as_f64().unwrap();
    let lambda = 4.
        * (std::f64::consts::PI * m as f64 / (2. * n as f64))
            .sin()
            .powi(2)
        / t.state.config.dx().powi(2);
    let theta = 2. * ((0.005 * 9.81 * lambda).sqrt() * dt * 0.5).asin();
    for _ in 0..1000 {
        t.step();
    }
    assert!(
        (t.state.eta[0]
            - 0.0001
                * (std::f64::consts::PI * m as f64 * 0.5 / n as f64).cos()
                * (1000. * theta).cos())
        .abs()
            < 1e-16
    );
}
#[test]
fn sponge_and_drag_remove_energy() {
    let mut a = Tank::new(Config {
        nx: 96,
        ny: 64,
        damping: 0.,
        boundary: "reflective".into(),
        ..Config::default()
    })
    .unwrap();
    a.pulse(0.5, 0.5, 0.035, 0.0002).unwrap();
    let mut s = a.state.clone();
    s.config.boundary = "sponge".into();
    let mut b = Tank::from_snapshot(s).unwrap();
    let e = a.energy();
    for _ in 0..1600 {
        a.step();
        b.step();
    }
    eprintln!(
        "sponge residual {} reflective {}",
        b.energy() / e,
        a.energy() / e
    );
    assert!(b.energy() / a.energy() < 0.03);
    let mut d = mode(96, 2, 0.);
    d.state.config.damping = 1.;
    d = Tank::from_snapshot(d.state.clone()).unwrap();
    let e = d.energy();
    for _ in 0..1500 {
        d.step();
    }
    assert!(d.energy() / e < 0.05);
}
#[test]
fn depth_scales_gravity_phase_speed() {
    let mut a = mode(96, 3, 0.);
    let mut s = a.state.clone();
    s.config.depth_m *= 4.;
    s.depth.iter_mut().for_each(|h| *h *= 4.);
    let mut b = Tank::from_snapshot(s).unwrap();
    for _ in 0..400 {
        a.step();
        b.step();
    } // dt halves exactly when depth quadruples, same dimensionless solution.
    assert!((a.state.time_s / b.state.time_s - 2.).abs() < 1e-12);
    assert!(a
        .state
        .eta
        .iter()
        .zip(&b.state.eta)
        .all(|(x, y)| (x - y).abs() < 1e-16));
}
#[test]
fn deterministic_restart_preserves_full_state() {
    let mut a = Tank::new(Config {
        nx: 64,
        ny: 40,
        ..Config::default()
    })
    .unwrap();
    a.preset("double-slit").unwrap();
    for _ in 0..100 {
        a.step();
    }
    let text = serde_json::to_vec(&a.state).unwrap();
    let mut b = Tank::from_snapshot(serde_json::from_slice(&text).unwrap()).unwrap();
    for _ in 0..177 {
        a.step();
        b.step();
    }
    // Exact floating roundtrip is enabled explicitly in Cargo.toml.
    assert_eq!(a.state.eta, b.state.eta);
    assert_eq!(a.state.ux, b.state.ux);
    assert_eq!(a.state.intensity, b.state.intensity);
}
#[test]
fn invalid_import_does_not_replace_active_experiment() {
    let mut s = Session::default();
    assert_eq!(
        s.request(br#"{"op":"new","preset":"pulse","config":{"nx":32,"ny":32}}"#)["ok"],
        true
    );
    let before = s.request(br#"{"op":"snapshot"}"#)["snapshot"].clone();
    for command in [
        json!({"op":"load","snapshot":{"version":2}}),
        json!({"op":"set","config":{"depth_m":-1}}),
        json!({"op":"advance","steps":1e9}),
        json!({"op":"new","config":{"nx":99999999}}),
        json!({"op":"paint","x":-1,"y":0.5,"radius":0.01,"tool":"wall"}),
    ] {
        assert_eq!(
            s.request(&serde_json::to_vec(&command).unwrap())["ok"],
            false
        );
        assert_eq!(s.request(br#"{"op":"snapshot"}"#)["snapshot"], before);
    }
}
#[test]
fn solid_and_face_state_validation() {
    let mut s = Tank::new(Config {
        nx: 32,
        ny: 32,
        boundary: "reflective".into(),
        ..Config::default()
    })
    .unwrap()
    .state;
    s.ux[31] = 1.;
    assert!(Tank::from_snapshot(s.clone()).is_err());
    s.ux[31] = 0.;
    s.walls[10] = 1;
    s.eta[10] = 1e-4;
    assert!(Tank::from_snapshot(s).is_err());
}

#[test]
fn depth_interface_matches_shallow_water_reflection_and_transmission() {
    let (nx, ny) = (512, 32);
    let mut t = Tank::new(Config {
        nx,
        ny,
        width_m: 0.8,
        depth_m: 0.008,
        surface_tension: 0.,
        damping: 0.,
        boundary: "reflective".into(),
        ..Config::default()
    })
    .unwrap();
    let dx = t.state.config.dx();
    let gaussian = |x: f64| 0.0001 * (-((x - 0.2) / 0.018).powi(2) * 0.5).exp();
    for y in 0..ny {
        for x in 0..nx {
            let i = y * nx + x;
            if x >= nx / 2 {
                t.state.depth[i] = 0.002;
            }
            t.state.eta[i] = gaussian((x as f64 + 0.5) * dx);
            if x < nx - 1 {
                t.state.ux[i] = (9.81_f64 / 0.008).sqrt() * gaussian((x as f64 + 1.) * dx);
            }
        }
    }
    t = Tank::from_snapshot(t.state).unwrap();
    while t.state.time_s < 1.2 {
        t.step();
    }
    let peak = |range: std::ops::Range<usize>| range.map(|x| t.state.eta[x]).fold(0_f64, f64::max);
    let reflected = peak(130..220) / 0.0001;
    let transmitted = peak(270..330) / 0.0001;
    eprintln!("depth-step amplitudes: reflected={reflected} transmitted={transmitted}");
    assert!((reflected - 1. / 3.).abs() < 0.02);
    assert!((transmitted - 4. / 3.).abs() < 0.04);
}

#[test]
fn narrow_sources_are_cell_integrated_and_time_resolved() {
    fn driven(n: usize, x: f64) -> Tank {
        let mut s = Session::default();
        let commands = [
            json!({"op":"new","config":{"nx":n,"ny":n,"width_m":10.,"depth_m":0.0005,"gravity":0.1,"surface_tension":0.,"damping":0.,"boundary":"reflective"},"preset":"empty"}),
            json!({"op":"sources","sources":[{"x":x,"y":0.5,"frequency_hz":40.,"amplitude_m":0.00015,"phase_rad":0.,"kind":"plane","enabled":true,"radius_m":0.008}]}),
            json!({"op":"advance","steps":256}),
        ];
        for c in commands {
            assert_eq!(s.request(&serde_json::to_vec(&c).unwrap())["ok"], true);
        }
        s.tank.unwrap()
    }
    let a = driven(32, 0.5);
    let b = driven(32, 16. / 31.);
    let c = driven(64, 0.5);
    assert!((a.state.time_s - 0.2).abs() < 1e-14);
    for t in [&a, &b, &c] {
        assert!(t.diagnostics()["max_height_m"].as_f64().unwrap() > 1e-7);
    }
    assert!((a.mass() - b.mass()).abs() < 1e-17);
    assert!((a.mass() - c.mass()).abs() < 1e-17);
}
