#[cfg(feature = "bluetooth")]
mod assets;
#[cfg(feature = "bluetooth")]
mod bluetooth;
#[cfg(feature = "bluetooth")]
mod ble_profile;
mod device;
#[cfg(feature = "bluetooth")]
mod display;
mod motion;
mod observation;
#[cfg(feature = "bluetooth")]
mod power;
mod repl;
#[cfg(feature = "bluetooth")]
mod session;
mod snap;

use clap::{Parser, Subcommand, ValueEnum};
use repl::{Fail, PREAMBLE, Repl};
use serde_json::json;
use std::io::Read;
use std::time::Duration;

#[derive(Parser)]
#[command(
    name = "vexaim",
    version,
    about = "Run MicroPython and save camera frames from a VEX AIM over USB or Bluetooth. USB is the default; Bluetooth must be selected explicitly."
)]
struct Cli {
    /// Print standalone VEX Python instead of connecting
    #[arg(long, global = true)]
    emit_python: bool,
    /// Machine-readable JSON output
    #[arg(long, global = true)]
    json: bool,
    /// Emit samples/events as JSON Lines, followed by a bounded final result
    #[arg(long, global = true)]
    jsonl: bool,
    /// Which robot to use when several are plugged in (0-based, see `doctor`)
    #[arg(long, global = true)]
    device: Option<usize>,
    /// Connection to use; commands never fall back to another transport
    #[arg(long, global = true, value_enum, default_value_t = Transport::Usb)]
    transport: Transport,
    /// Exact Bluetooth robot name from `bluetooth scan` (for example AIM6518)
    #[arg(long, global = true, conflicts_with = "device")]
    name: Option<String>,
    /// Reuse an agent-managed USB/Bluetooth session; never replay an action implicitly
    #[arg(long, global = true, conflicts_with_all = ["device", "transport"])]
    session: Option<String>,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Clone, Copy, PartialEq, Eq, ValueEnum)]
enum Transport {
    Usb,
    Bluetooth,
}

#[derive(Subcommand)]
enum BluetoothCmd {
    /// List VEX BLE candidates without pairing or executing robot code
    Scan,
    /// Pair the named AIM using masked local input and the native OS credential store
    Pair {
        /// Read the four-digit code from one line of stdin instead of a masked terminal prompt.
        /// Lets an agent pair on a student's behalf; the code is then visible to that agent.
        #[arg(long)]
        code_stdin: bool,
    },
    /// Remove this CLI's stored credential for the named visible robot (does not unpair the robot)
    Forget,
}

const STOP_CODE: &str = "robot.stop_all_movement()\ntry:\n    robot.sound.stop()\nexcept Exception:\n    pass\nwait(400, MSEC)\nprint('stopped', robot.is_stopped())\n";

