use super::{Backend, Request, failure};
use crate::{
    bluetooth,
    display::DisplayConnection,
    motion,
    repl::{Fail, PREAMBLE, Repl},
};
use btleplug::api::{ConnectionParameterPreset, Peripheral as _};
use serde_json::{Value, json};
use std::{
    path::Path,
    time::{Duration, Instant},
};
use tokio::sync::mpsc::UnboundedSender;
use vex_v5_serial::generic::GenericConnection;

pub struct Robot {
    repl: Repl<DisplayConnection<GenericConnection>>,
    identity: Value,
    needs_check: bool,
    camera_usable: bool,
    power: crate::power::Power,
}

fn checked(result: &crate::repl::ExecResult) -> Result<(), Fail> {
    if result.timed_out || !result.stderr.is_empty() {
        return Err(Fail::Session(format!(
            "Robot Python failed or timed out; no action was retried. {}",
            result.stderr.trim()
        )));
    }
    Ok(())
}

impl Robot {
    async fn connected(&self) -> bool {
        let GenericConnection::Bluetooth(conn) = self.repl.connection().inner() else {
            return true;
        };
        // Cached OS connection state, not a GATT round trip or another scan.
        matches!(
            tokio::time::timeout(Duration::from_millis(500), conn.peripheral.is_connected()).await,
            Ok(Ok(true))
        )
    }
    pub async fn open(name: &str) -> Result<(Self, Value), Fail> {
        if let Some(port) = name.strip_prefix("usb:") {
            let dev = crate::repl::devices()?
                .into_iter()
                .find(|d| d.system_port().port_info.port_name == port)
                .ok_or_else(|| {
                    failure("Selected USB robot is no longer present; no other robot was selected")
                })?;
            let conn = dev.connect(Duration::from_millis(100)).map_err(failure)?;
            let mut robot = Self {
                repl: Repl::from_connection(DisplayConnection::new(GenericConnection::Serial(
                    conn,
                ))),
                identity: json!({"transport":"usb","system_port":port}),
                needs_check: false,
                camera_usable: true,
                power: crate::power::Power::new(&Value::Null),
            };
            robot.prepare().await?;
            let details = robot.state().await?;
            return Ok((
                robot,
                json!({"transport":"usb","id":name,"robot_state":details["robot_state"]}),
            ));
        }
        let all = Instant::now();
        let (id, device) = bluetooth::select(name).await?;
        let discovery_ms = all.elapsed().as_millis() as u64;
        let connected = Instant::now();
        let mut conn = device.connect().await.map_err(failure)?;
        let setup = async {
            let mut identity = bluetooth::identity(&conn).await?;
            bluetooth::authenticate(&mut conn, &id, false, false).await?;
            // Keep this request alive in the patched backend for the connection.
            let _ = tokio::time::timeout(
                Duration::from_secs(3),
                conn.peripheral
                    .request_connection_parameters(ConnectionParameterPreset::ThroughputOptimized),
            )
            .await;
            bluetooth::add_system_versions(&mut conn, &mut identity).await;
            Ok::<_, Fail>(identity)
        }
        .await;
        let mut identity = match setup {
            Ok(info) => info,
            Err(error) => {
                let _ = conn.close().await;
                return Err(error);
            }
        };
        identity["name"] = json!(name);
        identity["id"] = json!(id);
        let connection_ms = connected.elapsed().as_millis() as u64;
        let prepared = Instant::now();
        let mut robot = Self {
            repl: Repl::from_connection(DisplayConnection::new(GenericConnection::Bluetooth(conn))),
            power: crate::power::Power::new(&identity),
            identity,
            needs_check: false,
            camera_usable: true,
        };
        if let Err(error) = robot.power.arm(&mut robot.repl).await {
            robot.cleanup_open().await;
            return Err(error);
        }
        let setup = robot
            .repl
            .exec(
                &format!(
                    "{PREAMBLE}{}\n{}\nprint(_va_json.dumps(_va_state()))\n",
                    motion::helpers(),
                    crate::device::RUNTIME
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
                robot.cleanup_open().await;
                return Err(error);
            }
        };
        let state: Value = match serde_json::from_str(setup.stdout.trim()) {
            Ok(state) => state,
            Err(error) => {
                robot.cleanup_open().await;
                return Err(failure(error));
            }
        };
        let _keepalive = match robot
            .repl
            .connection_mut()
            .enable_keepalive(&robot.identity)
            .await
        {
            Ok(active) => active,
            Err(error) => {
                robot.cleanup_open().await;
                return Err(error);
            }
        };
        let device_info = robot.identity.clone();
        if let Err(error) = robot.power.acquire(&mut robot.repl, true, false).await {
            robot.cleanup_open().await;
            return Err(error);
        }
        let health = robot.health();
        Ok((
            robot,
            json!({"transport":"bluetooth","id":id,"device_info":device_info,"robot_state":state,"keepalive":health,"timings":{"discovery_ms":discovery_ms,
            "connection_ms":connection_ms,"preparation_ms":prepared.elapsed().as_millis() as u64,
            "startup_ms":all.elapsed().as_millis() as u64}}),
        ))
    }

