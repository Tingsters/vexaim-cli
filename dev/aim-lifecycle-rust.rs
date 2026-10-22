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
    let path = PathBuf::from(std::env::var("VEXAIM_LIFECYCLE_OUTPUT")?);
    let mut report = json!({"passed":false,"state":"starting","name":name,
        "method":mode,"quiet_seconds":420,
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
        check_profile(&report["identity"], before_flags.current_program)?;
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
        } else {
        report["state"] = json!("starting_builtin_repl");
        std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
        // Fixed existing system binary only. No file-transfer, firmware write,
        // saved student program or retry of an uncertain start is permitted.
        conn.handshake(FileLoadActionPacket {
            vendor: FileVendor::Sys, action: FileLoadAction::Run,
            file_name: FixedString::new("___v_02.bin")?,
        }, Duration::from_secs(2), 0).await??;
        started = true;
        tokio::time::sleep(Duration::from_millis(100)).await;
        let flags = conn.handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0).await??;
        report["current_program_started"] = json!(flags.current_program);
        if flags.current_program & 0x0f != 2 {
            return Err(std::io::Error::other("Built-in REPL start was acknowledged but program 2 was not confirmed").into());
        }
        }
        let mut repl = Repl::from_connection(&mut conn);
        let read_state = "print(_va_json.dumps({'stopped':robot.is_stopped(),'battery_pct':robot.get_battery_level(),'system_time_ms':robot.timer.system(),'marker':_va_repl_control_marker}))\n";
        let before = repl.exec(&format!("{PREAMBLE}import json as _va_json\n_va_repl_control_marker=robot.timer.system()\n{read_state}"), Duration::from_secs(15)).await.map_err(probe_error)?;
        if before.timed_out || !before.stderr.is_empty() { return Err(std::io::Error::other("Initial Python read failed").into()); }
        let before: Value = serde_json::from_str(before.stdout.trim())?;
        if before["stopped"] != true { return Err(std::io::Error::other("Robot is not stopped").into()); }
        report["before"] = before.clone(); report["state"] = json!("quiet");
        let quiet = Instant::now(); let mut observed = Instant::now();
        while quiet.elapsed() < Duration::from_secs(420) {
            tokio::time::sleep(Duration::from_secs(5).min(Duration::from_secs(420).saturating_sub(quiet.elapsed()))).await;
            if observed.elapsed() > Duration::from_secs(15) { return Err(std::io::Error::other("Host monitoring stalled; quiet interval incomplete").into()); }
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
            if flags.current_program & 0x0f == 2 {
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