#[derive(Subcommand)]
enum Cmd {
    /// Manage AIM image/sound slots; requires an owned connection
    Assets {
        kind: String,
        operation: String,
        slot: Option<u8>,
        #[arg(long)]
        file: Option<String>,
        #[arg(long)]
        output: Option<String>,
        #[arg(long)]
        replace: bool,
    },
    /// Discover device commands and their native Python equivalents offline
    Catalog { group: Option<String> },
    /// Read native API availability from the selected robot
    Capabilities {
        #[arg(long)]
        live: bool,
    },
    /// Fresh camera observations for an agent's image reader
    Camera {
        #[command(subcommand)]
        command: CameraCmd,
    },
    /// VEX-style commands; use `catalog GROUP` for parameters and units
    #[command(external_subcommand)]
    Native(Vec<String>),
    /// Agent-facing persistent USB/Bluetooth connection management
    Session {
        #[command(subcommand)]
        command: SessionCmd,
    },
    /// Bounded relative turn; speed defaults to the conservative 30 DPS until hardware validation
    Turn {
        #[arg(value_enum)]
        direction: motion::Direction,
        degrees: f64,
        #[arg(long, default_value_t = 30.0)]
        speed: f64,
    },
    /// Bounded move in millimeters; angle is robot-relative (0 forward, 90 right)
    Move {
        distance: f64,
        #[arg(long, default_value_t = 0.0)]
        angle: f64,
        #[arg(long, default_value_t = 80.0)]
        speed: f64,
    },
    /// Bluetooth discovery and local credential management
    Bluetooth {
        #[command(subcommand)]
        command: BluetoothCmd,
    },
    /// Check the selected connection, REPL and battery; print fixes if something is wrong
    Doctor,
    /// Run Python on the robot. CODE, or -f FILE, or "-" for stdin. State (variables, `robot`) persists between calls.
    Exec {
        code: Option<String>,
        /// Supply one answer per input() call without an interactive terminal
        #[arg(long = "input")]
        inputs: Vec<String>,
        #[arg(short, long)]
        file: Option<String>,
        /// Seconds before the program is interrupted (Ctrl-C)
        #[arg(short, long, default_value_t = 30)]
        timeout: u64,
        /// Do not auto-create `robot = Robot()` (and the vex imports)
        #[arg(long)]
        no_preamble: bool,
    },
    /// Request interruption and stop wheels/sound; needs a working link
    Stop,
    /// Battery, heading, position as JSON
    Info,
    /// Save one native camera JPEG over the selected transport
    Snap {
        /// Output file (default: vexaim-snap-<unix-time>.jpg in the current directory)
        #[arg(short, long)]
        output: Option<String>,
    },
}

#[derive(Subcommand)]
enum SessionCmd {
    /// Start/reuse the named Bluetooth robot or selected USB robot
    Start {
        /// Keep the background connection across chats and idle workshop breaks.
        #[arg(long)]
        persistent: bool,
        /// Replace a running student program on the selected robot, if necessary.
        #[arg(long)]
        takeover: bool,
    },
    /// Read cached connection status without rescanning or touching the robot
    Status,
    /// Stop, disconnect and close the selected session
    Close,
    #[command(hide = true)]
    Serve {
        #[arg(long)]
        id: String,
        #[arg(long)]
        persistent: bool,
        #[arg(long)]
        takeover: bool,
    },
}

#[derive(Subcommand)]
enum CameraCmd {
    /// Save a validated native image with absolute path and control readiness
    Observe {
        #[arg(long, default_value = ".vexaim/captures")]
        output_dir: String,
        #[arg(long)]
        with_detections: bool,
        /// Explicit UVC binding when several AIMs are connected
        #[arg(long)]
        camera_index: Option<u32>,
    },
}

fn out(cli_json: bool, v: serde_json::Value, human: impl FnOnce() -> String) {
    if cli_json {
        println!("{v}")
    } else {
        println!("{}", human())
    }
}

