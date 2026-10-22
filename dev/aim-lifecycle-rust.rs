//! Source-derived AIM connection/lifecycle controls; never student commands.
//! Windows VEXcode AIM 4.67.0: AIMVexSerial.sendDataUserPort -> runSystemProgram(2).
use crate::{
    bluetooth,
    repl::{PREAMBLE, Repl},
};
use btleplug::api::{ConnectionParameterPreset, Peripheral as _};
use serde_json::{Value, json};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
use vex_v5_serial::{
    Connection,
    protocol::{
        FixedString,
        cdc2::{
            file::{FileLoadAction, FileLoadActionPacket, FileVendor},
            system::SystemFlagsPacket,
        },
    },
};

fn check_profile(identity: &Value, current_program: u8) -> Result<(), std::io::Error> {
    if identity["model"] != "AIM"
        || identity["hardware"] != "REV1"
        || identity["firmware"] != "1.0.4.b0"
    {
        return Err(std::io::Error::other(
            "Control requires the observed AIM REV1 / 1.0.4.b0 profile",
        ));
    }
    // Official AIM source masks the low nibble before checking program state.
    if current_program & 0x0f != 0 {
        return Err(std::io::Error::other(
            "A program is already running; no program was stopped or replaced",
        ));
    }
    Ok(())
}

fn repl_mode_confirmed(program: u8, flags: u32) -> bool {
    program == 27 && flags.to_le_bytes()[3] == 19
}

