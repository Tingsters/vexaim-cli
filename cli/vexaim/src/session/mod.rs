//! One radio owner per user/name; short CLI calls reach it over private local IPC.
mod ipc;
mod owner_process;
mod robot;
#[cfg(test)]
mod tests;

use crate::{Cli, Cmd, SessionCmd, motion, repl::Fail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    sync::mpsc,
};

const LIMIT: usize = 64 * 1024;
const PROTOCOL: u32 = 2;
const IDLE: Duration = Duration::from_secs(30 * 60);

pub(super) fn failure(e: impl std::fmt::Display) -> Fail {
    Fail::Session(e.to_string())
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Request {
    Assets(crate::assets::AssetRequest),
    Native {
        words: Vec<String>,
    },
    Capabilities,
    Observe {
        output_dir: String,
        with_detections: bool,
        camera_index: Option<u32>,
    },
    Status,
    Info,
    Doctor,
    Stop,
    Close,
    Turn {
        left: bool,
        degrees: f64,
        speed: f64,
    },
    Move {
        distance: f64,
        angle: f64,
        speed: f64,
    },
    Exec {
        source: String,
        timeout: u64,
        preamble: bool,
    },
    Snap {
        output: String,
    },
}

impl Request {
    fn validate(&self) -> Result<(), Fail> {
        match self {
            Self::Assets(request) => request.validate()?,
            Self::Native { words } => {
                crate::device::parse(words, true)?;
            }
            Self::Observe { output_dir, .. } if !std::path::Path::new(output_dir).is_absolute() => {
                return Err(failure("Observation directory must be absolute"));
            }
            Self::Turn {
                left,
                degrees,
                speed,
            } => {
                motion::turn_source(
                    if *left {
                        motion::Direction::Left
                    } else {
                        motion::Direction::Right
                    },
                    *degrees,
                    *speed,
                )?;
            }
            Self::Move {
                distance,
                angle,
                speed,
            } => {
                motion::move_source(*distance, *angle, *speed)?;
            }
            Self::Exec {
                source, timeout, ..
            } if source.len() > 48 * 1024 || !(1..=120).contains(timeout) => {
                return Err(failure(
                    "Session exec is limited to 48 KiB and 1..120 seconds",
                ));
            }
            Self::Snap { output } if !std::path::Path::new(output).is_absolute() => {
                return Err(failure(
                    "Session camera output must be an absolute local path",
                ));
            }
            _ => {}
        }
        Ok(())
    }
    fn priority(&self) -> bool {
        matches!(self, Self::Stop | Self::Close)
    }
}

type Events = mpsc::UnboundedSender<Value>;
pub(super) trait Backend {
    async fn perform(
        &mut self,
        request: &Request,
        events: &Events,
        received: Instant,
    ) -> Result<Value, Fail>;
    fn interrupted(&mut self, request: &Request);
    async fn halt(&mut self) -> Result<Value, Fail>;
    async fn close(&mut self);
}

struct Job {
    request: Request,
    events: Events,
    received: Instant,
}
type Cache = Rc<RefCell<Value>>;

fn result(events: &Events, mut value: Value, received: Instant) {
    value["event"] = json!("result");
    value["total_ms"] = json!(received.elapsed().as_millis() as u64);
    let _ = events.send(value);
}
fn error(error: impl std::fmt::Display) -> Value {
    json!({"ok":false,"error":error.to_string()})
}

async fn read_frame<S: AsyncRead + Unpin>(stream: &mut S) -> std::io::Result<Value> {
    let size = stream.read_u32().await? as usize;
    if size == 0 || size > LIMIT {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "IPC frame too large or empty",
        ));
    }
    let mut body = vec![0; size];
    stream.read_exact(&mut body).await?;
    serde_json::from_slice(&body).map_err(std::io::Error::other)
}
async fn write_frame<S: AsyncWrite + Unpin>(stream: &mut S, value: &Value) -> std::io::Result<()> {
    let body = serde_json::to_vec(value)?;
    if body.len() > LIMIT {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "IPC response exceeds 64 KiB",
        ));
    }
    stream.write_u32(body.len() as u32).await?;
    stream.write_all(&body).await?;
    stream.flush().await
}

