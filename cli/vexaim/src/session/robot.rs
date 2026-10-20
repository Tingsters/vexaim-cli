use super::{Backend, Request, failure};
use crate::{
    bluetooth, motion,
    repl::{Fail, PREAMBLE, Repl},
};
use btleplug::api::{ConnectionParameterPreset, Peripheral as _};
use serde_json::{Value, json};
use std::{
    path::Path,
    time::{Duration, Instant},
};
use tokio::sync::mpsc::UnboundedSender;
use vex_v5_serial::bluetooth::BluetoothConnection;

pub struct Robot {
    repl: Repl<BluetoothConnection>,
    identity: Value,
    needs_check: bool,
    camera_usable: bool,
}

fn checked(result: &crate::repl::ExecResult) -> Result<(), Fail> {
    if result.timed_out || !result.stderr.is_empty() {
        return Err(Fail::Bluetooth(format!(
            "Robot Python failed or timed out; no action was retried. {}",
            result.stderr.trim()
        )));
    }
    Ok(())
}

impl Robot {
    async fn connected(&self) -> bool {
        // Cached OS connection state, not a GATT round trip or another scan.
        matches!(
            tokio::time::timeout(
                Duration::from_millis(500),
                self.repl.connection().peripheral.is_connected()
            )
            .await,
            Ok(Ok(true))
        )
    }
    pub async fn open(name: &str) -> Result<(Self, Value), Fail> {
        let all = Instant::now();
        let (id, device) = bluetooth::select(name).await?;
        let discovery_ms = all.elapsed().as_millis() as u64;
        let connected = Instant::now();
        let mut conn = device.connect().await.map_err(failure)?;
        let setup = async {
            let identity = bluetooth::identity(&conn).await?;
            bluetooth::authenticate(&mut conn, &id, false).await?;
            // Keep this request alive in the patched backend for the connection.
            let _ = tokio::time::timeout(
                Duration::from_secs(3),
                conn.peripheral
                    .request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized),
            )
            .await;
            Ok::<_, Fail>(identity)
        }
        .await;
        let identity = match setup {
            Ok(info) => info,
            Err(error) => {
                let _ = conn.close().await;
                return Err(error);
            }
        };
        let connection_ms = connected.elapsed().as_millis() as u64;
        let prepared = Instant::now();
        let mut robot = Self {
            repl: Repl::from_connection(conn),
            identity,
            needs_check: false,
            camera_usable: true,
        };
        let setup = robot
            .repl
            .exec(
                &format!(
                    "{PREAMBLE}{}\nprint(_va_json.dumps(_va_state()))\n",
                    motion::HELPERS
                ),
                Duration::from_secs(15),
            )
            .await;
        let setup = match setup {
            Ok(result) => checked(&result).map(|_| result),
            Err(error) => Err(error),
        };
        let setup = match setup {
            Ok(result) => result,
            Err(error) => {
                robot.close().await;
                return Err(error);
            }
        };
        let state: Value = match serde_json::from_str(setup.stdout.trim()) {
            Ok(state) => state,
            Err(error) => {
                robot.close().await;
                return Err(failure(error));
            }
        };
        Ok((
            robot,
            json!({"id":id,"robot_state":state,"timings":{"discovery_ms":discovery_ms,
            "connection_ms":connection_ms,"preparation_ms":prepared.elapsed().as_millis() as u64,
            "startup_ms":all.elapsed().as_millis() as u64}}),
        ))
    }

    async fn state(&mut self) -> Result<Value, Fail> {
        // Explicit state queries may recover after an interruption, but never replay a move.
        let query = "try:\n    print(_va_json.dumps(_va_state()))\nexcept NameError:\n    print('__VEXAIM_REINITIALIZE__')\n";
        let mut result = self.repl.exec(query, Duration::from_secs(5)).await?;
        checked(&result)?;
        if result.stdout.trim() == "__VEXAIM_REINITIALIZE__" {
            result = self
                .repl
                .exec(
                    &format!(
                        "{PREAMBLE}{}\nprint(_va_json.dumps(_va_state()))\n",
                        motion::HELPERS
                    ),
                    Duration::from_secs(12),
                )
                .await?;
        }
        checked(&result)?;
        let state: Value = serde_json::from_str(result.stdout.trim()).map_err(failure)?;
        self.needs_check = state["stopped"] != true;
        Ok(json!({"ok":true,"robot_state":state,"needs_check":self.needs_check}))
    }
}