    async fn prepare(&mut self) -> Result<(), Fail> {
        let result = self
            .repl
            .exec(
                &format!(
                    "{PREAMBLE}{}\n{}",
                    motion::helpers(),
                    crate::device::RUNTIME
                ),
                Duration::from_secs(25),
            )
            .await?;
        checked(&result)
    }
    async fn cleanup_open(&mut self) {
        // Startup failure must not interrupt an unowned student program.
        if self.power.check_role(&mut self.repl).await.is_ok() {
            let _ = self.power.release(&mut self.repl).await;
        }
        let _ = self.power.stop_owned(&mut self.repl).await;
        self.disconnect().await;
    }
    async fn disconnect(&mut self) {
        self.repl.close().await;
        if let GenericConnection::Bluetooth(conn) = self.repl.connection_mut().inner_mut() {
            let _ = conn.close().await;
        }
    }
    fn health(&self) -> Value {
        let mut health = self.repl.connection().keepalive_status();
        health["power"] = self.power.status();
        health
    }
    async fn ensure_power(&mut self, reinstall: bool) -> Result<(), Fail> {
        let restarted = self.power.arm(&mut self.repl).await?;
        if restarted {
            let check = self
                .repl
                .exec(
                    "print('_va_state' in globals() and '_vx_runtime_version' in globals())\n",
                    Duration::from_secs(5),
                )
                .await?;
            checked(&check)?;
            if check.stdout.trim() != "True" {
                self.prepare().await?;
            }
        }
        self.power
            .acquire(&mut self.repl, restarted || reinstall, restarted)
            .await
    }
    async fn native(&mut self, words: &[String]) -> Result<Value, Fail> {
        let a = crate::device::parse(words, true)?;
        if a.command.starts_with("screen ") && a.kind != "read" {
            self.activate_display().await?;
        }
        let source = format!(
            "_vx_print(_vx_dispatch({}))\n",
            crate::device::python_json(&serde_json::to_value(&a).unwrap())
        );
        let result = self
            .repl
            .exec(
                &source,
                Duration::from_secs(a.timeout + crate::device::RESULT_TIMEOUT_SECS),
            )
            .await?;
        checked(&result)?;
        let value: Value = serde_json::from_str(result.stdout.trim()).map_err(failure)?;
        Ok(json!({"ok":value["rejected"]!=true,"rejected":value["rejected"]==true,"value":value}))
    }
    async fn capture(&mut self, camera_index: Option<u32>) -> Result<Vec<u8>, Fail> {
        if !self.camera_usable {
            return Err(failure(
                "Previous capture was interrupted; close/start the session before another image transfer",
            ));
        }
        match self.repl.connection().inner() {
            GenericConnection::Bluetooth(_) => {
                bluetooth::require_camera_firmware(&self.identity)?;
                tokio::time::timeout(
                    Duration::from_secs(60),
                    bluetooth::capture_jpeg(self.repl.connection_mut()),
                )
                .await
                .map_err(|_| failure("Camera capture timed out; no stale artifact returned"))?
            }
            GenericConnection::Serial(_) => {
                tokio::task::spawn_blocking(move || crate::snap::capture(camera_index))
                    .await
                    .map_err(failure)?
                    .map_err(failure)
            }
        }
    }

