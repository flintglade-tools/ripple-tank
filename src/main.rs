use flintglade_ripple::{Config, Session, Tank, MAX_INPUT};
use serde_json::{json, Value};
use std::{
    env, fs,
    io::{self, BufRead, Read, Write},
    path::Path,
    time::Instant,
};

fn read(path: &str) -> Result<Vec<u8>, String> {
    let mut f = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut b = Vec::new();
    Read::by_ref(&mut f)
        .take((MAX_INPUT + 1) as u64)
        .read_to_end(&mut b)
        .map_err(|e| e.to_string())?;
    if b.len() > MAX_INPUT {
        return Err("File exceeds 32MiB".into());
    }
    Ok(b)
}
fn save(path: &str, value: &Value) -> Result<(), String> {
    // Refuse accidental overwrite; choose a fresh output path for each experiment.
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    f.write_all(&serde_json::to_vec(value).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    f.write_all(b"\n").map_err(|e| e.to_string())
}
fn checked(session: &mut Session, command: Value) -> Result<Value, String> {
    let r = session.request(&serde_json::to_vec(&command).map_err(|e| e.to_string())?);
    if r["ok"] != true {
        Err(r["error"].as_str().unwrap_or("Engine failure").into())
    } else {
        Ok(r)
    }
}
fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{}", json!({"ok":false,"error":e}));
            std::process::ExitCode::FAILURE
        }
    }
}
fn run() -> Result<(), String> {
    let a: Vec<String> = env::args().collect();
    let usage="Ripple Tank 0.1.0\n  ripple new PRESET OUTPUT.ripple.json [CONFIG.json]\n  ripple run INPUT.ripple.json STEPS OUTPUT.ripple.json [FIELD.csv]\n  ripple inspect INPUT.ripple.json\n  ripple bench [NX NY STEPS]\n  ripple serve  # newline-delimited JSON command protocol on stdin/stdout\nOutputs never overwrite existing files; SI units, model and version are stored in each state.";
    if a.len() < 2 || ["--help", "-h", "help"].contains(&a[1].as_str()) {
        println!("{usage}");
        return Ok(());
    }
    let mut s = Session::default();
    match a[1].as_str() {
        "new" if (4..=5).contains(&a.len()) => {
            let cfg = if a.len() == 5 {
                serde_json::from_slice(&read(&a[4])?).map_err(|e| e.to_string())?
            } else {
                json!({})
            };
            checked(&mut s, json!({"op":"new","preset":a[2],"config":cfg}))?;
            let out = checked(&mut s, json!({"op":"snapshot"}))?;
            save(&a[3], &out["snapshot"])?;
            println!(
                "{}",
                json!({"ok":true,"output":a[3],"diagnostics":out["diagnostics"]})
            );
        }
        "run" if (5..=6).contains(&a.len()) => {
            if Path::new(&a[4]).exists() || (a.len() == 6 && Path::new(&a[5]).exists()) {
                return Err("Output already exists".into());
            }
            let snapshot: Value =
                serde_json::from_slice(&read(&a[2])?).map_err(|e| e.to_string())?;
            checked(&mut s, json!({"op":"load","snapshot":snapshot}))?;
            let n: u64 = a[3].parse().map_err(|_| "STEPS must be integer")?;
            if n > 10_000_000 {
                return Err("At most 10000000 steps per batch".into());
            }
            let start = Instant::now();
            let mut left = n;
            while left > 0 {
                let k = left.min(256);
                checked(&mut s, json!({"op":"advance","steps":k}))?;
                left -= k;
            }
            let out = checked(&mut s, json!({"op":"snapshot"}))?;
            save(&a[4], &out["snapshot"])?;
            if a.len() == 6 {
                let field = checked(&mut s, json!({"op":"csv"}))?;
                let mut f = fs::OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(&a[5])
                    .map_err(|e| e.to_string())?;
                f.write_all(field["csv"].as_str().ok_or("Missing CSV")?.as_bytes())
                    .map_err(|e| e.to_string())?;
            }
            println!(
                "{}",
                json!({"ok":true,"output":a[4],"wall_seconds":start.elapsed().as_secs_f64(),"diagnostics":out["diagnostics"]})
            );
        }
        "inspect" if a.len() == 3 => {
            let snapshot: Value =
                serde_json::from_slice(&read(&a[2])?).map_err(|e| e.to_string())?;
            let out = checked(&mut s, json!({"op":"load","snapshot":snapshot}))?;
            println!("{out}");
        }
        "bench" if a.len() == 2 || a.len() == 5 => {
            let (nx, ny, n) = if a.len() == 5 {
                (
                    a[2].parse().map_err(|_| "Bad NX")?,
                    a[3].parse().map_err(|_| "Bad NY")?,
                    a[4].parse::<usize>().map_err(|_| "Bad STEPS")?,
                )
            } else {
                (200, 120, 2000)
            };
            if !(1..=1_000_000).contains(&n) {
                return Err("Benchmark steps must be 1..1000000".into());
            }
            let mut t = Tank::new(Config {
                nx,
                ny,
                ..Config::default()
            })?;
            t.preset("double-slit")?;
            for _ in 0..20 {
                t.step();
            }
            let start = Instant::now();
            for _ in 0..n {
                t.step();
            }
            let secs = start.elapsed().as_secs_f64();
            let render = Instant::now();
            for _ in 0..100 {
                t.render();
            }
            let render_ms = render.elapsed().as_secs_f64() * 10.;
            println!(
                "{}",
                json!({"ok":true,"version":env!("CARGO_PKG_VERSION"),"nx":nx,"ny":ny,"steps":n,"seconds":secs,"ms_per_step":secs*1000./n as f64,"render_ms":render_ms,"sim_seconds_per_wall_second":n as f64*t.diagnostics()["dt_s"].as_f64().unwrap()/secs,"diagnostics":t.diagnostics()})
            );
        }
        "serve" if a.len() == 2 => {
            let mut input = io::stdin().lock();
            let mut stdout = io::stdout().lock();
            loop {
                let mut b = Vec::new();
                let n = input
                    .by_ref()
                    .take((MAX_INPUT + 1) as u64)
                    .read_until(b'\n', &mut b)
                    .map_err(|e| e.to_string())?;
                if n == 0 {
                    break;
                }
                if n > MAX_INPUT {
                    return Err("Request exceeds 32MiB".into());
                }
                let r = s.request(&b);
                writeln!(stdout, "{r}").map_err(|e| e.to_string())?;
                stdout.flush().map_err(|e| e.to_string())?;
            }
        }
        _ => return Err(format!("Invalid arguments.\n{usage}")),
    }
    Ok(())
}