fn run(cli: &Cli) -> Result<i32, Fail> {
    if let Cmd::Catalog { group } = &cli.cmd {
        println!("{}", device::catalog(group.as_deref()));
        return Ok(0);
    }
    if let Cmd::Capabilities { live: false } = cli.cmd {
        println!("{}", device::catalog(None));
        return Ok(0);
    }
    if let Cmd::Native(words) = &cli.cmd {
        let action = device::parse(words, cli.session.is_some())?;
        if action.kind == "host"
            && (cli.emit_python
                || words.iter().any(|w| w == "--emit-python")
                || cli.session.is_none())
        {
            return Err(device::fail(
                "LCD screenshot is a host operation and requires --session; no VEX Python equivalent",
            ));
        }
        if cli.emit_python || words.iter().any(|w| w == "--emit-python") {
            println!(
                "from vex import *\nfrom vex_globals import *\nrobot = Robot()\n{}",
                device::standalone(&action)
            );
            return Ok(0);
        }
    } else if cli.emit_python {
        return Err(device::fail(
            "--emit-python is available for native catalogue commands",
        ));
    }
    if cli.session.is_some() || matches!(cli.cmd, Cmd::Session { .. }) {
        #[cfg(feature = "bluetooth")]
        return session::run(cli);
        #[cfg(not(feature = "bluetooth"))]
        return Err(Fail::Bluetooth(
            "Persistent sessions need a Bluetooth-enabled build.".into(),
        ));
    }
    let bluetooth =
        cli.transport == Transport::Bluetooth || matches!(cli.cmd, Cmd::Bluetooth { .. });
    if bluetooth {
        if cli.device.is_some() {
            return Err(Fail::Bluetooth(
                "--device is a USB index; select Bluetooth with --name NAME.".into(),
            ));
        }
        #[cfg(feature = "bluetooth")]
        return bluetooth::run(cli);
        #[cfg(not(feature = "bluetooth"))]
        return Err(Fail::Bluetooth("This build has no Bluetooth support; install a combined build or rebuild with --features bluetooth.".into()));
    }
    if cli.name.is_some() {
        return Err(Fail::Bluetooth(
            "--name requires --transport bluetooth (or a bluetooth subcommand).".into(),
        ));
    }
    match &cli.cmd {
        Cmd::Assets { .. } => Err(device::fail("Assets require an owned --session")),
        Cmd::Catalog { .. } => unreachable!(),
        Cmd::Capabilities { .. } => run_exec(cli, &device::capability_source(), 30, true),
        Cmd::Native(words) => {
            let a = device::parse(words, false)?;
            run_exec(
                cli,
                &device::standalone(&a),
                a.timeout + device::RESULT_TIMEOUT_SECS,
                true,
            )
        }
        Cmd::Camera { .. } => Err(device::fail(
            "Camera observe requires an owned session; start a USB or Bluetooth session first",
        )),
        Cmd::Session { .. } => unreachable!(),
        Cmd::Turn {
            direction,
            degrees,
            speed,
        } => {
            let source = motion::turn_source(*direction, *degrees, *speed)?;
            run_exec(cli, &format!("{}{source}", motion::helpers()), 23, true)
        }
        Cmd::Move {
            distance,
            angle,
            speed,
        } => {
            let source = motion::move_source(*distance, *angle, *speed)?;
            run_exec(cli, &format!("{}{source}", motion::helpers()), 23, true)
        }
        Cmd::Bluetooth { .. } => unreachable!(),
        Cmd::Doctor => doctor(cli),
        Cmd::Stop => {
            let dev = repl::pick(repl::devices()?, cli.device)?;
            let mut r = Repl::open(&dev)?;
            let res = smol::block_on(async {
                r.sync().await?;
                let x = r
                    .exec(&format!("{PREAMBLE}{STOP_CODE}"), Duration::from_secs(5))
                    .await?;
                r.close().await;
                Ok::<_, Fail>(x)
            })?;
            out(
                cli.json,
                json!({"ok": res.stderr.is_empty(), "stdout": res.stdout, "stderr": res.stderr}),
                || format!("{}{}", res.stdout, res.stderr),
            );
            Ok(if res.stderr.is_empty() { 0 } else { 1 })
        }
        Cmd::Snap { output } => match snap::snap(output.as_deref()) {
            Ok(r) => {
                out(
                    cli.json,
                    json!({"ok": true, "path": r.path, "width": r.width, "height": r.height, "bytes": r.bytes}),
                    || {
                        format!(
                            "saved {} ({}x{}, {} bytes)",
                            r.path, r.width, r.height, r.bytes
                        )
                    },
                );
                Ok(0)
            }
            Err(e) => Err(Fail::Io(format!("camera: {e}"))),
        },
        Cmd::Info => {
            let code = format!(
                "import json\nprint(json.dumps({{'battery_pct': robot.get_battery_level(), 'heading': robot.inertial.get_heading(), 'x_mm': robot.get_x_position(), 'y_mm': robot.get_y_position(), 'stopped': robot.is_stopped()}}))\n"
            );
            run_exec(cli, &code, 10, true)
        }
        Cmd::Exec {
            code,
            inputs,
            file,
            timeout,
            no_preamble,
        } => {
            let src = with_inputs(exec_source(code, file)?, inputs)?;
            run_exec(cli, &src, *timeout, !*no_preamble)
        }
    }
}

