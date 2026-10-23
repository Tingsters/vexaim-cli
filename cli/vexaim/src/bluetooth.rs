//! Explicit BLE selection, native credential storage and the verified AIM JPEG path.
use crate::camera_capture::{CaptureTransport, Options as CaptureOptions, Trace as CaptureTrace};
use crate::{
    BluetoothCmd, Cli, Cmd, out, print_exec,
    repl::{Fail, PREAMBLE, Repl},
    snap::Snap,
};
use btleplug::api::Peripheral as _;
use serde_json::json;
use std::{
    io::{IsTerminal, Write},
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;
use vex_v5_serial::{
    Connection,
    bluetooth::{self, BluetoothConnection, BluetoothDevice},
    protocol::{
        Version,
        cdc2::{
            file::*,
            system::{ScreenCapturePacket, SystemStatusPacket},
        },
    },
};

const SERVICE: &str = "vexaim.bluetooth";
const STATE: &str = "import json\nprint(json.dumps({'battery_pct':robot.get_battery_level(),'heading':robot.inertial.get_heading(),'x_mm':robot.get_x_position(),'y_mm':robot.get_y_position(),'stopped':robot.is_stopped()}))\n";
const STATUS: &str = "import json,sys\nprint(json.dumps({'battery_pct':robot.get_battery_level(),'micropython_core':'.'.join(str(n) for n in sys.implementation.version[:3]),'python_compat':sys.version.split(';')[0]}))\n";
const HINT: &str = "Check robot power and Bluetooth, keep VEXcode closed, select the exact --name, and run `vexaim --name NAME bluetooth pair` in a local terminal if authentication is needed. No USB reconnect is required for Bluetooth. A stop command also needs a working link.";

fn fail(message: impl Into<String>) -> Fail {
    Fail::Bluetooth(message.into())
}
fn io(error: impl std::fmt::Display) -> Fail {
    fail(error.to_string())
}

fn decode_pin(code: &str) -> Result<[u8; 4], Fail> {
    let bytes = code.as_bytes();
    if bytes.len() != 4 || !bytes.iter().all(u8::is_ascii_digit) {
        return Err(fail(
            "Enter exactly four digits; never put the code in command arguments.",
        ));
    }
    Ok([
        bytes[0] - b'0',
        bytes[1] - b'0',
        bytes[2] - b'0',
        bytes[3] - b'0',
    ])
}

fn entry(id: &str) -> Result<keyring::Entry, Fail> {
    keyring::Entry::new(SERVICE, id).map_err(|_| {
        fail("Cannot open the native credential store; no plaintext fallback is used.")
    })
}

fn saved_code(id: &str) -> Result<Option<String>, Fail> {
    match entry(id)?.get_password() {
        Ok(code) => return Ok(Some(code)),
        Err(keyring::Error::NoEntry) => {}
        Err(_) => {
            return Err(fail(
                "Cannot read the native credential store. Unlock it and retry; no plaintext fallback is used.",
            ));
        }
    }
    // The instructor Python probe used Python keyring's Windows target mapping.
    // Verify its username before reading, then migrate only after authentication.
    #[cfg(windows)]
    for target in [SERVICE.to_string(), format!("{id}@{SERVICE}")] {
        let legacy = keyring::Entry::new_with_target(&target, SERVICE, id)
            .map_err(|_| fail("Cannot open the legacy native credential entry."))?;
        match legacy.get_attributes() {
            Ok(attributes)
                if attributes
                    .get("username")
                    .is_some_and(|u| u.eq_ignore_ascii_case(id)) =>
            {
                return legacy
                    .get_password()
                    .map(Some)
                    .map_err(|_| fail("Cannot read the legacy native credential entry."));
            }
            Ok(_) | Err(keyring::Error::NoEntry) => {}
            Err(_) => return Err(fail("Cannot inspect the legacy native credential entry.")),
        }
    }
    Ok(None)
}

fn forget_code(id: &str) -> Result<(), Fail> {
    match entry(id)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(_) => return Err(fail("Cannot remove the native credential entry.")),
    }
    #[cfg(windows)]
    for target in [SERVICE.to_string(), format!("{id}@{SERVICE}")] {
        let legacy = keyring::Entry::new_with_target(&target, SERVICE, id)
            .map_err(|_| fail("Cannot open the legacy native credential entry."))?;
        match legacy.get_attributes() {
            Ok(attributes)
                if attributes
                    .get("username")
                    .is_some_and(|u| u.eq_ignore_ascii_case(id)) =>
            {
                legacy
                    .delete_credential()
                    .map_err(|_| fail("Cannot remove the legacy native credential entry."))?;
            }
            Ok(_) | Err(keyring::Error::NoEntry) => {}
            Err(_) => return Err(fail("Cannot inspect the legacy native credential entry.")),
        }
    }
    Ok(())
}

async fn candidates() -> Result<Vec<(String, String, BluetoothDevice)>, Fail> {
    let devices = bluetooth::find_devices(Duration::from_secs(8), None)
        .await
        .map_err(io)?;
    let mut result = Vec::new();
    for device in devices {
        let properties = device.0.properties().await.map_err(io)?;
        let name = properties.and_then(|p| p.local_name).unwrap_or_default();
        // CoreBluetooth does not expose a MAC address; its peripheral UUID is
        // the stable credential identity. Windows/Linux keep the address mapping
        // used by the instructor probe.
        #[cfg(target_os = "macos")]
        let id = device.0.id().to_string();
        #[cfg(not(target_os = "macos"))]
        let id = device.0.address().to_string();
        result.push((name, id, device));
    }
    result.sort_by(|a, b| a.1.cmp(&b.1));
    Ok(result)
}