async fn handle(
    mut stream: ipc::Stream,
    normal: mpsc::UnboundedSender<Job>,
    priority: mpsc::UnboundedSender<Job>,
    cache: Cache,
    busy: Rc<Cell<bool>>,
) {
    let parsed = tokio::time::timeout(Duration::from_secs(2), read_frame(&mut stream)).await;
    let value = match parsed {
        Ok(Ok(value)) => value,
        _ => return,
    };
    if value["protocol"] != PROTOCOL {
        let _ = write_frame(&mut stream, &error("Incompatible session protocol")).await;
        return;
    }
    let request = match serde_json::from_value::<Request>(value["request"].clone())
        .and_then(|r| r.validate().map(|_| r).map_err(serde::de::Error::custom))
    {
        Ok(request) => request,
        Err(e) => {
            let _ = write_frame(&mut stream, &error(e)).await;
            return;
        }
    };
    if matches!(request, Request::Status) {
        let value = cache.borrow().clone();
        let _ = write_frame(&mut stream, &value).await;
        return;
    }
    if cache.borrow()["state"] != "ready" {
        let _ = write_frame(
            &mut stream,
            &error("Session is not ready; no action was queued"),
        )
        .await;
        return;
    }
    let concurrent_device = matches!(&request,Request::Native{words} if crate::device::parse(words,true).is_ok_and(|a|matches!(a.kind.as_str(),"read"|"write"|"vision"|"setting"|"actions")));
    if !request.priority() && busy.replace(true) && !concurrent_device {
        let _ = write_frame(
            &mut stream,
            &error(
                "Robot busy; no movement queued. Try a fresh request when it finishes, or stop it.",
            ),
        )
        .await;
        return;
    }
    let (events, mut receiver) = mpsc::unbounded_channel();
    let job = Job {
        request,
        events,
        received: Instant::now(),
    };
    let is_priority = job.request.priority();
    if (if is_priority { &priority } else { &normal })
        .send(job)
        .is_err()
    {
        busy.set(false);
        let _ = write_frame(&mut stream, &error("Session closed; no action sent")).await;
        return;
    }
    loop {
        tokio::select! {
            event = receiver.recv() => {
                let Some(event) = event else {break};
                let done = event["event"] == "result";
                if !matches!(tokio::time::timeout(Duration::from_secs(2),write_frame(&mut stream,&event)).await,Ok(Ok(()))) || done {break;}
            },
            // A closed caller must not leave its movement running until the host deadline.
            read = stream.read_u8() => { let _ = read; break; }
        }
    }
}

enum Outcome {
    Complete(Result<Value, Fail>),
    Stop(Job),
    CallerGone,
}

async fn actor<B: Backend>(
    mut backend: B,
    mut normal: mpsc::UnboundedReceiver<Job>,
    mut priority: mpsc::UnboundedReceiver<Job>,
    cache: Cache,
    busy: Rc<Cell<bool>>,
) {
    loop {
        let job = tokio::select! { biased;
            job = priority.recv() => job,
            job = normal.recv() => job,
            _ = tokio::time::sleep(IDLE) => { let _ = backend.halt().await; break; }
        };
        let Some(job) = job else { break };
        busy.set(true);
        cache.borrow_mut()["busy"] = json!(true);
        if job.request.priority() {
            backend.interrupted(&job.request);
            cache.borrow_mut()["needs_check"] = json!(true);
            // Stop also cancels an accepted action that the actor has not started yet.
            while let Ok(pending) = normal.try_recv() {
                result(
                    &pending.events,
                    error("Cancelled by stop before execution; no movement sent"),
                    pending.received,
                );
            }
            let halted = backend.halt().await.unwrap_or_else(error);
            result(&job.events, halted, job.received);
            busy.set(false);
            cache.borrow_mut()["busy"] = json!(false);
            if matches!(job.request, Request::Close) {
                break;
            }
            continue;
        }
        // Cancelling this future is followed by an explicit interrupt/resync/stop.
        let outcome = {
            let operation = backend.perform(&job.request, &job.events, job.received);
            tokio::pin!(operation);
            tokio::select! { biased;
                stop = priority.recv() => match stop {Some(stop)=>Outcome::Stop(stop),None=>Outcome::CallerGone},
                _ = job.events.closed() => Outcome::CallerGone,
                result = &mut operation => Outcome::Complete(result),
            }
        };
        let mut close = false;
        match outcome {
            Outcome::Complete(Ok(mut value)) => {
                if value["ok"] == false && value["rejected"] != true {
                    backend.interrupted(&job.request);
                    let stopped = backend.halt().await;
                    value["needs_check"] = json!(true);
                    value["stopped_confirmed"] = json!(stopped.is_ok());
                }
                if let Some(state) = value.get("robot_state") {
                    cache.borrow_mut()["robot_state"] = state.clone();
                }
                cache.borrow_mut()["needs_check"] = json!(value["needs_check"] == true);
                result(&job.events, value, job.received);
            }
            Outcome::Complete(Err(e)) => {
                backend.interrupted(&job.request);
                let halted = backend.halt().await;
                cache.borrow_mut()["needs_check"] = json!(true);
                let mut value = error(e);
                value["needs_check"] = json!(true);
                value["stopped_confirmed"] = json!(halted.is_ok());
                result(&job.events, value, job.received);
            }
            other => {
                backend.interrupted(&job.request);
                let halted = backend.halt().await.unwrap_or_else(error);
                cache.borrow_mut()["needs_check"] = json!(true);
                let mut cancelled =
                    error("Operation interrupted; not retried. Read info before another action.");
                cancelled["needs_check"] = json!(true);
                cancelled["stopped_confirmed"] = json!(halted["stopped"] == true);
                result(&job.events, cancelled, job.received);
                if let Outcome::Stop(stop) = other {
                    close = matches!(stop.request, Request::Close);
                    result(&stop.events, halted, stop.received);
                }
            }
        }
        busy.set(false);
        cache.borrow_mut()["busy"] = json!(false);
        if close {
            break;
        }
    }
    busy.set(true);
    cache.borrow_mut()["state"] = json!("closing");
    backend.close().await;
    cache.borrow_mut()["state"] = json!("closed");
}