fn exec_source(code: &Option<String>, file: &Option<String>) -> Result<String, Fail> {
    match (code, file) {
        (Some(c), None) if c == "-" => {
            let mut s = String::new();
            std::io::stdin()
                .read_to_string(&mut s)
                .map_err(|e| Fail::Io(e.to_string()))?;
            Ok(s)
        }
        (Some(c), None) => Ok(c.clone()),
        (None, Some(f)) => std::fs::read_to_string(f).map_err(|e| Fail::Io(format!("{f}: {e}"))),
        _ => Err(Fail::Io("give CODE, or -f FILE, or '-' for stdin".into())),
    }
}

fn with_inputs(source: String, inputs: &[String]) -> Result<String, Fail> {
    if inputs.is_empty() {
        return Ok(source);
    }
    if inputs.len() > 32 || inputs.iter().any(|s| s.len() > 512) {
        return Err(device::fail("At most 32 input answers of 512 bytes each"));
    }
    Ok(format!(
        "import json as _vx_input_json\n_vx_original_input = input\n_vx_input_answers = iter(_vx_input_json.loads({}))\ndef input(prompt=''):\n    print(prompt, end='')\n    try:\n        return next(_vx_input_answers)\n    except StopIteration:\n        raise RuntimeError('No supplied answer for input(); add --input TEXT')\ntry:\n    exec({})\nfinally:\n    input = _vx_original_input\n",
        serde_json::to_string(&serde_json::to_string(inputs).unwrap()).unwrap(),
        serde_json::to_string(&source).unwrap()
    ))
}

fn run_exec(cli: &Cli, src: &str, timeout: u64, preamble: bool) -> Result<i32, Fail> {
    let dev = repl::pick(repl::devices()?, cli.device)?;
    let mut r = Repl::open(&dev)?;
    let res = smol::block_on(async {
        if preamble {
            // separate call so line numbers in tracebacks match the student's code
            let p = r.exec(PREAMBLE, Duration::from_secs(10)).await?;
            if !p.stderr.is_empty() {
                return Ok::<_, Fail>(p);
            }
        }
        let x = r.exec(src, Duration::from_secs(timeout)).await?;
        r.close().await;
        Ok(x)
    })?;
    Ok(print_exec(cli, &res, timeout))
}

fn print_exec(cli: &Cli, res: &repl::ExecResult, timeout: u64) -> i32 {
    let value = if matches!(cli.cmd, Cmd::Native(_) | Cmd::Capabilities { .. }) {
        serde_json::from_str::<serde_json::Value>(res.stdout.trim()).ok()
    } else {
        None
    };
    let ok = res.stderr.is_empty()
        && !res.timed_out
        && value.as_ref().is_none_or(|v| {
            v["rejected"] != true && v["state"] != "failed" && v["state"] != "cancelled"
        });
    if cli.jsonl {
        device::print_jsonl(
            json!({"ok":ok,"value":value,"stdout":if value.is_none(){Some(&res.stdout)}else{None},"stderr":res.stderr,"timed_out":res.timed_out}),
        );
        return if ok { 0 } else { 1 };
    }
    out(
        cli.json,
        json!({"ok": ok, "stdout": res.stdout, "stderr": res.stderr, "timed_out": res.timed_out, "possible_output_truncation": res.timed_out && res.stdout.len() >= 1500, "elapsed_ms": res.elapsed.as_millis() as u64,"value":value}),
        || {
            let mut s = res.stdout.replace("\r\n", "\n");
            if res.timed_out {
                s.push_str(&format!(
                    "[timed out after {timeout}s: program interrupted]\n"
                ));
                if res.stdout.len() >= 1500 {
                    s.push_str("[hint: the robot's output buffer can overflow when more than ~2 KB is printed in one burst. Print less, or print in chunks with wait(50, MSEC) between them.]\n");
                }
            }
            if !res.stderr.is_empty() {
                s.push_str(&res.stderr.replace("\r\n", "\n"));
            }
            s.trim_end().to_string()
        },
    );
    if ok { 0 } else { 1 }
}