impl Backend for Robot {
    async fn perform(
        &mut self,
        request: &Request,
        events: &UnboundedSender<Value>,
        received: Instant,
    ) -> Result<Value, Fail> {
        if !self.connected().await {
            return Err(failure(
                "Bluetooth link is down; robot may be asleep. Close/start the session after checking power. No action was sent or replayed.",
            ));
        }
        if matches!(request, Request::Info | Request::Doctor) {
            let mut state = self.state().await?;
            if matches!(request, Request::Doctor) {
                state["verdict"] = json!("ready");
            }
            return Ok(state);
        }
        if self.needs_check {
            return Err(failure(
                "Previous operation was interrupted or uncertain. Read info to verify the robot is stopped before issuing a fresh action. No movement was replayed.",
            ));
        }
        if let Request::Snap { output } = request {
            if !self.camera_usable {
                return Err(failure(
                    "The camera transfer was interrupted. Close/start the session before another snapshot; movement remains available after an info check.",
                ));
            }
            bluetooth::require_camera_firmware(&self.identity)?;
            let image = tokio::time::timeout(
                Duration::from_secs(60),
                bluetooth::capture_jpeg(self.repl.connection_mut()),
            )
            .await
            .map_err(|_| failure("Camera timed out; output preserved"))??;
            let (width, height) = bluetooth::jpeg_dimensions(&image)?;
            bluetooth::save_atomic(Path::new(output), &image)?;
            return Ok(
                json!({"ok":true,"path":output,"width":width,"height":height,"bytes":image.len()}),
            );
        }
        let (source, timeout) = match request {
            Request::Turn {
                left,
                degrees,
                speed,
            } => (
                motion::turn_source(
                    if *left {
                        motion::Direction::Left
                    } else {
                        motion::Direction::Right
                    },
                    *degrees,
                    *speed,
                )?,
                23,
            ),
            Request::Move {
                distance,
                angle,
                speed,
            } => (motion::move_source(*distance, *angle, *speed)?, 23),
            Request::Exec {
                source,
                timeout,
                preamble,
            } => (
                if *preamble {
                    format!("{PREAMBLE}{source}")
                } else {
                    source.clone()
                },
                *timeout,
            ),
            _ => return Err(failure("Unsupported session request")),
        };
        let mut seen = 0;
        let mut dispatch_ms = None;
        let result = self
            .repl
            .exec_observed(&source, Duration::from_secs(timeout), |buffer| {
                // Notifications may split lines or contain several lines. Never emit twice.
                let text = String::from_utf8_lossy(buffer);
                let lines: Vec<_> = text
                    .split_inclusive('\n')
                    .filter(|s| s.ends_with('\n'))
                    .collect();
                for line in lines.iter().skip(seen) {
                    if let Some((_, body)) = line.split_once(motion::EVENT_PREFIX)
                        && let Ok(mut event) = serde_json::from_str::<Value>(body.trim())
                    {
                        // Robot output cannot impersonate an IPC result/close event.
                        if event["event"] != "started" {
                            continue;
                        }
                        if event["event"] == "started" {
                            let elapsed = received.elapsed().as_millis() as u64;
                            dispatch_ms = Some(elapsed);
                            event["dispatch_ms"] = json!(elapsed);
                            event["start_measurement"] =
                                json!("robot_command_issued_acknowledgement");
                        }
                        let _ = events.send(event);
                    }
                }
                seen = lines.len();
            })
            .await?;
        let stdout = result
            .stdout
            .lines()
            .filter(|s| !s.starts_with(motion::EVENT_PREFIX))
            .collect::<Vec<_>>()
            .join("\n");
        let measurement = stdout
            .lines()
            .rev()
            .find_map(|s| serde_json::from_str::<Value>(s).ok());
        let ok = !result.timed_out && result.stderr.is_empty();
        self.needs_check = !ok;
        Ok(
            json!({"ok":ok,"stdout":stdout,"stderr":result.stderr,"timed_out":result.timed_out,
            "needs_check":self.needs_check,"measurement":measurement,
            "timings":{"dispatch_ms":dispatch_ms,"execution_ms":result.elapsed.as_millis() as u64}}),
        )
    }

    fn interrupted(&mut self, request: &Request) {
        self.repl.invalidate();
        self.needs_check = true;
        if matches!(request, Request::Snap { .. }) {
            self.camera_usable = false;
        }
    }

    async fn halt(&mut self) -> Result<Value, Fail> {
        if !self.connected().await {
            return Err(failure(
                "Robot link unavailable; stopped state cannot be confirmed. Use the physical switch if needed.",
            ));
        }
        self.repl.invalidate();
        let result = self
            .repl
            .exec(
                &format!("{PREAMBLE}robot.stop_all_movement()\ntry:\n    robot.sound.stop()\nexcept Exception:\n    pass\nprint(robot.is_stopped())\n"),
                Duration::from_secs(5),
            )
            .await?;
        checked(&result)?;
        if result.stdout.trim() != "True" {
            return Err(failure(
                "Stop was sent but stopped state was not confirmed; use the physical switch",
            ));
        }
        Ok(json!({"ok":true,"stopped":true}))
    }

    async fn close(&mut self) {
        self.repl.close().await;
        let _ = self.repl.connection_mut().close().await;
    }
}