pub(crate) async fn select(name: &str) -> Result<(String, BluetoothDevice), Fail> {
    let mut matches: Vec<_> = candidates()
        .await?
        .into_iter()
        .filter(|(n, _, _)| n == name)
        .collect();
    if matches.len() != 1 {
        return Err(fail(format!(
            "Expected exactly one robot named {name}; found {}. Check power and use `vexaim bluetooth scan`. No command was sent.",
            matches.len()
        )));
    }
    let (_, id, device) = matches.remove(0);
    Ok((id, device))
}

pub(crate) async fn identity(conn: &BluetoothConnection) -> Result<serde_json::Value, Fail> {
    let mut info = json!({});
    for (key, short) in [
        ("model", "2a24"),
        ("firmware", "2a26"),
        ("hardware", "2a27"),
    ] {
        let uuid = Uuid::parse_str(&format!("0000{short}-0000-1000-8000-00805f9b34fb")).unwrap();
        let characteristic = conn
            .peripheral
            .characteristics()
            .into_iter()
            .find(|c| c.uuid == uuid)
            .ok_or_else(|| fail("Selected device lacks AIM Device Information."))?;
        let bytes = tokio::time::timeout(
            Duration::from_secs(5),
            conn.peripheral.read(&characteristic),
        )
        .await
        .map_err(|_| fail("Timed out reading AIM identity."))?
        .map_err(io)?;
        info[key] = String::from_utf8(bytes)
            .map_err(|_| fail("Invalid AIM identity response."))?
            .trim_end_matches('\0')
            .into();
    }
    if info["model"] != "AIM" {
        return Err(fail(
            "Selected device does not identify as a VEX AIM; no Python or camera command was sent.",
        ));
    }
    // Preserve the original field: on AIM, 2a26 is a separate application
    // revision (VEXcode calls it appVersion2), not necessarily the VEXos release.
    info["gatt_firmware_revision"] = info["firmware"].clone();
    info["gatt_software_revision"] = serde_json::Value::Null;
    let software_uuid = Uuid::from_u128(0x00002a28_0000_1000_8000_00805f9b34fb);
    if let Some(characteristic) = conn
        .peripheral
        .characteristics()
        .into_iter()
        .find(|c| c.uuid == software_uuid)
    {
        match tokio::time::timeout(
            Duration::from_secs(2),
            conn.peripheral.read(&characteristic),
        )
        .await
        {
            Ok(Ok(bytes)) => match String::from_utf8(bytes) {
                Ok(value) => info["gatt_software_revision"] = json!(value.trim_end_matches('\0')),
                Err(_) => {
                    info["software_revision_error"] =
                        json!("Invalid UTF-8 in optional GATT software revision")
                }
            },
            _ => {
                info["software_revision_error"] =
                    json!("Optional GATT software revision unavailable")
            }
        }
    }
    Ok(info)
}

fn version_text(version: Version) -> String {
    format!(
        "{}.{}.{}.b{}",
        version.major, version.minor, version.build, version.beta
    )
}

/// One source-defined SYS_STATUS read, after authentication; never a firmware write.
pub(crate) async fn add_system_versions<C: Connection>(conn: &mut C, info: &mut serde_json::Value) {
    for key in ["vexos_version", "cpu0_version", "cpu1_version"] {
        info[key] = serde_json::Value::Null;
    }
    match conn
        .handshake(SystemStatusPacket {}, Duration::from_secs(2), 0)
        .await
    {
        Ok(Ok(reply)) => {
            info["vexos_version"] = reply
                .system_version
                .map(version_text)
                .map_or(serde_json::Value::Null, |v| json!(v));
            info["cpu0_version"] = json!(version_text(reply.cpu0_version));
            info["cpu1_version"] = json!(version_text(reply.cpu1_version));
        }
        _ => info["system_versions_error"] = json!("Optional AIM system version read unavailable"),
    }
}

/// Read the pairing code from the first line of `input` (used by `pair --code-stdin`).
fn read_code_line(mut input: impl std::io::BufRead) -> Result<String, Fail> {
    let mut line = String::new();
    input
        .read_line(&mut line)
        .map_err(|_| fail("Reading the code failed; no credential was saved."))?;
    Ok(line.trim().to_string())
}