async fn serve(id: &str, name: &str) -> Result<(), Fail> {
    if ipc::id_for(name)? != id {
        return Err(failure("Session identity does not match selected name"));
    }
    let mut listener = ipc::Listener::bind(id).await.map_err(failure)?;
    let cache = Rc::new(RefCell::new(
        json!({"ok":true,"protocol":PROTOCOL,"session":id,"name":name,"state":"connecting","busy":false,"tool_version":env!("CARGO_PKG_VERSION")}),
    ));
    let busy = Rc::new(Cell::new(false));
    let (normal_tx, normal_rx) = mpsc::unbounded_channel();
    let (priority_tx, priority_rx) = mpsc::unbounded_channel();
    let (listener_cache, listener_busy) = (cache.clone(), busy.clone());
    let listener = tokio::task::spawn_local(async move {
        while let Ok(stream) = listener.accept().await {
            tokio::task::spawn_local(handle(
                stream,
                normal_tx.clone(),
                priority_tx.clone(),
                listener_cache.clone(),
                listener_busy.clone(),
            ));
        }
    });
    match robot::Robot::open(name).await {
        Ok((robot, details)) => {
            for (key, value) in details.as_object().unwrap() {
                cache.borrow_mut()[key] = value.clone();
            }
            cache.borrow_mut()["state"] = json!("ready");
            actor(robot, normal_rx, priority_rx, cache.clone(), busy).await;
            // Give the close response a chance to flush before stopping the listener.
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        Err(e) => {
            cache.borrow_mut()["ok"] = json!(false);
            cache.borrow_mut()["state"] = json!("failed");
            cache.borrow_mut()["error"] = json!(e.to_string());
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    }
    listener.abort();
    let _ = listener.await;
    Ok(())
}

async fn client(
    id: &str,
    request: &Request,
    json_output: bool,
    print: bool,
) -> Result<Value, Fail> {
    let mut stream = ipc::connect(id).await.map_err(|e| failure(format!("Session unavailable ({e}); start a fresh session after checking the robot. No action was replayed.")))?;
    write_frame(&mut stream, &json!({"protocol":PROTOCOL,"request":request}))
        .await
        .map_err(failure)?;
    loop {
        let response_timeout = if matches!(request, Request::Status) {
            2
        } else {
            130
        };
        let value = tokio::time::timeout(
            Duration::from_secs(response_timeout),
            read_frame(&mut stream),
        )
        .await
        .map_err(|_| failure("Session response timed out; action may have run. Do not replay it."))?
        .map_err(|e| {
            failure(format!(
                "Session response lost ({e}); action may have run. Do not replay it."
            ))
        })?;
        if print {
            if json_output {
                println!("{value}");
            } else if value["event"] == "started" {
                println!("moving");
            } else if let Some(stdout) = value["stdout"].as_str() {
                println!("{stdout}");
                if let Some(err) = value["stderr"].as_str().filter(|s| !s.is_empty()) {
                    eprintln!("{err}");
                }
            } else {
                println!("{value}");
            }
        }
        if value["event"] != "started"
            && (value["event"] == "result" || value.get("event").is_none())
        {
            return Ok(value);
        }
    }
}

async fn start(name: &str) -> Result<Value, Fail> {
    let id = ipc::id_for(name)?;
    let mut connecting = false;
    if let Ok(value) = client(&id, &Request::Status, false, false).await {
        if value["name"] != name || value["protocol"] != PROTOCOL {
            return Err(failure("Existing session identity/protocol mismatch"));
        }
        if value["state"] == "ready" {
            return Ok(value);
        }
        if value["state"] == "failed" {
            return Err(failure(
                value["error"]
                    .as_str()
                    .unwrap_or("Session initialization failed"),
            ));
        }
        connecting = value["state"] == "connecting";
        if value["state"] == "closed" || value["state"] == "closing" {
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    }
    let arguments = [
        "--json",
        "--transport",
        "bluetooth",
        "--name",
        name,
        "session",
        "serve",
        "--id",
        &id,
    ];
    let mut child = if connecting {
        None
    } else {
        Some(owner_process::spawn(&arguments).map_err(failure)?)
    };
    let deadline = Instant::now() + Duration::from_secs(55);
    loop {
        if let Ok(value) = client(&id, &Request::Status, false, false).await {
            if value["name"] != name {
                return Err(failure("Session selected a different name; no action sent"));
            }
            if value["state"] == "ready" {
                return Ok(value);
            }
            if value["state"] == "failed" {
                return Err(failure(
                    value["error"]
                        .as_str()
                        .unwrap_or("Session initialization failed"),
                ));
            }
        }
        if Instant::now() >= deadline {
            if let Some(child) = &mut child {
                let _ = child.kill();
            }
            return Err(failure(
                "Session startup exceeded 55 seconds; no movement was requested",
            ));
        }
        if let Some(child) = &mut child
            && let Some(status) = child.try_wait().map_err(failure)?
        {
            return Err(failure(format!(
                "Session process exited ({status}) before ready; no movement requested"
            )));
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

pub fn run(cli: &Cli) -> Result<i32, Fail> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(failure)?;
    let result = tokio::task::LocalSet::new().block_on(&runtime, async {
        if let Cmd::Session {
            command: SessionCmd::Start,
        } = cli.cmd
        {
            if cli.session.is_some() {
                return Err(failure("Use --name for session start"));
            }
            let name = if let Some(name) = &cli.name {
                name.clone()
            } else {
                if cli.transport == crate::Transport::Bluetooth {
                    return Err(failure("Select Bluetooth robot with --name NAME"));
                }
                let dev = crate::repl::pick(crate::repl::devices()?, cli.device)?;
                format!("usb:{}", dev.system_port().port_info.port_name)
            };
            let value = start(&name).await?;
            crate::out(cli.json, value.clone(), || {
                format!(
                    "Connected to {name}; session {}",
                    value["session"].as_str().unwrap()
                )
            });
            return Ok(0);
        }
        if let Cmd::Session {
            command: SessionCmd::Serve { id },
        } = &cli.cmd
        {
            let name = cli
                .name
                .as_deref()
                .ok_or_else(|| failure("Missing robot name"))?;
            return serve(id, name).await.map(|_| 0);
        }
        let id = cli
            .session
            .as_deref()
            .ok_or_else(|| failure("Select the connection with --session ID"))?;
        if !ipc::valid_id(id) {
            return Err(failure("Invalid session ID"));
        }
        let mut request = match &cli.cmd {
            Cmd::Assets {
                kind,
                operation,
                slot,
                file,
                output,
                replace,
            } => Request::Assets(crate::assets::AssetRequest {
                kind: kind.clone(),
                operation: operation.clone(),
                slot: *slot,
                file: file
                    .as_ref()
                    .map(crate::observation::absolute)
                    .transpose()?
                    .map(|p| p.to_string_lossy().into_owned()),
                output: output
                    .as_ref()
                    .map(crate::observation::absolute)
                    .transpose()?
                    .map(|p| p.to_string_lossy().into_owned()),
                replace: *replace,
            }),
            Cmd::Native(words) => Request::Native {
                words: words.clone(),
            },
            Cmd::Capabilities { .. } => Request::Capabilities,
            Cmd::Camera {
                command:
                    crate::CameraCmd::Observe {
                        output_dir,
                        with_detections,
                        camera_index,
                    },
            } => Request::Observe {
                output_dir: crate::observation::absolute(output_dir)?
                    .to_string_lossy()
                    .into_owned(),
                with_detections: *with_detections,
                camera_index: *camera_index,
            },
            Cmd::Session {
                command: SessionCmd::Status,
            } => Request::Status,
            Cmd::Session {
                command: SessionCmd::Close,
            } => Request::Close,
            Cmd::Info => Request::Info,
            Cmd::Doctor => Request::Doctor,
            Cmd::Stop => Request::Stop,
            Cmd::Turn {
                direction,
                degrees,
                speed,
            } => Request::Turn {
                left: matches!(direction, motion::Direction::Left),
                degrees: *degrees,
                speed: *speed,
            },
            Cmd::Move {
                distance,
                angle,
                speed,
            } => Request::Move {
                distance: *distance,
                angle: *angle,
                speed: *speed,
            },
            Cmd::Exec {
                code,
                inputs,
                file,
                timeout,
                no_preamble,
            } => Request::Exec {
                source: crate::with_inputs(crate::exec_source(code, file)?, inputs)?,
                timeout: *timeout,
                preamble: !*no_preamble,
            },
            Cmd::Snap { output } => {
                let path = std::path::PathBuf::from(crate::snap::output_path(output.as_deref()));
                let path = if path.is_absolute() {
                    path
                } else {
                    std::env::current_dir().map_err(failure)?.join(path)
                };
                Request::Snap {
                    output: path
                        .to_str()
                        .ok_or_else(|| failure("Camera path must be valid UTF-8"))?
                        .to_string(),
                }
            }
            _ => return Err(failure("This command does not use a session")),
        };
        request.validate()?;
        if let Some(expected) = &cli.name {
            let status = client(id, &Request::Status, false, false).await?;
            if status["name"] != *expected {
                return Err(failure(
                    "Session belongs to a different robot; no action sent",
                ));
            }
        }
        let native = if let Request::Native { words } = &request {
            Some(crate::device::parse(words, true)?)
        } else {
            None
        };
        let foreground = native.as_ref().is_some_and(|a| !a.no_wait);
        if matches!(request,Request::Observe{..}) {eprintln!("Capturing a fresh native frame; allow up to 60 seconds plus cleanup.");}
        let wait_id=native.as_ref().filter(|a|a.command=="actions wait").and_then(|a|a.args[0].as_str()).map(str::to_owned);
        if let Some(id)=&wait_id {request=Request::Native{words:vec!["actions".into(),"status".into(),id.clone()]};}
        let mut value = client(id, &request, cli.json, !foreground && !cli.jsonl).await?;
        if foreground {
            if let Some(action_id) = value["value"]["action"]["id"].as_str().map(str::to_owned).or(wait_id) {
                let started = Instant::now();
                loop {
                    tokio::time::sleep(Duration::from_millis(80)).await;
                    let status = client(
                        id,
                        &Request::Native {
                            words: vec!["actions".into(), "status".into(), action_id.clone()],
                        },
                        false,
                        false,
                    )
                    .await?;
                    if status["ok"] != true {
                        value = status;
                        break;
                    }
                    let action = &status["value"]["value"];
                    if action["state"] != "running" {
                        value = json!({"ok":action["state"]=="completed","action":action});
                        break;
                    }
                    if started.elapsed().as_secs() > native.as_ref().unwrap().timeout + 3 {
                        if native.as_ref().unwrap().command!="actions wait" {let _ = client(id, &Request::Stop, false, false).await;}
                        return Err(failure(
                            "Foreground wait exceeded its deadline; no action replayed. Check live state before further motion.",
                        ));
                    }
                }
            }
            if !cli.jsonl {crate::out(cli.json, value.clone(), || value.to_string());}
        }
        if cli.jsonl {crate::device::print_jsonl(value.clone());}
        Ok(if value["ok"] == true { 0 } else { 1 })
    });
    runtime.shutdown_timeout(Duration::from_millis(100));
    result
}

/// Do not let a legacy one-shot process steal a workshop session's console.
pub(crate) async fn guard_one_shot(name: &str) -> Result<(), Fail> {
    let id = ipc::id_for(name)?;
    match ipc::connect(&id).await {
        Ok(_) => Err(failure(format!(
            "A session already owns {name}. Use --session {id} for info/exec/turn/move/snap/stop, or close that session before pairing or standalone commands."
        ))),
        Err(e)
            if matches!(
                e.kind(),
                std::io::ErrorKind::NotFound | std::io::ErrorKind::ConnectionRefused
            ) =>
        {
            Ok(())
        }
        Err(e) => Err(failure(format!(
            "Cannot check the existing session ({e}); no second Bluetooth connection was opened."
        ))),
    }
}
