//! Explicit BLE selection, native credential storage and the verified AIM JPEG path.
use crate::{
    BluetoothCmd, Cli, Cmd, out, print_exec,
    repl::{Fail, PREAMBLE, Repl},
    snap::Snap,
};
use btleplug::api::{ConnectionParameterPreset, Peripheral as _};
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
        cdc2::{file::*, system::ScreenCapturePacket},
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
            "Enter exactly four digits in the local masked prompt; never put the code in chat or command arguments.",
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
    Ok(info)
}

pub(crate) async fn authenticate(
    conn: &mut BluetoothConnection,
    id: &str,
    pair: bool,
) -> Result<(), Fail> {
    if !pair && conn.is_paired().await.map_err(io)? {
        return Ok(());
    }
    let code = if pair {
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
            let pair = matches!(cli.cmd, Cmd::Bluetooth { command: BluetoothCmd::Pair });
            authenticate(&mut conn, &id, pair).await?;
            if pair {
                out(cli.json, json!({"ok":true,"transport":"bluetooth","name":name,"id":id,"credential_saved":true}), || format!("Paired {name}; credential saved in the native OS store."));
                return Ok(0);
            }
            if let Cmd::Snap { output } = &cli.cmd {
                require_camera_firmware(&info)?;
                let throughput_requested = matches!(tokio::time::timeout(
                    Duration::from_secs(3),
                    conn.peripheral.request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized)
                ).await, Ok(Ok(())));
                let started = Instant::now();
                let image = tokio::time::timeout(Duration::from_secs(60), capture_jpeg(&mut conn)).await.map_err(|_| fail("Camera capture timed out; existing output was preserved."))??;
                let (width,height) = jpeg_dimensions(&image)?;
                let path = crate::snap::output_path(output.as_deref());
                save_atomic(Path::new(&path), &image)?;
                let elapsed = started.elapsed();
                let result = Snap { path, width, height, bytes:image.len() };
                let interval_us = tokio::time::timeout(Duration::from_secs(2), conn.peripheral.connection_parameters()).await.ok().and_then(Result::ok).flatten().map(|p|p.interval_us);
                out(cli.json, json!({"ok":true,"transport":"bluetooth","path":result.path,"width":width,"height":height,"bytes":result.bytes,"elapsed_ms":elapsed.as_millis() as u64,"within_30_seconds":elapsed<=Duration::from_secs(30),"throughput_request_accepted":throughput_requested,"connection_interval_us":interval_us}), || format!("saved {} ({}x{}, {} bytes, {:.2}s over Bluetooth)",result.path,width,height,result.bytes,elapsed.as_secs_f64()));
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
    let mut repl = Repl::from_connection(conn);
    let operation = async {
        let (source, timeout, preamble) = match &cli.cmd {
            Cmd::Doctor => (STATUS.to_string(),10,true),
            Cmd::Info => (STATE.to_string(),10,true),
            Cmd::Stop => (crate::STOP_CODE.to_string(),5,true),
            Cmd::Exec { code,file,timeout,no_preamble } => (crate::exec_source(code,file)?,*timeout,!*no_preamble),
            Cmd::Turn { direction, degrees, speed } => (format!("{}{}", crate::motion::HELPERS, crate::motion::turn_source(*direction, *degrees, *speed)?), 23, true),
            Cmd::Move { distance, angle, speed } => (format!("{}{}", crate::motion::HELPERS, crate::motion::move_source(*distance, *angle, *speed)?), 23, true),
            _ => return Err(fail("Unsupported Bluetooth command.")),
        };
        if preamble {
            let setup = repl.exec(PREAMBLE,Duration::from_secs(10)).await?;
            if setup.timed_out || !setup.stderr.is_empty() { return Err(fail("Python robot initialization failed or timed out.")); }
        }
        let result = repl.exec(&source,Duration::from_secs(timeout)).await?;
        if matches!(cli.cmd,Cmd::Doctor) {
            crate::validate_status(&result).map_err(fail)?;
            out(cli.json,json!({"verdict":"ready","transport":"bluetooth","device_info":info,"checks":[{"check":"repl","ok":true,"detail":result.stdout.trim(),"fix":""}]}),||format!("[ok] Bluetooth authentication and REPL: {}\nverdict: ready",result.stdout.trim()));
            return Ok(0);
        }
        Ok(print_exec(cli,&result,timeout))
    }.await;
    repl.close().await;
    operation
}

pub(crate) fn require_camera_firmware(info: &serde_json::Value) -> Result<(), Fail> {
    if info["model"] != "AIM" || info["hardware"] != "REV1" || info["firmware"] != "1.0.0.b0" {
        return Err(fail(
            "Native Bluetooth JPEG capture is verified only for AIM REV1 / BLE firmware 1.0.0.b0; no menu/reset fallback was attempted.",
        ));
    }
    Ok(())
}

pub(crate) async fn capture_jpeg(conn: &mut BluetoothConnection) -> Result<Vec<u8>, Fail> {
    conn.handshake(
        ScreenCapturePacket { layer: Some(8) },
        Duration::from_secs(3),
        0,
    )
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
    let chunk = usize::from(init.window_size.saturating_sub(14)).min(216) / 4 * 4;
    if chunk == 0 {
        return Err(fail("Camera receive window is too small."));
    }
    let deadline = Instant::now() + Duration::from_secs(45);
    let mut bytes = Vec::with_capacity(size);
    while bytes.len() < size {
        if Instant::now() >= deadline {
            return Err(fail(
                "Camera transfer exceeded 45 seconds; existing output was preserved.",
            ));
        }
        let requested = if bytes.is_empty() {
            128.min(chunk)
        } else {
            chunk
        }
        .min((size - bytes.len()).div_ceil(4) * 4);
        let address = bytes.len() as u32;
        let reply = conn
            .handshake(
                FileDataReadPacket {
                    address,
                    size: requested as u16,
                },
                Duration::from_secs(3),
                0,
            )
            .await
            .map_err(io)?
            .map_err(io)?;
        append_block(&mut bytes, size, address, requested, &reply)?;
        if address == 0 && !bytes.starts_with(&[0xff, 0xd8]) {
            return Err(fail(
                "Camera layer did not return JPEG; no other layer or menu action was attempted.",
            ));
        }
    }
    jpeg_dimensions(&bytes)?;
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
        assert!(require_camera_firmware(&info).is_ok());
        info["firmware"] = json!("unknown");
        assert!(require_camera_firmware(&info).is_err());
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