pub(crate) async fn authenticate(
    conn: &mut BluetoothConnection,
    id: &str,
    pair: bool,
    code_stdin: bool,
) -> Result<(), Fail> {
    if !pair {
        let code = saved_code(id)?.ok_or_else(|| {
            Fail::AuthenticationRequired(
                "Authentication is required on this computer; pair the selected robot once.".into(),
            )
        })?;
        let pin = decode_pin(&code)?;
        if conn.is_paired().await.map_err(io)? {
            return verify_owner(conn, id).await;
        }
        conn.authenticate_pairing(pin).await.map_err(|_| Fail::AuthenticationRequired(
            "Stored authentication was rejected. Automatic reconnect is paused; pair explicitly to claim this robot. No credential was erased.".into()))?;
        return Ok(());
    }
    let code = if pair && code_stdin {
        conn.request_pairing().await.map_err(io)?;
        eprintln!("Read the four-digit code on the selected robot's LCD and send it on stdin.");
        tokio::time::timeout(
            Duration::from_secs(120),
            tokio::task::spawn_blocking(|| read_code_line(std::io::stdin().lock())),
        )
        .await
        .map_err(|_| fail("Pairing input timed out; no credential was saved."))?
        .map_err(|_| fail("Reading the code failed; no credential was saved."))??
    } else if pair {
        if !std::io::stdin().is_terminal() || !std::io::stderr().is_terminal() {
            return Err(fail(
                "Pairing needs a local interactive terminal with masked input. Run `vexaim --name NAME bluetooth pair` there; do not send the code in chat.",
            ));
        }
        conn.request_pairing().await.map_err(io)?;
        eprintln!("Read the four-digit code on the selected robot's LCD.");
        tokio::time::timeout(
            Duration::from_secs(120),
            tokio::task::spawn_blocking(|| rpassword::prompt_password("Robot code (hidden): ")),
        )
        .await
        .map_err(|_| fail("Pairing input timed out; no credential was saved."))?
        .map_err(|_| fail("Masked input failed; no credential was saved."))?
        .map_err(|_| fail("Masked input failed; no credential was saved."))?
    } else {
        saved_code(id)?.ok_or_else(|| fail("VEX authentication required. Run `vexaim --name NAME bluetooth pair` locally first."))?
    };
    let pin = decode_pin(&code)?;
    conn.authenticate_pairing(pin).await.map_err(|_| fail("Robot rejected the code or authentication failed; no credential was saved. Pair again locally."))?;
    entry(id)?.set_password(&code).map_err(|_| fail("Robot accepted the code, but the native credential store could not save it. Unlock the store and pair again."))?;
    Ok(())
}

/// Read-only ownership evidence. A changed application code must never be
/// overwritten by a background reconnect from the previous computer.
pub(crate) async fn verify_owner(conn: &BluetoothConnection, id: &str) -> Result<(), Fail> {
    let code = saved_code(id)?.ok_or_else(|| {
        Fail::AuthenticationRequired(
            "No saved credential for this robot; automatic reconnect is paused.".into(),
        )
    })?;
    let expected = decode_pin(&code)?;
    let actual = tokio::time::timeout(Duration::from_secs(5), conn.peripheral.read(&conn.pairing))
        .await
        .map_err(|_| fail("Authentication read timed out"))?
        .map_err(io)?;
    if actual != expected {
        return Err(Fail::AuthenticationRequired(
            "Robot authentication changed or was released. Automatic reconnect is paused to allow handoff; saved credentials were retained.".into()));
    }
    Ok(())
}
pub(crate) fn authentication_required(error: &Fail) -> bool {
    matches!(error, Fail::AuthenticationRequired(_))
}

pub fn run(cli: &Cli) -> Result<i32, Fail> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(io)?;
    let result = runtime.block_on(async {
        if matches!(cli.cmd, Cmd::Bluetooth { command: BluetoothCmd::Scan }) {
            let devices: Vec<_> = candidates().await?.into_iter().map(|(name,id,_)| json!({"name":name,"id":id,"identity_verified":false})).collect();
            out(cli.json, json!({"ok":true,"transport":"bluetooth","devices":devices}), || devices.iter().map(|d| format!("{}  {}", d["name"].as_str().unwrap(), d["id"].as_str().unwrap())).collect::<Vec<_>>().join("\n"));
            return Ok(0);
        }
        let name = cli.name.as_deref().ok_or_else(|| fail("Select the robot explicitly with --name NAME (see `vexaim bluetooth scan`)."))?;
        crate::session::guard_one_shot(name).await?;
        let (id, device) = select(name).await?;
        if matches!(cli.cmd, Cmd::Bluetooth { command: BluetoothCmd::Forget }) {
            forget_code(&id)?;
            out(cli.json, json!({"ok":true,"credential_removed":true,"id":id}), || format!("Removed the CLI's saved credential for {name}. Robot pairing was not changed."));
            return Ok(0);
        }
        let mut conn = device.connect().await.map_err(io)?;
        let operation = async {
            let info = identity(&conn).await?;
            let pair = matches!(cli.cmd, Cmd::Bluetooth { command: BluetoothCmd::Pair { .. } });
            let code_stdin = matches!(cli.cmd, Cmd::Bluetooth { command: BluetoothCmd::Pair { code_stdin: true } });
            authenticate(&mut conn, &id, pair, code_stdin).await?;
            if pair {
                out(cli.json, json!({"ok":true,"transport":"bluetooth","name":name,"id":id,"credential_saved":true}), || format!("Paired {name}; credential saved in the native OS store."));
                return Ok(0);
            }
            if let Cmd::Snap { output } = &cli.cmd {
                require_camera_firmware(&info)?;
                let parameters = crate::ble_profile::Profile::selected()?.apply(&conn.peripheral).await;
                let started = Instant::now();
                let image = tokio::time::timeout(Duration::from_secs(CAPTURE_GUARD_SECS), capture_jpeg(&mut conn)).await.map_err(|_| fail("Camera capture timed out; existing output was preserved."))??;
                let (width,height) = crate::observation::validate(&image)?;
                let path = crate::snap::output_path(output.as_deref());
                save_atomic(Path::new(&path), &image)?;
                let elapsed = started.elapsed();
                let result = Snap { path, width, height, bytes:image.len() };
                let interval_us = tokio::time::timeout(Duration::from_secs(2), conn.peripheral.connection_parameters()).await.ok().and_then(Result::ok).flatten().map(|p|p.interval_us);
                out(cli.json, json!({"ok":true,"transport":"bluetooth","path":result.path,"width":width,"height":height,"bytes":result.bytes,"elapsed_ms":elapsed.as_millis() as u64,"within_30_seconds":elapsed<=Duration::from_secs(30),"throughput_request_accepted":parameters["requested"]=="throughput" && parameters["accepted"]==true,"connection_parameters":parameters,"connection_interval_us":interval_us}), || format!("saved {} ({}x{}, {} bytes, {:.2}s over Bluetooth)",result.path,width,height,result.bytes,elapsed.as_secs_f64()));
                return Ok(0);
            }
            // Borrow the connection through the operation so explicit disconnect runs
            // after both success and failure; both notification streams stay active.
            run_python(cli, &mut conn, &info).await
        }.await;
        let cleanup = conn.close().await.map_err(io);
        match operation { Err(error) => Err(error), Ok(code) => { cleanup?; Ok(code) } }
    });
    runtime.shutdown_timeout(Duration::from_millis(100));
    if matches!(cli.cmd, Cmd::Doctor) {
        if let Err(error) = &result {
            out(
                cli.json,
                json!({"verdict":"not ready","transport":"bluetooth","checks":[{"check":"bluetooth","ok":false,"detail":error.to_string(),"fix":HINT}]}),
                || format!("[FAIL] bluetooth: {error}\n       fix: {HINT}\nverdict: not ready"),
            );
            return Ok(1);
        }
    }
    result
}

