//! Explicit, ignored stationary hardware control; never part of the CLI runtime.
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
        Decode, DecodeError, DecodeErrorKind, Encode, VEX_CRC16,
        cdc::{CdcCommand, CdcReply, SystemAlivePacket},
        cdc2::aim::ScreenStatusPacket,
    },
};

#[derive(Clone, Debug)]
struct HomeBack;
impl Encode for HomeBack {
    fn size(&self) -> usize {
        10
    }
    fn encode(&self, data: &mut [u8]) {
        data[..8].copy_from_slice(&[0xc9, 0x36, 0xb8, 0x47, 0x56, 0x65, 1, 0x54]);
        let crc = VEX_CRC16.checksum(&data[..8]);
        data[8..10].copy_from_slice(&crc.to_be_bytes());
    }
}
impl CdcCommand for HomeBack {
    const CMD: u8 = 0x56;
    type Reply = HomeBackAck;
}
#[derive(Debug)]
struct HomeBackAck;
impl Decode for HomeBackAck {
    fn decode(data: &mut &[u8]) -> Result<Self, DecodeError> {
        if data.len() < 5 {
            return Err(DecodeError::new::<Self>(DecodeErrorKind::UnexpectedEnd));
        }
        for (offset, name, value) in [(2, "cmd", 0x56), (4, "ecmd", 0x65)] {
            if data[offset] != value {
                return Err(DecodeError::new::<Self>(DecodeErrorKind::UnexpectedByte {
                    name,
                    value: data[offset],
                    expected: if offset == 2 { &[0x56] } else { &[0x65] },
                }));
            }
        }
        if data.len() != 8
            || data[..2] != [0xaa, 0x55]
            || data[3] != 4
            || data[5] != 0x76
            || VEX_CRC16.checksum(data) != 0
        {
            return Err(DecodeError::new::<Self>(DecodeErrorKind::InvalidHeader));
        }
        *data = &data[8..];
        Ok(Self)
    }
}
impl CdcReply for HomeBackAck {
    const CMD: u8 = 0x56;
    type Command = HomeBack;
}