#[tokio::test]
#[ignore = "stationary AIM hardware control; requires explicit readiness/name/output env"]
async fn stationary_source_lifecycle_control() -> Result<(), Box<dyn std::error::Error>> {
    assert_eq!(
        std::env::var("VEXAIM_HARDWARE_READY").as_deref(),
        Ok("stationary-bluetooth-no-actuators")
    );
    let name = std::env::var("VEXAIM_HARDWARE_NAME")?;
    let mode = std::env::var("VEXAIM_LIFECYCLE_MODE")?;
    assert!(["official-notifications", "builtin-repl"].contains(&mode.as_str()));
    let quiet_seconds: u64 = std::env::var("VEXAIM_LIFECYCLE_SECONDS")
        .unwrap_or_else(|_| "1200".into())
        .parse()?;
    assert!((420..=1800).contains(&quiet_seconds));
    let path = PathBuf::from(std::env::var("VEXAIM_LIFECYCLE_OUTPUT")?);
    let mut report = json!({"passed":false,"state":"starting","name":name,
        "method":mode,"quiet_seconds":quiet_seconds,
        "foreground_radio_during_quiet":false,"program_uploaded":false});
    std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
    let (id, device) = bluetooth::select(&name).await.map_err(probe_error)?;
    let mut conn = device.connect().await?;
    let mut started = false;
    let result = async {
        let mut identity = bluetooth::identity(&conn).await.map_err(probe_error)?;
        bluetooth::authenticate(&mut conn, &id, false).await.map_err(probe_error)?;
        conn.peripheral.request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized).await?;
        bluetooth::add_system_versions(&mut conn, &mut identity).await;
        let before_flags = conn.handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0).await??;
        report["identity"] = identity;
        report["current_program_before"] = json!(before_flags.current_program);
        let adopt_owned = mode == "builtin-repl" && std::env::var("VEXAIM_LIFECYCLE_ADOPT_OWNED_REPL").as_deref() == Ok("confirmed-prior-control");
        check_profile(&report["identity"], if adopt_owned { 0 } else { before_flags.current_program })?;
        if mode == "official-notifications" {
            // All three notifications are enabled by the official AIM connect
            // path. Subscribing to command status sends no motion command.
            for value in [
                0x6c7851a0_adf7_4de6_881d_1ce2cd0fecf9u128,
                0x6c7851a0_adf7_4de6_881d_1ce2cd0fece9u128,
                0x6c7851a0_adf7_4de6_881d_1ce2cd0fecc9u128,
            ] {
                let characteristic = conn.peripheral.characteristics().into_iter()
                    .find(|c| c.uuid == uuid::Uuid::from_u128(value))
                    .ok_or_else(|| std::io::Error::other("Official AIM status characteristic missing"))?;
                conn.peripheral.subscribe(&characteristic).await?;
            }
            report["subscribed_remote_characteristics"] = json!(3);
        } else if adopt_owned {
            if !repl_mode_confirmed(before_flags.current_program, before_flags.flags) {
                return Err(std::io::Error::other("The prior control's owned REPL program 27 is no longer active").into());
            }
            started = true;
            report["adopted_prior_owned_repl"] = json!(true);
        } else {
        report["state"] = json!("starting_builtin_repl");
        std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
        // Fixed existing system binary only. No file-transfer, firmware write,
        // saved student program or retry of an uncertain start is permitted.
        let ack = conn.handshake(FileLoadActionPacket {
            vendor: FileVendor::Sys, action: FileLoadAction::Run,
            file_name: FixedString::new("___v_02.bin")?,
        }, Duration::from_secs(2), 0).await?;
        match ack {
            Ok(_) => report["start_reply_code"] = json!(0x76),
            // Observed on AIM 1.0.4: this reply accompanies REPL Mode.
            // Never accept it without the independent program/screen checks.
            Err(vex_v5_serial::protocol::cdc2::Cdc2Ack::WriteError) => report["start_reply_code"] = json!(1),
            Err(error) => return Err(error.into()),
        }
        started = true;
        tokio::time::sleep(Duration::from_millis(100)).await;
        let flags = conn.handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0).await??;
        report["current_program_started"] = json!(flags.current_program);
        if !repl_mode_confirmed(flags.current_program, flags.flags) {
            return Err(std::io::Error::other("Built-in REPL program 27 was not confirmed; start was not replayed").into());
        }
        }
        let mut repl = Repl::from_connection(&mut conn);
        let read_state = "print(_va_json.dumps({'stopped':robot.is_stopped(),'battery_pct':robot.get_battery_level(),'system_time_ms':robot.timer.system(),'marker':_va_repl_control_marker}))\n";
        let before = repl.exec(&format!("{PREAMBLE}import json as _va_json\n_va_repl_control_marker=robot.timer.system()\n{read_state}"), Duration::from_secs(15)).await.map_err(probe_error)?;
        if before.timed_out || !before.stderr.is_empty() { return Err(std::io::Error::other("Initial Python read failed").into()); }
        let before: Value = serde_json::from_str(before.stdout.trim())?;
        if before["stopped"] != true { return Err(std::io::Error::other("Robot is not stopped").into()); }
        let flags = repl.connection_mut().handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0).await??;
        report["current_program_after_raw_entry"] = json!(flags.current_program);
        report["screen_after_raw_entry"] = json!(flags.flags.to_le_bytes()[3]);
        if mode == "builtin-repl" && !repl_mode_confirmed(flags.current_program, flags.flags) {
            return Err(std::io::Error::other("Raw console entry did not retain built-in REPL program 27").into());
        }
        report["before"] = before.clone(); report["state"] = json!("quiet");
        let quiet = Instant::now(); let mut observed = Instant::now();
        while quiet.elapsed() < Duration::from_secs(quiet_seconds) {
            tokio::time::sleep(Duration::from_secs(5).min(Duration::from_secs(quiet_seconds).saturating_sub(quiet.elapsed()))).await;
            if observed.elapsed() > Duration::from_secs(15) { return Err(std::io::Error::other("Host monitoring stalled; quiet interval incomplete").into()); }
            // Cached Windows/OS connection state only; no GATT round trip.
            if !tokio::time::timeout(Duration::from_millis(500), repl.connection_mut().peripheral.is_connected()).await?? {
                return Err(std::io::Error::other("Bluetooth connection disappeared during quiet interval").into());
            }
            observed = Instant::now(); report["elapsed_s"] = json!(quiet.elapsed().as_secs_f64());
            std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
        }
        let after = repl.exec(read_state, Duration::from_secs(15)).await.map_err(probe_error)?;
        if after.timed_out || !after.stderr.is_empty() { return Err(std::io::Error::other("Final Python read failed").into()); }
        let after: Value = serde_json::from_str(after.stdout.trim())?;
        if after["stopped"] != true || after["marker"] != before["marker"]
            || after["system_time_ms"].as_u64() <= before["system_time_ms"].as_u64() {
            return Err(std::io::Error::other("Final state/REPL continuity check failed").into());
        }
        report["after"] = after; report["passed"] = json!(true); report["state"] = json!("passed");
        repl.close().await;
        Ok::<_, Box<dyn std::error::Error>>(())
    }.await;
    if let Err(ref error) = result {
        report["state"] = json!("failed");
        report["error"] = json!(error.to_string());
    }
    if started {
        // Do not stop a different program if the user changed the LCD meanwhile.
        if let Ok(Ok(flags)) = conn
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await
        {
            if repl_mode_confirmed(flags.current_program, flags.flags) {
                report["stop_confirmed"] = json!(matches!(
                    conn.handshake(
                        FileLoadActionPacket {
                            vendor: FileVendor::User,
                            action: FileLoadAction::Stop,
                            file_name: FixedString::new("null")?,
                        },
                        Duration::from_secs(2),
                        0
                    )
                    .await,
                    Ok(Ok(_))
                ));
            }
        }
    }
    let _ = conn.close().await;
    std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "{}",
        json!({"passed":report["passed"],"error":report.get("error"),"report":path})
    );
    result
}