// Repl is generic over Connection; a small forwarding implementation lets the
// BLE owner retain responsibility for disconnect on every return path.
async fn run_python(
    cli: &Cli,
    conn: &mut BluetoothConnection,
    info: &serde_json::Value,
) -> Result<i32, Fail> {
    let mut repl = Repl::from_connection(crate::display::DisplayConnection::new(conn));
    let operation = async {
        let (source, timeout, preamble) = match &cli.cmd {
            Cmd::Doctor => (STATUS.to_string(),10,true),
            Cmd::Info => (STATE.to_string(),10,true),
            Cmd::Stop => (crate::STOP_CODE.to_string(),5,true),
            Cmd::Exec { code,inputs,file,timeout,no_preamble,behaviors } => {
                let source = crate::with_inputs(crate::exec_source(code,file)?,inputs)?;
                let source = if *behaviors {format!("{}\n{}\n{}", crate::device::RUNTIME, crate::device::BEHAVIORS, crate::device::behavior_exec(&source, *timeout))} else {source};
                (source,*timeout,!*no_preamble)
            },
            Cmd::Turn { direction, degrees, speed } => (format!("{}{}", crate::motion::helpers(), crate::motion::turn_source(*direction, *degrees, *speed)?), 23, true),
            Cmd::Move { distance, angle, speed } => (format!("{}{}", crate::motion::helpers(), crate::motion::move_source(*distance, *angle, *speed)?), 23, true),
            Cmd::Capabilities {..} => (crate::device::capability_source(),30,true),
            Cmd::Native(words) => { let a=crate::device::parse(words,false)?; (crate::device::standalone(&a),a.timeout+crate::device::RESULT_TIMEOUT_SECS,true) },
            _ => return Err(fail("Unsupported Bluetooth command.")),
        };
        if preamble {
            let setup = repl.exec(PREAMBLE,Duration::from_secs(10)).await?;
            if setup.timed_out || !setup.stderr.is_empty() { return Err(fail("Python robot initialization failed or timed out.")); }
        }
        let display = (preamble && matches!(cli.cmd, Cmd::Exec {..}) && crate::display::program_uses_display(&source)) || matches!(&cli.cmd, Cmd::Native(words) if words.first().is_some_and(|w|w=="screen") && crate::device::parse(words,false).is_ok_and(|a|a.kind!="read"));
        if display {
            let state=repl.exec(STATE,Duration::from_secs(5)).await?;
            if state.timed_out || !state.stderr.is_empty() || serde_json::from_str::<serde_json::Value>(state.stdout.trim()).map_err(io)?["stopped"]!=true {
                return Err(fail("Finish movement before the first display program"));
            }
            repl.connection_mut().enable(info).await?;
        }
        let result = repl.exec(&source,Duration::from_secs(timeout)).await?;
        if matches!(cli.cmd,Cmd::Doctor) {
            crate::validate_status(&result).map_err(fail)?;
            out(cli.json,json!({"verdict":"ready","transport":"bluetooth","device_info":info,"checks":[{"check":"repl","ok":true,"detail":result.stdout.trim(),"fix":""}]}),||format!("[ok] Bluetooth authentication and REPL: {}\nverdict: ready",result.stdout.trim()));
            return Ok(0);
        }
        Ok(print_exec(cli,&result,timeout))
    }.await;
    let cleanup = repl.connection_mut().disable().await.map_err(io);
    repl.close().await;
    cleanup?;
    operation
}

pub(crate) fn known_aim_profile(info: &serde_json::Value) -> bool {
    info["model"] == "AIM"
        && info["hardware"] == "REV1"
        && matches!(info["firmware"].as_str(), Some("1.0.0.b0" | "1.0.4.b0"))
}