fn doctor(cli: &Cli) -> Result<i32, Fail> {
    let mut checks: Vec<serde_json::Value> = Vec::new();
    let mut ready = true;
    let mut add = |name: &str, ok: bool, detail: String, hint: &str| {
        if !ok {
            ready = false;
        }
        checks.push(
            json!({"check": name, "ok": ok, "detail": detail, "fix": if ok { "" } else { hint }}),
        );
    };
    let devs = match repl::devices() {
        Ok(d) => d,
        Err(e) => {
            add("usb-discovery", false, e.to_string(), "re-plug the cable");
            vec![]
        }
    };
    add(
        "robot-detected",
        !devs.is_empty(),
        format!("{} device(s)", devs.len()),
        "Plug the AIM into this computer with its USB cable (a data cable, not charge-only) and turn the robot on.",
    );
    for (i, d) in devs.iter().enumerate() {
        add(
            &format!("device{i}-ports"),
            d.user_port().is_some(),
            format!(
                "system={} user={}",
                d.system_port().port_info.port_name,
                d.user_port()
                    .map(|u| u.port_info.port_name.clone())
                    .unwrap_or("none".into())
            ),
            "Re-plug the robot. If it persists, the USB interface layout is unexpected: report it.",
        );
    }
    let os = std::env::consts::OS;
    match repl::pick(devs, cli.device) {
        Err(e) => add(
            "device-selection",
            false,
            e.to_string(),
            "Choose a listed --device N when several robots are connected; check that the selected robot is plugged in.",
        ),
        Ok(dev) => match Repl::open(&dev) {
            Err(e) => add("open-ports", false, e.to_string(), repl::open_hint(os)),
            Ok(mut r) => {
                add("open-ports", true, "opened".into(), "");
                let res = smol::block_on(async {
                    let x = r.exec(&format!("{PREAMBLE}import json,sys\nprint(json.dumps({{'battery_pct': robot.get_battery_level(), 'micropython_core': '.'.join(str(n) for n in sys.implementation.version[:3]), 'python_compat': sys.version.split(';')[0]}}))\n"), Duration::from_secs(10)).await;
                    r.close().await;
                    x
                });
                match res {
                    Ok(x) => match validate_status(&x) {
                        Ok(()) => add("repl", true, x.stdout.trim().to_string(), ""),
                        Err(reason) => add(
                            "repl",
                            false,
                            format!("{reason}; stdout={:?}; stderr={:?}", x.stdout, x.stderr),
                            repl::repl_hint(os),
                        ),
                    },
                    Err(e) => add("repl", false, e.to_string(), repl::repl_hint(os)),
                }
            }
        },
    }
    let verdict = if ready { "ready" } else { "not ready" };
    if cli.json {
        println!("{}", json!({"verdict": verdict, "checks": checks}));
    } else {
        for c in &checks {
            println!(
                "[{}] {}: {}",
                if c["ok"] == true { "ok" } else { "FAIL" },
                c["check"].as_str().unwrap(),
                c["detail"].as_str().unwrap()
            );
            if c["ok"] == false {
                println!("       fix: {}", c["fix"].as_str().unwrap());
            }
        }
        println!("verdict: {verdict}");
    }
    Ok(if ready { 0 } else { 1 })
}