    async fn state(&mut self) -> Result<Value, Fail> {
        // Explicit state queries may recover after an interruption, but never replay a move.
        let query = "try:\n    print(_va_json.dumps(_va_state()))\nexcept NameError:\n    print('__VEXAIM_REINITIALIZE__')\n";
        let mut result = self.repl.exec(query, Duration::from_secs(5)).await?;
        checked(&result)?;
        if result.stdout.trim() == "__VEXAIM_REINITIALIZE__" {
            self.power.request_arm();
            let restarted = self.power.arm(&mut self.repl).await?;
            self.prepare().await?;
            self.power.acquire(&mut self.repl, true, restarted).await?;
            result = self
                .repl
                .exec(
                    &format!(
                        "{PREAMBLE}{}\nprint(_va_json.dumps(_va_state()))\n",
                        motion::helpers()
                    ),
                    Duration::from_secs(12),
                )
                .await?;
        }
        checked(&result)?;
        let state: Value = serde_json::from_str(result.stdout.trim()).map_err(failure)?;
        self.needs_check = state["stopped"] != true && state["owned_action_active"] != true;
        Ok(
            json!({"ok":true,"robot_state":state,"device_info":self.identity,"needs_check":self.needs_check}),
        )
    }
    async fn activate_display(&mut self) -> Result<(), Fail> {
        if !self.repl.connection().inner().is_bluetooth()
            || self.repl.connection_mut().foreground().await?
        {
            return Ok(());
        }
        let state = self.state().await?;
        if state["robot_state"]["stopped"] != true
            || state["robot_state"]["imu_calibrating"] == true
        {
            return Err(failure(
                "Finish movement/calibration before the first display program; nothing was replayed",
            ));
        }
        self.repl.connection_mut().enable(&self.identity).await?;
        self.power.acquire(&mut self.repl, true, true).await?;
        // Activating the display restarts the robot's Python namespace, which drops the
        // session helpers (_va_*, _vx_*) that the next command relies on.
        self.prepare().await
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
        self.power.touch(received);
        if !self.repl.connection().active() {
            if let Err(error) = self.power.check_role(&mut self.repl).await {
                self.power.suspend();
                self.needs_check = true;
                return Err(error);
            }
        }
        if matches!(request, Request::Info | Request::Doctor) {
            self.power.resume();
            let mut state = self.state().await?;
            self.ensure_power(true).await?;
            // An explicit live read can re-establish failed read-only liveness;
            // background failures never restart or replay a student action.
            self.repl
                .connection_mut()
                .enable_keepalive(&self.identity)
                .await?;
            state["keepalive"] = self.health();
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
        self.ensure_power(false).await?;
        if let Request::Screenshot { output } = request {
            if !self.camera_usable {
                return Err(failure(
                    "Capture interrupted; close/start session before another display capture",
                ));
            }
            let before = self.state().await?;
            if before["robot_state"]["stopped"] != true {
                return Ok(
                    json!({"ok":false,"rejected":true,"error":"Finish movement before LCD capture"}),
                );
            }
            if matches!(
                self.repl.connection().inner(),
                GenericConnection::Bluetooth(_)
            ) {
                bluetooth::require_camera_firmware(&self.identity)?;
            }
            let bytes = tokio::time::timeout(
                Duration::from_secs(60),
                bluetooth::capture_lcd(self.repl.connection_mut()),
            )
            .await
            .map_err(|_| failure("LCD capture timed out"))??;
            let png = crate::observation::lcd_png(&bytes)?;
            crate::observation::save_bytes(Path::new(output), &png)?;
            let after = self.state().await;
            let ready = after
                .as_ref()
                .is_ok_and(|s| s["robot_state"]["stopped"] == true);
            self.needs_check = !ready;
            return Ok(
                json!({"ok":true,"path":output,"mime_type":"image/png","width":240,"height":240,"bytes":png.len(),"source":"LCD screenshot, not the camera","control_ready":ready,"needs_check":!ready}),
            );
        }
        if let Request::Native { words } = request {
            return self.native(words).await;
        }
        if let Request::Assets(asset) = request {
            let state = self.state().await?;
            if state["robot_state"]["stopped"] != true {
                return Ok(
                    json!({"ok":false,"rejected":true,"error":"Finish movement before an asset transfer"}),
                );
            }
            if asset.operation == "list" {
                let value = crate::assets::list(self.repl.connection_mut(), &asset.kind).await?;
                return Ok(json!({"ok":true,"assets":value}));
            }
            let constant = format!(
                "{}{}",
                if asset.kind == "image" {
                    "IMAGE"
                } else {
                    "SOUND"
                },
                asset.slot.unwrap()
            );
            let result = self
                .repl
                .exec(
                    &format!(
                        "_vx_print(_vx_plain(_vx_arg({})))\n",
                        crate::device::python_json(&json!({"constant":constant}))
                    ),
                    Duration::from_secs(5),
                )
                .await?;
            if !result.stderr.is_empty() {
                return Ok(
                    json!({"ok":false,"rejected":true,"error":"Firmware has no verified asset slot filename; no storage mutation was attempted"}),
                );
            }
            let name: Value = serde_json::from_str(result.stdout.trim()).map_err(failure)?;
            let Some(name) = name.as_str() else {
                return Ok(
                    json!({"ok":false,"rejected":true,"error":"Firmware uses numeric asset slots; storage mapping unverified, no mutation attempted"}),
                );
            };
            let value =
                crate::assets::transfer(self.repl.connection_mut(), asset, name, false).await?;
            return Ok(value);
        }
        if matches!(request, Request::Capabilities) {
            let result = self
                .repl
                .exec(&crate::device::capability_source(), Duration::from_secs(30))
                .await?;
            checked(&result)?;
            return Ok(
                json!({"ok":true,"capabilities":serde_json::from_str::<Value>(result.stdout.trim()).map_err(failure)?,"identity":self.identity}),
            );
        }
        if let Request::Observe {
            output_dir,
            with_detections,
            camera_index,
        } = request
        {
            let requested = crate::observation::now_ms();
            let before = self.state().await?;
            if before["robot_state"]["stopped"] != true {
                return Ok(
                    json!({"ok":false,"rejected":true,"error":"Robot is moving; finish/wait/cancel its action before a stable observation","robot_state":before["robot_state"]}),
                );
            }
            eprintln!("Capturing a fresh camera observation (up to 60 seconds)");
            let bytes = self.capture(*camera_index).await?;
            let after = self.state().await;
            let mut ready = after
                .as_ref()
                .is_ok_and(|s| s["robot_state"]["stopped"] == true);
            let detections = if *with_detections && ready {
                Some(
                    match self.native(&["vision".into(), "get-data".into()]).await {
                        Ok(value) => value,
                        Err(error) => {
                            ready = false;
                            json!({"ok":false,"error":error.to_string()})
                        }
                    },
                )
            } else {
                None
            };
            self.needs_check = !ready;
            let transport =
                if matches!(self.repl.connection().inner(), GenericConnection::Serial(_)) {
                    "usb"
                } else {
                    "bluetooth"
                };
            let mut artifact = crate::observation::store(
                Path::new(output_dir),
                &bytes,
                self.identity.clone(),
                transport,
                requested,
                before["robot_state"].clone(),
                after
                    .map(|s| s["robot_state"].clone())
                    .unwrap_or_else(|e| json!({"error":e.to_string()})),
                ready,
                detections,
            )?;
            artifact["needs_check"] = json!(!ready);
            return Ok(artifact);
        }
        if let Request::Snap { output } = request {
            if !self.camera_usable {
                return Err(failure(
                    "The camera transfer was interrupted. Close/start the session before another snapshot; movement remains available after an info check.",
                ));
            }
            let image = self.capture(None).await?;
            let (width, height) = crate::observation::validate(&image)?;
            crate::observation::save(Path::new(output), &image)?;
            return Ok(
                json!({"ok":true,"path":output,"width":width,"height":height,"bytes":image.len()}),
            );
        }
        if matches!(request, Request::Exec {source,..} if crate::display::program_uses_display(source))
        {
            self.activate_display().await?;
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
        self.power.request_arm();
        if matches!(
            request,
            Request::Snap { .. } | Request::Observe { .. } | Request::Screenshot { .. }
        ) {
            self.camera_usable = false;
        }
    }

    async fn halt(&mut self) -> Result<Value, Fail> {
        // Stop bytes take priority over both display and liveness traffic.
        let display_active = self.repl.connection_mut().pause();
        let session_alive = self.repl.connection_mut().end_keepalive();
        if !self.connected().await {
            return Err(failure(
                "Robot link unavailable; stopped state cannot be confirmed. Use the physical switch if needed.",
            ));
        }
        self.repl.invalidate();
        let result = self
            .repl
            .exec(
                &format!("{PREAMBLE}{}\ntry:\n    _vx_cancel_all()\nexcept NameError:\n    pass\nprint(_va_stop())\ntry:\n    robot.sound.stop()\nexcept Exception:\n    pass\n", motion::STOP_HELPER),
                Duration::from_secs(5),
            )
            .await?;
        checked(&result)?;
        if result.stdout.trim() != "True" {
            return Err(failure(
                "Stop was sent but stopped state was not confirmed; use the physical switch",
            ));
        }
        self.repl.connection_mut().restore_keepalive(session_alive);
        if display_active {
            self.repl
                .connection_mut()
                .finish_stop()
                .await
                .map_err(failure)?;
        }
        self.power.request_arm();
        Ok(json!({"ok":true,"stopped":true}))
    }

    async fn close(&mut self) {
        self.repl.connection_mut().end_keepalive();
        let _ = self.halt().await;
        if let Err(error) = self.power.release(&mut self.repl).await {
            eprintln!("Power lease cleanup was not confirmed: {error}");
        }
        let _ = self.power.stop_owned(&mut self.repl).await;
        self.disconnect().await;
    }
    async fn idle(&mut self) -> Result<Option<Value>, Fail> {
        let display_was_active = self.repl.connection().active();
        if self.repl.connection().lease_expired() {
            self.power.request_arm();
        }
        if let Err(error) = self.repl.connection_mut().idle().await {
            self.needs_check = true;
            self.repl.invalidate();
            self.power.request_arm();
            self.power.suspend();
            return Err(failure(error));
        }
        if display_was_active && !self.repl.connection().active() {
            self.power.request_arm();
            // Begin the write phase on the next tick so the actor can defer
            // ordinary clients before borrowing this mutating future.
            return Ok(Some(self.health()));
        }
        if self.power.background_due() {
            let repair = async {
                if !self.repl.is_raw() {
                    return Err(failure(
                        "Live info is required before power-context recovery",
                    ));
                }
                self.power.check_role(&mut self.repl).await?;
                let state = self
                    .repl
                    .exec("print(robot.is_stopped())\n", Duration::from_secs(5))
                    .await?;
                checked(&state)?;
                if state.stdout.trim() == "True" {
                    self.ensure_power(true).await?;
                }
                Ok::<_, Fail>(())
            }
            .await;
            if let Err(error) = repair {
                self.power.suspend();
                self.needs_check = true;
                return Err(error);
            }
        }
        Ok(Some(self.health()))
    }

    fn client_activity(&mut self, received: Instant) {
        self.power.touch(received);
    }
    fn idle_is_read_only(&self) -> bool {
        !self.power.repair_pending() && !self.repl.connection().lease_expired()
    }
}