pub(crate) fn require_camera_firmware(info: &serde_json::Value) -> Result<(), Fail> {
    if !known_aim_profile(info) {
        return Err(fail(
            "Native Bluetooth JPEG capture supports only AIM REV1 / BLE firmware 1.0.0.b0 or 1.0.4.b0; no menu/reset fallback was attempted.",
        ));
    }
    Ok(())
}

pub(crate) async fn capture_jpeg<C: CaptureTransport>(conn: &mut C) -> Result<Vec<u8>, Fail> {
    capture_buffer(conn, Some(8), true).await
}

// At the observed Windows default interval, ~21 KiB takes ~36 seconds.
// The fixed 115200-byte LCD buffer therefore needs minutes, not 55 seconds.
// Keep nested guards ordered and every transfer finite, including complex JPEGs.
pub(crate) const CAPTURE_TRANSFER_SECS: u64 = 240;
pub(crate) const CAPTURE_GUARD_SECS: u64 = 250;
pub(crate) const CAPTURE_REQUEST_SECS: u64 = 300;
pub(crate) const CAPTURE_CLIENT_SECS: u64 = 330;

pub(crate) async fn capture_lcd<C: CaptureTransport>(conn: &mut C) -> Result<Vec<u8>, Fail> {
    capture_buffer(conn, None, false).await
}

async fn capture_buffer<C: CaptureTransport>(
    conn: &mut C,
    layer: Option<u8>,
    jpeg: bool,
) -> Result<Vec<u8>, Fail> {
    let options = CaptureOptions::selected()?;
    let mut trace = CaptureTrace::new(&options, conn.capture_metrics());
    let result = capture_buffer_inner(conn, layer, jpeg, &options, &mut trace).await;
    trace.finish(result.is_ok(), conn.capture_metrics());
    result
}

async fn capture_buffer_inner<C: CaptureTransport>(
    conn: &mut C,
    layer: Option<u8>,
    jpeg: bool,
    options: &CaptureOptions,
    trace: &mut CaptureTrace,
) -> Result<Vec<u8>, Fail> {
    let setup = Instant::now();
    conn.handshake(ScreenCapturePacket { layer }, Duration::from_secs(3), 0)
        .await
        .map_err(io)?
        .map_err(io)?;
    let init = conn
        .handshake(
            FileTransferInitializePacket {
                operation: FileTransferOperation::Read,
                target: FileTransferTarget::Cbuf,
                vendor: FileVendor::Sys,
                options: FileTransferOptions::None,
                file_size: 512 * 272 * 4,
                load_address: 0,
                write_file_crc: 0,
                metadata: FileMetadata {
                    extension: "ini".try_into().unwrap(),
                    extension_type: ExtensionType::EncryptedBinary,
                    timestamp: 0,
                    version: Version {
                        major: 0,
                        minor: 0,
                        build: 0,
                        beta: 0,
                    },
                },
                file_name: "screen".try_into().unwrap(),
            },
            Duration::from_secs(3),
            0,
        )
        .await
        .map_err(io)?
        .map_err(io)?;
    let size = init.file_size as usize;
    if size == 0 || size > 1024 * 1024 {
        return Err(fail("Camera buffer is empty or exceeds the 1 MiB limit."));
    }
    if !jpeg && size != 240 * 240 * 2 {
        return Err(fail(
            "Unsupported AIM LCD buffer layout; expected 240x240 RGB565, no alternate layer was tried",
        ));
    }
    let chunk = if options.payload_window {
        // The official AIM BLE uploader treats the advertised window as payload,
        // capped at 232 bytes; 232 data + reply framing fits its 244-byte packet.
        usize::from(init.window_size).min(232) / 4 * 4
    } else {
        usize::from(init.window_size.saturating_sub(14)).min(216) / 4 * 4
    };
    if chunk == 0 {
        return Err(fail("Camera receive window is too small."));
    }
    trace.report["setup_ms"] = json!(setup.elapsed().as_millis() as u64);
    trace.report["buffer_bytes"] = json!(size);
    trace.report["block_bytes"] = json!(chunk);
    let deadline = Instant::now() + options.transfer_timeout;
    let authorization = if options.operation_auth {
        tokio::time::timeout(
            deadline.saturating_duration_since(Instant::now()),
            conn.authorize_capture(),
        )
        .await
        .map_err(|_| fail("Camera authentication exceeded the transfer deadline"))?
        .map_err(io)?
        .map(|authorization| {
            if options.reply_pacing {
                authorization.with_reply_pacing()
            } else {
                authorization
            }
        })
    } else {
        None
    };
    let mut bytes = Vec::with_capacity(size);
    while bytes.len() < size {
        if Instant::now() >= deadline {
            return Err(fail(format!(
                "{} transfer exceeded {} seconds; existing output was preserved.",
                if jpeg { "Camera" } else { "LCD" },
                options.transfer_timeout.as_secs_f64()
            )));
        }
        let requested = if bytes.is_empty() {
            128.min(chunk)
        } else {
            chunk
        }
        .min((size - bytes.len()).div_ceil(4) * 4);
        let address = bytes.len() as u32;
        let began = Instant::now();
        let budget = options
            .block_timeout
            .min(deadline.saturating_duration_since(Instant::now()));
        let operation = async {
            conn.send_capture_read(
                FileDataReadPacket {
                    address,
                    size: requested as u16,
                },
                authorization.as_ref(),
            )
            .await
            .map_err(io)?;
            conn.recv::<Result<FileDataReadReplyPacket, vex_v5_serial::protocol::cdc2::Cdc2Ack>>(
                budget,
            )
            .await
            .map_err(io)?
            .map_err(io)
        };
        let reply = if options.diagnostic {
            tokio::time::timeout(budget, operation).await.map_err(|_| fail("Camera block made no progress before its finite deadline; interrupted capture must not be reused"))??
        } else {
            // Normal commands retain their existing write and per-reply deadlines.
            operation.await?
        };
        append_block(&mut bytes, size, address, requested, &reply)?;
        trace.report["blocks"] = json!(trace.report["blocks"].as_u64().unwrap_or(0) + 1);
        trace.report["bytes_received"] = json!(bytes.len());
        trace.report["block_ms"]
            .as_array_mut()
            .unwrap()
            .push(json!(began.elapsed().as_micros() as f64 / 1000.));
        if jpeg && address == 0 && !bytes.starts_with(&[0xff, 0xd8]) {
            return Err(fail(
                "Camera layer did not return JPEG; no other layer or menu action was attempted.",
            ));
        }
    }
    tokio::time::timeout(
        deadline.saturating_duration_since(Instant::now()),
        conn.verify_capture(authorization),
    )
    .await
    .map_err(|_| fail("Camera final authentication exceeded the transfer deadline"))?
    .map_err(io)?;
    let validation = Instant::now();
    if jpeg {
        jpeg_dimensions(&bytes)?;
    }
    trace.report["validation_ms"] = json!(validation.elapsed().as_micros() as f64 / 1000.);
    // Read-only downloads have no FILE_EXIT/program-upload completion command.
    Ok(bytes)
}