fn validate_status(result: &repl::ExecResult) -> Result<(), &'static str> {
    if result.timed_out {
        return Err("REPL status query timed out");
    }
    if !result.stderr.is_empty() {
        return Err("Python status query failed");
    }
    let value: serde_json::Value = serde_json::from_str(result.stdout.trim())
        .map_err(|_| "REPL did not return a JSON status object")?;
    if !value["battery_pct"]
        .as_f64()
        .is_some_and(|b| (0.0..=100.0).contains(&b))
    {
        return Err("REPL status has no valid battery percentage");
    }
    for key in ["micropython_core", "python_compat"] {
        if !value[key].as_str().is_some_and(|s| !s.trim().is_empty()) {
            return Err("REPL status is missing interpreter versions");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bluetooth_is_explicit_and_never_uses_usb_indices_or_pin_arguments() {
        let cli = Cli::try_parse_from(["vexaim", "info"]).unwrap();
        assert!(cli.transport == Transport::Usb);
        let cli = Cli::try_parse_from([
            "vexaim",
            "--transport",
            "bluetooth",
            "--name",
            "AIM6518",
            "snap",
        ])
        .unwrap();
        assert!(cli.transport == Transport::Bluetooth);
        assert!(
            Cli::try_parse_from(["vexaim", "--name", "AIM6518", "--device", "0", "info"]).is_err()
        );
        assert!(Cli::try_parse_from(["vexaim", "bluetooth", "pair", "--pin", "1234"]).is_err());
        assert!(
            Cli::try_parse_from([
                "vexaim",
                "--session",
                "aim-0000000000000000",
                "--transport",
                "usb",
                "info"
            ])
            .is_err()
        );
        let turn = Cli::try_parse_from([
            "vexaim",
            "--session",
            "aim-0000000000000000",
            "turn",
            "left",
            "360",
        ])
        .unwrap();
        assert!(matches!(
            turn.cmd,
            Cmd::Turn {
                degrees: 360.0,
                speed: 30.0,
                ..
            }
        ));
    }

    #[test]
    fn readiness_requires_a_complete_successful_status_response() {
        let mut result = repl::ExecResult {
            upload_elapsed: Duration::ZERO,
            stdout: String::new(),
            stderr: String::new(),
            timed_out: false,
            elapsed: Duration::ZERO,
        };
        for invalid in [
            "",
            "hello",
            "{}",
            "{\"battery_pct\":101}",
            "{\"battery_pct\":50}",
        ] {
            result.stdout = invalid.into();
            assert!(validate_status(&result).is_err());
        }
        result.stdout =
            r#"{"battery_pct":100,"micropython_core":"1.22.0","python_compat":"3.4.0"}"#.into();
        assert!(validate_status(&result).is_ok());
        let valid: serde_json::Value = serde_json::from_str(&result.stdout).unwrap();
        for battery in [json!(-1), json!(101), json!("100"), json!(null)] {
            let mut invalid = valid.clone();
            invalid["battery_pct"] = battery;
            result.stdout = invalid.to_string();
            assert!(validate_status(&result).is_err());
        }
        for key in ["micropython_core", "python_compat"] {
            let mut invalid = valid.clone();
            invalid[key] = json!("");
            result.stdout = invalid.to_string();
            assert!(validate_status(&result).is_err());
        }
        result.stdout = valid.to_string();
        result.timed_out = true;
        assert!(validate_status(&result).is_err());
        result.timed_out = false;
        result.stderr = "Traceback: failed".into();
        assert!(validate_status(&result).is_err());
    }
}

fn main() {
    let mut cli = Cli::parse();
    if cli.jsonl {
        cli.json = true;
    }
    match run(&cli) {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            if cli.json {
                println!("{}", json!({"ok": false, "error": e.to_string()}))
            } else {
                eprintln!("error: {e}")
            }
            std::process::exit(2);
        }
    }
}
#[cfg(all(test, feature = "bluetooth"))]
#[path = "../../../dev/aim-idle-rust.rs"]
mod aim_idle_probe;
#[cfg(all(test, feature = "bluetooth"))]
#[path = "../../../dev/aim-lifecycle-rust.rs"]
mod aim_lifecycle_probe;