#[tokio::test]
#[ignore = "explicit stationary hardware test; close CLI owners and set readiness/name/output env"]
async fn stationary_idle_control() -> Result<(), Box<dyn std::error::Error>> {
    assert_eq!(
        std::env::var("VEXAIM_HARDWARE_READY").as_deref(),
        Ok("stationary-bluetooth-no-actuators")
    );
    let name = std::env::var("VEXAIM_HARDWARE_NAME")?;
    let path = PathBuf::from(std::env::var("VEXAIM_IDLE_OUTPUT")?);
    let mode = std::env::var("VEXAIM_IDLE_MODE").unwrap_or_else(|_| "back+alive".into());
    assert!(["back+alive", "flags-back", "telemetry"].contains(&mode.as_str()));
    let telemetry = mode == "telemetry";
    let alive = mode != "flags-back";
    let (id, device) = bluetooth::select(&name)
        .await
        .map_err(|e| std::io::Error::other(e.to_string()))?;
    let mut conn = device.connect().await?;
    let result = async {
        let identity = bluetooth::identity(&conn).await.map_err(probe_error)?;
        bluetooth::require_camera_firmware(&identity).map_err(probe_error)?;
        bluetooth::authenticate(&mut conn, &id, false, false)
            .await
            .map_err(probe_error)?;
        conn.peripheral
            .request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized)
            .await?;
        if telemetry {
            // Previously enumerated AIM status notifications; receive only.
            // Do not subscribe to commands, programmer/configuration or reset.
            for value in [
                0x6c7851a0_adf7_4de6_881d_1ce2cd0fecc9u128,
                0x6c7851a0_adf7_4de6_881d_1ce2cd0fecf9u128,
            ] {
                let characteristic = conn
                    .peripheral
                    .characteristics()
                    .into_iter()
                    .find(|c| c.uuid == uuid::Uuid::from_u128(value))
                    .ok_or_else(|| {
                        std::io::Error::other("Known AIM status characteristic missing")
                    })?;
                conn.peripheral.subscribe(&characteristic).await?;
            }
        }
        let mut repl = Repl::from_connection(&mut conn);
        let state = format!(
            "{PREAMBLE}import json\nprint(json.dumps({{'stopped':robot.is_stopped(),\
             'battery_pct':robot.get_battery_level(),'uptime_ms':robot.timer.system(),\
             'x_mm':robot.get_x_position(),'y_mm':robot.get_y_position()}}))\n"
        );
        let before = repl
            .exec(&state, Duration::from_secs(15))
            .await
            .map_err(probe_error)?;
        assert!(before.stderr.is_empty() && !before.timed_out);
        let before: Value = serde_json::from_str(before.stdout.trim())?;
        assert_eq!(before["stopped"], true);
        let mut report = json!({
            "passed":false,"identity":identity,"before":before,"polls":[],"back":[],
            "mode":mode,"telemetry":telemetry
        });
        let start = Instant::now();
        let mut next_back = Instant::now();
        let measured = async {
            while start.elapsed() < Duration::from_secs(420) {
                if alive {
                    repl.connection_mut()
                        .handshake(SystemAlivePacket {}, Duration::from_secs(2), 0)
                        .await?;
                }
                let screen_id = if telemetry {
                    None
                } else {
                    Some(
                        repl.connection_mut()
                            .handshake(ScreenStatusPacket, Duration::from_secs(2), 0)
                            .await??
                            .screen_id,
                    )
                };
                if !telemetry && Instant::now() >= next_back {
                    let sent = screen_id == Some(0);
                    if sent {
                        repl.connection_mut()
                            .handshake(HomeBack, Duration::from_secs(2), 0)
                            .await?;
                    }
                    report["back"].as_array_mut().unwrap().push(json!({
                        "elapsed_s":start.elapsed().as_secs_f64(),"sent":sent
                    }));
                    next_back = Instant::now() + Duration::from_secs(60);
                }
                report["polls"].as_array_mut().unwrap().push(json!({
                    "elapsed_s":start.elapsed().as_secs_f64(),"screen_id":screen_id
                }));
                std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
                if report["polls"].as_array().unwrap().len() % 15 == 1 {
                    println!("{}", report["polls"].as_array().unwrap().last().unwrap());
                }
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
            let after = repl
                .exec(&state, Duration::from_secs(15))
                .await
                .map_err(probe_error)?;
            assert!(after.stderr.is_empty() && !after.timed_out);
            let after: Value = serde_json::from_str(after.stdout.trim())?;
            assert_eq!(after["stopped"], true);
            assert!(after["uptime_ms"].as_u64() > before["uptime_ms"].as_u64());
            if !telemetry {
                let delivered = report["back"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .filter(|v| v["sent"] == true)
                    .count();
                if delivered < 7 {
                    return Err(std::io::Error::other(
                        "Home Back control was not exercised seven times",
                    )
                    .into());
                }
            }
            report["after"] = after;
            report["passed"] = json!(true);
            Ok::<_, Box<dyn std::error::Error>>(())
        }
        .await;
        if let Err(ref error) = measured {
            report["error"] = json!(error.to_string());
        }
        std::fs::write(&path, serde_json::to_vec_pretty(&report)?)?;
        repl.close().await;
        measured
    }
    .await;
    let _ = conn.close().await;
    result
}

fn probe_error(error: crate::repl::Fail) -> std::io::Error {
    std::io::Error::other(error.to_string())
}

#[test]
fn home_back_packet_and_ack_are_strict() {
    let mut wire = vec![0; HomeBack.size()];
    HomeBack.encode(&mut wire);
    assert_eq!(&wire[..8], &[0xc9, 0x36, 0xb8, 0x47, 0x56, 0x65, 1, 0x54]);
    assert_eq!(VEX_CRC16.checksum(&wire), 0);
    let mut ack = vec![0xaa, 0x55, 0x56, 4, 0x65, 0x76];
    ack.extend_from_slice(&VEX_CRC16.checksum(&ack).to_be_bytes());
    assert!(HomeBackAck::decode(&mut ack.as_slice()).is_ok());
    for offset in 0..ack.len() {
        let mut corrupt = ack.clone();
        corrupt[offset] ^= 1;
        assert!(HomeBackAck::decode(&mut corrupt.as_slice()).is_err());
    }
    for length in 0..ack.len() {
        assert!(HomeBackAck::decode(&mut &ack[..length]).is_err());
    }
}