fn append_block(
    bytes: &mut Vec<u8>,
    total: usize,
    address: u32,
    requested: usize,
    reply: &FileDataReadReplyPacket,
) -> Result<(), Fail> {
    let remaining = total.saturating_sub(bytes.len());
    let needed = requested.min(remaining);
    if reply.address != address
        || address as usize != bytes.len()
        || reply.data.len() < needed
        || reply.data.len() > requested
        || needed == 0
    {
        return Err(fail(
            "Camera block address/length mismatch; output was not replaced.",
        ));
    }
    bytes.extend_from_slice(&reply.data[..needed]);
    Ok(())
}

pub(crate) fn jpeg_dimensions(bytes: &[u8]) -> Result<(u32, u32), Fail> {
    let bad = || fail("Incomplete or invalid native JPEG; output was not replaced.");
    if !bytes.starts_with(&[0xff, 0xd8]) || !bytes.ends_with(&[0xff, 0xd9]) {
        return Err(bad());
    }
    let mut cursor = 2;
    while cursor + 4 <= bytes.len() {
        if bytes[cursor] != 0xff {
            break;
        }
        while cursor < bytes.len() && bytes[cursor] == 0xff {
            cursor += 1;
        }
        let marker = *bytes.get(cursor).ok_or_else(bad)?;
        cursor += 1;
        if marker == 0xda || marker == 0xd9 {
            break;
        }
        if cursor + 2 > bytes.len() {
            break;
        }
        let length = u16::from_be_bytes([bytes[cursor], bytes[cursor + 1]]) as usize;
        if length < 2 || cursor + length > bytes.len() {
            break;
        }
        if (0xc0..=0xcf).contains(&marker) && ![0xc4, 0xc8, 0xcc].contains(&marker) {
            if length < 8 {
                break;
            }
            let height = u16::from_be_bytes([bytes[cursor + 3], bytes[cursor + 4]]) as u32;
            let width = u16::from_be_bytes([bytes[cursor + 5], bytes[cursor + 6]]) as u32;
            if (width, height) != (640, 480) {
                return Err(fail(
                    "Unsupported native camera dimensions; expected the verified 640x480 JPEG.",
                ));
            }
            return Ok((width, height));
        }
        cursor += length;
    }
    Err(bad())
}