fn probe_error(error: crate::repl::Fail) -> std::io::Error {
    std::io::Error::other(error.to_string())
}

#[test]
fn builtin_control_refuses_unknown_profiles_and_running_programs() {
    let profile = json!({"model":"AIM","hardware":"REV1","firmware":"1.0.4.b0"});
    assert!(check_profile(&profile, 0).is_ok());
    assert!(check_profile(&profile, 0x90).is_ok());
    for program in [1, 2, 8, 0x92, 0xff] {
        assert!(check_profile(&profile, program).is_err());
    }
    for key in ["model", "hardware", "firmware"] {
        let mut unknown = profile.clone();
        unknown[key] = json!("unknown");
        assert!(check_profile(&unknown, 0).is_err());
    }
}

#[test]
fn builtin_start_matches_the_installed_official_packet_builder() {
    use vex_v5_serial::protocol::Encode;
    let packet = FileLoadActionPacket {
        vendor: FileVendor::Sys,
        action: FileLoadAction::Run,
        file_name: FixedString::new("___v_02.bin").unwrap(),
    };
    let mut bytes = vec![0; packet.size()];
    packet.encode(&mut bytes);
    assert_eq!(
        bytes,
        [
            201, 54, 184, 71, 86, 24, 26, 15, 0, 95, 95, 95, 118, 95, 48, 50, 46, 98, 105, 110, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 48, 203
        ]
    );
}

#[test]
fn repl_activation_requires_both_observed_program_and_screen() {
    assert!(repl_mode_confirmed(27, 0x13000600));
    for (program, flags) in [(0, 0x13000600), (2, 0x13000600), (27, 0), (27, 0x14000600)] {
        assert!(!repl_mode_confirmed(program, flags));
    }
}

#[tokio::test]
#[ignore = "read-only stationary hardware inspection; explicit readiness/name/output env"]
async fn stationary_lifecycle_diagnostics() -> Result<(), Box<dyn std::error::Error>> {
    use vex_v5_serial::protocol::cdc2::file::{DirectoryEntryPacket, DirectoryFileCountPacket};
    assert_eq!(
        std::env::var("VEXAIM_HARDWARE_READY").as_deref(),
        Ok("stationary-bluetooth-no-actuators")
    );
    let name = std::env::var("VEXAIM_HARDWARE_NAME")?;
    let path = PathBuf::from(std::env::var("VEXAIM_LIFECYCLE_OUTPUT")?);
    let (id, device) = bluetooth::select(&name).await.map_err(probe_error)?;
    let mut conn = device.connect().await?;
    let mut report = json!({"read_only":true,"program_started":false,"passed":false});
    let result = async {
        let mut identity = bluetooth::identity(&conn).await.map_err(probe_error)?;
        check_profile(&identity, 0)?;
        bluetooth::authenticate(&mut conn, &id, false)
            .await
            .map_err(probe_error)?;
        bluetooth::add_system_versions(&mut conn, &mut identity).await;
        conn.peripheral
            .request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized)
            .await?;
        let flags = conn
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await??;
        report["identity"] = identity;
        report["program_field"] = json!(flags.current_program);
        report["flags"] = json!(flags.flags);
        std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
        let bytes =
            tokio::time::timeout(Duration::from_secs(60), bluetooth::capture_lcd(&mut conn))
                .await?
                .map_err(probe_error)?;
        let png = crate::observation::lcd_png(&bytes).map_err(probe_error)?;
        let image = path.with_extension("png");
        crate::observation::save_bytes(&image, &png).map_err(probe_error)?;
        report["lcd"] = json!(image);
        let count = conn
            .handshake(
                DirectoryFileCountPacket {
                    vendor: FileVendor::Sys,
                    reserved: 0,
                },
                Duration::from_secs(2),
                0,
            )
            .await??
            .count;
        report["system_file_count"] = json!(count);
        report["system_files"] = json!([]);
        for index in 0..count.min(16) {
            let entry = conn
                .handshake(
                    DirectoryEntryPacket {
                        file_index: index as u8,
                        reserved: 0,
                    },
                    Duration::from_secs(2),
                    0,
                )
                .await??;
            report["system_files"]
                .as_array_mut()
                .unwrap()
                .push(json!(entry.file_name.as_str()));
        }
        report["passed"] = json!(true);
        Ok::<_, Box<dyn std::error::Error>>(())
    }
    .await;
    if let Err(ref error) = result {
        report["error"] = json!(error.to_string());
    }
    let _ = conn.close().await;
    std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
    println!("{}", report);
    result
}