pub(crate) fn save_atomic(path: &Path, bytes: &[u8]) -> Result<(), Fail> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent).map_err(io)?;
    let mut staged = tempfile::NamedTempFile::new_in(parent).map_err(io)?;
    staged.write_all(bytes).map_err(io)?;
    staged.persist(path).map_err(|_| {
        fail("Could not atomically replace the JPEG destination; previous output was preserved.")
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use vex_v5_serial::{
        ConnectionType,
        bluetooth::{BluetoothError, BluetoothIoMetrics, FileReadAuthorization},
        protocol::{
            cdc::{CdcCommand, CdcReply},
            cdc2::file::FileDataReadPacket,
        },
    };

    struct CaptureFake {
        command: Vec<u8>,
        reads: usize,
        begun: usize,
        verified: usize,
        fail_verification: bool,
        stall: bool,
        corrupt: bool,
        stall_authorization: bool,
        stall_final_auth: bool,
        image: Vec<u8>,
        read_sizes: Vec<usize>,
    }
    impl CaptureFake {
        fn new() -> Self {
            Self {
                command: vec![],
                reads: 0,
                begun: 0,
                verified: 0,
                fail_verification: false,
                stall: false,
                corrupt: false,
                stall_authorization: false,
                stall_final_auth: false,
                image: vec![
                    0xff, 0xd8, 0xff, 0xc0, 0, 11, 8, 1, 224, 2, 128, 1, 1, 0x11, 0, 0, 0xff, 0xd9,
                ],
                read_sizes: vec![],
            }
        }
        fn frame(&self, ecmd: u8, payload: &[u8]) -> Vec<u8> {
            let size = payload.len() + 3;
            let mut bytes = vec![0xaa, 0x55, 0x56];
            if size > 127 {
                bytes.extend([0x80 | (size >> 8) as u8, size as u8]);
            } else {
                bytes.push(size as u8);
            }
            bytes.push(ecmd);
            bytes.extend(payload);
            let mut crc = 0_u16;
            for byte in &bytes {
                crc ^= (*byte as u16) << 8;
                for _ in 0..8 {
                    crc = if crc & 0x8000 != 0 {
                        (crc << 1) ^ 0x1021
                    } else {
                        crc << 1
                    };
                }
            }
            bytes.extend(crc.to_be_bytes());
            bytes
        }
    }
    impl Connection for CaptureFake {
        type Error = BluetoothError;
        fn connection_type(&self) -> ConnectionType {
            ConnectionType::Bluetooth
        }
        async fn send(&mut self, p: impl CdcCommand) -> Result<(), Self::Error> {
            self.command = vec![0; p.size()];
            p.encode(&mut self.command);
            Ok(())
        }
        async fn recv<P: CdcReply>(&mut self, _: Duration) -> Result<P, Self::Error> {
            let ecmd = self.command[5];
            let data = match ecmd {
                0x28 => self.frame(ecmd, &[0x76]),
                0x11 => {
                    let mut body = vec![0x76];
                    body.extend(232_u16.to_le_bytes());
                    body.extend((self.image.len() as u32).to_le_bytes());
                    body.extend(0_u32.to_be_bytes());
                    self.frame(ecmd, &body)
                }
                0x14 => {
                    self.reads += 1;
                    if self.stall {
                        std::future::pending::<()>().await;
                    }
                    let requested =
                        u16::from_le_bytes([self.command[11], self.command[12]]) as usize;
                    self.read_sizes.push(requested);
                    let address =
                        u32::from_le_bytes(self.command[7..11].try_into().unwrap()) as usize;
                    let mut body = self.command[7..11].to_vec();
                    body.extend(&self.image[address..(address + requested).min(self.image.len())]);
                    body.resize(4 + requested, 0);
                    let mut bytes = self.frame(ecmd, &body);
                    if self.corrupt {
                        *bytes.last_mut().unwrap() ^= 1;
                    }
                    bytes
                }
                _ => panic!("A capture must not issue an upload, menu, motor or program command"),
            };
            P::decode(&mut data.as_slice()).map_err(Into::into)
        }
        async fn read_user(&mut self, _: &mut [u8]) -> Result<usize, Self::Error> {
            panic!("No Python during native capture")
        }
        async fn write_user(&mut self, _: &[u8]) -> Result<usize, Self::Error> {
            panic!("No Python during native capture")
        }
    }
    impl CaptureTransport for CaptureFake {
        fn capture_metrics(&self) -> Option<BluetoothIoMetrics> {
            None
        }
        async fn authorize_capture(
            &mut self,
        ) -> Result<Option<FileReadAuthorization>, Self::Error> {
            self.begun += 1;
            if self.stall_authorization {
                std::future::pending::<()>().await;
            }
            Ok(None)
        }
        async fn verify_capture(
            &mut self,
            _: Option<FileReadAuthorization>,
        ) -> Result<(), Self::Error> {
            self.verified += 1;
            if self.stall_final_auth {
                std::future::pending::<()>().await;
            }
            if self.fail_verification {
                Err(BluetoothError::PairingRequired)
            } else {
                Ok(())
            }
        }
        async fn send_capture_read(
            &mut self,
            p: FileDataReadPacket,
            _: Option<&FileReadAuthorization>,
        ) -> Result<(), Self::Error> {
            self.send(p).await
        }
    }
    fn capture_options() -> CaptureOptions {
        CaptureOptions {
            operation_auth: true,
            block_timeout: Duration::from_millis(5),
            transfer_timeout: Duration::from_millis(50),
            diagnostic: true,
            report_path: None,
            payload_window: false,
            reply_pacing: false,
        }
    }
    #[tokio::test]
    async fn read_only_capture_verifies_authentication_before_returning_bytes() {
        let mut fake = CaptureFake::new();
        let options = capture_options();
        let mut trace = CaptureTrace::new(&options, None);
        let image = capture_buffer_inner(&mut fake, Some(8), true, &options, &mut trace)
            .await
            .unwrap();
        assert_eq!(image.len(), 18);
        assert_eq!(fake.begun, 1);
        assert_eq!(fake.verified, 1);
        assert_eq!(fake.reads, 1);
        fake.fail_verification = true;
        assert!(
            capture_buffer_inner(&mut fake, Some(8), true, &options, &mut trace)
                .await
                .is_err()
        );
    }
    #[tokio::test]
    async fn stalled_or_corrupt_camera_blocks_fail_without_retrying_a_read() {
        for stall in [true, false] {
            let mut fake = CaptureFake::new();
            fake.stall = stall;
            fake.corrupt = !stall;
            let options = capture_options();
            let mut trace = CaptureTrace::new(&options, None);
            assert!(
                capture_buffer_inner(&mut fake, Some(8), true, &options, &mut trace)
                    .await
                    .is_err()
            );
            assert_eq!(fake.reads, 1);
            assert_eq!(fake.verified, 0);
        }
    }
    #[tokio::test]
    async fn source_backed_payload_window_keeps_sequential_addresses_and_padding() {
        let mut fake = CaptureFake::new();
        fake.image.resize(600, 0);
        fake.image[598..].copy_from_slice(&[0xff, 0xd9]);
        let mut options = capture_options();
        options.payload_window = true;
        let mut trace = CaptureTrace::new(&options, None);
        let image = capture_buffer_inner(&mut fake, Some(8), true, &options, &mut trace)
            .await
            .unwrap();
        assert_eq!(fake.read_sizes, vec![128, 232, 232, 8]);
        assert_eq!(image, fake.image);
    }
    #[tokio::test]
    async fn transfer_deadline_includes_both_authentication_boundaries() {
        for first in [true, false] {
            let mut fake = CaptureFake::new();
            fake.stall_authorization = first;
            fake.stall_final_auth = !first;
            let mut options = capture_options();
            options.transfer_timeout = Duration::from_millis(5);
            let mut trace = CaptureTrace::new(&options, None);
            assert!(
                capture_buffer_inner(&mut fake, Some(8), true, &options, &mut trace)
                    .await
                    .is_err()
            );
            assert_eq!(fake.begun, 1);
            assert_eq!(fake.reads, if first { 0 } else { 1 });
        }
    }
    #[test]
    fn slow_link_capture_fits_before_all_enclosing_deadlines() {
        // Independently observed ~600 bytes/s: a full RGB565 LCD needs 192s.
        assert!(CAPTURE_TRANSFER_SECS >= (240_u64 * 240 * 2).div_ceil(600));
        assert!(CAPTURE_GUARD_SECS >= CAPTURE_TRANSFER_SECS + 6);
        assert!(CAPTURE_REQUEST_SECS > CAPTURE_GUARD_SECS + 20);
        assert!(CAPTURE_CLIENT_SECS > CAPTURE_REQUEST_SECS);
    }
    #[test]
    fn code_line_reads_only_the_first_line() {
        let input = std::io::Cursor::new(b" 1234 \r\nignored\n".to_vec());
        assert_eq!(read_code_line(input).unwrap(), "1234");
        assert_eq!(
            read_code_line(std::io::Cursor::new(Vec::new())).unwrap(),
            ""
        );
    }
    #[test]
    fn pin_validation_never_echoes_input() {
        assert_eq!(decode_pin("0123").unwrap(), [0, 1, 2, 3]);
        for pin in ["123", "12345", "１２３４", "12a4", " 123"] {
            assert!(!decode_pin(pin).unwrap_err().to_string().contains(pin));
        }
    }
    #[test]
    fn camera_rejects_corrupt_framing_and_unknown_dimensions() {
        let jpeg = [
            0xff, 0xd8, 0xff, 0xc0, 0, 11, 8, 1, 224, 2, 128, 1, 1, 0x11, 0, 0xff, 0xd9,
        ];
        assert_eq!(jpeg_dimensions(&jpeg).unwrap(), (640, 480));
        for cut in 0..jpeg.len() {
            assert!(jpeg_dimensions(&jpeg[..cut]).is_err());
        }
        let mut wrong = jpeg;
        wrong[9] = 1;
        assert!(jpeg_dimensions(&wrong).is_err());
        let mut wrong = jpeg;
        wrong[5] = 255;
        assert!(jpeg_dimensions(&wrong).is_err());
    }
    #[test]
    fn blocks_require_expected_address_and_length_and_strip_final_padding() {
        let mut bytes = vec![];
        for reply in [
            FileDataReadReplyPacket {
                address: 4,
                data: vec![1; 4],
            },
            FileDataReadReplyPacket {
                address: 0,
                data: vec![1; 2],
            },
            FileDataReadReplyPacket {
                address: 0,
                data: vec![1; 5],
            },
        ] {
            assert!(append_block(&mut bytes, 3, 0, 4, &reply).is_err());
            assert!(bytes.is_empty());
        }
        append_block(
            &mut bytes,
            3,
            0,
            4,
            &FileDataReadReplyPacket {
                address: 0,
                data: vec![1, 2, 3, 0],
            },
        )
        .unwrap();
        assert_eq!(bytes, [1, 2, 3]);
    }
    #[test]
    fn camera_firmware_is_checked_without_writes() {
        let mut info = json!({"model":"AIM","hardware":"REV1","firmware":"1.0.0.b0"});
        for revision in ["1.0.0.b0", "1.0.4.b0"] {
            info["firmware"] = json!(revision);
            assert!(require_camera_firmware(&info).is_ok());
        }
        for revision in ["unknown", "1.0.3.b0", "1.0.5.b0"] {
            info["firmware"] = json!(revision);
            assert!(require_camera_firmware(&info).is_err());
        }
        info["firmware"] = json!("1.0.4.b0");
        for field in ["model", "hardware"] {
            let mut other = info.clone();
            other[field] = json!("unknown");
            assert!(require_camera_firmware(&other).is_err());
        }
    }

    #[test]
    fn atomic_save_replaces_complete_output_and_leaves_previous_on_failure() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("camera photo.jpg");
        std::fs::write(&path, b"old").unwrap();
        save_atomic(&path, b"new image").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"new image");
        assert!(save_atomic(&path.join("impossible.jpg"), b"bad").is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"new image");
        assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
    }
}
