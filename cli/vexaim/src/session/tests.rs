//! Real local IPC with a fake radio owner: no robot/credentials required.
use super::*;
use std::future::pending;

#[derive(Clone, Default)]
struct Counters {
    calls: Rc<Cell<usize>>,
    halts: Rc<Cell<usize>>,
    closes: Rc<Cell<usize>>,
}
struct Fake {
    counters: Counters,
    needs_check: bool,
}
impl Backend for Fake {
    async fn perform(
        &mut self,
        request: &Request,
        events: &Events,
        _: Instant,
    ) -> Result<Value, Fail> {
        if matches!(request, Request::Info | Request::Doctor) {
            self.needs_check = false;
            return Ok(json!({"ok":true,"needs_check":false,"robot_state":{"stopped":true}}));
        }
        if self.needs_check {
            return Err(failure("info required before fresh motion"));
        }
        self.counters.calls.set(self.counters.calls.get() + 1);
        if let Request::Exec { source, .. } = request
            && source == "hold"
        {
            events.send(json!({"event":"started"})).unwrap();
            pending::<()>().await;
        }
        Ok(json!({"ok":true}))
    }
    fn interrupted(&mut self, _: &Request) {
        self.needs_check = true;
    }
    async fn halt(&mut self) -> Result<Value, Fail> {
        self.counters.halts.set(self.counters.halts.get() + 1);
        Ok(json!({"ok":true,"stopped":true}))
    }
    async fn close(&mut self) {
        self.counters.closes.set(self.counters.closes.get() + 1);
    }
}

async fn rig(
    label: &str,
) -> (
    String,
    Counters,
    tokio::task::JoinHandle<()>,
    tokio::task::JoinHandle<()>,
) {
    let name = format!("test-{label}-{}", std::process::id());
    let id = ipc::id_for(&name).unwrap();
    let mut listener = ipc::Listener::bind(&id).await.unwrap();
    let cache = Rc::new(RefCell::new(
        json!({"ok":true,"protocol":PROTOCOL,"session":id,"state":"ready","busy":false,"name":name}),
    ));
    let busy = Rc::new(Cell::new(false));
    let (tx, rx) = mpsc::unbounded_channel();
    let (stop_tx, stop_rx) = mpsc::unbounded_channel();
    let counters = Counters::default();
    let backend = Fake {
        counters: counters.clone(),
        needs_check: false,
    };
    let owner = tokio::task::spawn_local(actor(backend, rx, stop_rx, cache.clone(), busy.clone()));
    let listening = tokio::task::spawn_local(async move {
        while let Ok(stream) = listener.accept().await {
            tokio::task::spawn_local(handle(
                stream,
                tx.clone(),
                stop_tx.clone(),
                cache.clone(),
                busy.clone(),
            ));
        }
    });
    (id, counters, owner, listening)
}

async fn wait_calls(counters: &Counters, n: usize) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while counters.calls.get() < n {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test(flavor = "current_thread")]
async fn connection_owner_is_reused_and_busy_motion_is_never_queued() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("reuse").await;
            let status = client(&id, &Request::Status, false, false).await.unwrap();
            assert!(
                guard_one_shot(status["name"].as_str().unwrap())
                    .await
                    .is_err()
            );
            let turn = Request::Turn {
                left: true,
                degrees: 90.0,
                speed: 30.0,
            };
            for _ in 0..2 {
                assert_eq!(client(&id, &turn, false, false).await.unwrap()["ok"], true);
            }
            assert_eq!(counters.calls.get(), 2);
            let hold_id = id.clone();
            let hold = tokio::task::spawn_local(async move {
                client(
                    &hold_id,
                    &Request::Exec {
                        source: "hold".into(),
                        timeout: 30,
                        preamble: true,
                    },
                    false,
                    false,
                )
                .await
            });
            wait_calls(&counters, 3).await;
            assert_eq!(client(&id, &turn, false, false).await.unwrap()["ok"], false);
            assert_eq!(counters.calls.get(), 3);
            assert_eq!(
                client(&id, &Request::Status, false, false).await.unwrap()["state"],
                "ready"
            );
            assert_eq!(
                client(&id, &Request::Stop, false, false).await.unwrap()["stopped"],
                true
            );
            assert_eq!(hold.await.unwrap().unwrap()["needs_check"], true);
            assert_eq!(counters.calls.get(), 3); // rejected movement did not run after stop
            assert_eq!(
                client(&id, &Request::Info, false, false).await.unwrap()["needs_check"],
                false
            );
            assert_eq!(client(&id, &turn, false, false).await.unwrap()["ok"], true);
            assert_eq!(counters.calls.get(), 4);
            assert_eq!(
                client(&id, &Request::Close, false, false).await.unwrap()["ok"],
                true
            );
            owner.await.unwrap();
            assert_eq!(counters.closes.get(), 1);
            listener.abort();
            let _ = listener.await;
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn stop_cancels_a_pending_action_before_it_can_start() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (tx, rx) = mpsc::unbounded_channel();
            let (stop_tx, stop_rx) = mpsc::unbounded_channel();
            let (events, mut results) = mpsc::unbounded_channel();
            tx.send(Job {
                request: Request::Turn {
                    left: true,
                    degrees: 360.0,
                    speed: 30.0,
                },
                events,
                received: Instant::now(),
            })
            .unwrap();
            let (events, mut close_results) = mpsc::unbounded_channel();
            stop_tx
                .send(Job {
                    request: Request::Close,
                    events,
                    received: Instant::now(),
                })
                .unwrap();
            let counters = Counters::default();
            actor(
                Fake {
                    counters: counters.clone(),
                    needs_check: false,
                },
                rx,
                stop_rx,
                Rc::new(RefCell::new(json!({}))),
                Rc::new(Cell::new(true)),
            )
            .await;
            assert_eq!(counters.calls.get(), 0);
            assert_eq!(results.recv().await.unwrap()["ok"], false);
            assert_eq!(close_results.recv().await.unwrap()["stopped"], true);
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn losing_the_caller_interrupts_the_active_action_and_requires_a_state_check() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("caller-lost").await;
            let hold_id = id.clone();
            let hold = tokio::task::spawn_local(async move {
                client(
                    &hold_id,
                    &Request::Exec {
                        source: "hold".into(),
                        timeout: 30,
                        preamble: true,
                    },
                    false,
                    false,
                )
                .await
            });
            wait_calls(&counters, 1).await;
            hold.abort();
            let _ = hold.await;
            tokio::time::timeout(Duration::from_secs(2), async {
                while counters.halts.get() == 0 {
                    tokio::task::yield_now().await;
                }
            })
            .await
            .unwrap();
            assert_eq!(
                client(&id, &Request::Status, false, false).await.unwrap()["needs_check"],
                true
            );
            client(&id, &Request::Close, false, false).await.unwrap();
            owner.await.unwrap();
            listener.abort();
            let _ = listener.await;
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn protocol_rejects_oversized_input_before_allocating_body() {
    let (mut writer, mut reader) = tokio::io::duplex(16);
    writer.write_u32((LIMIT + 1) as u32).await.unwrap();
    assert!(read_frame(&mut reader).await.is_err());
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "build the release CLI first; this launches real short-lived clients against a fake radio owner"]
async fn packaged_cli_reuses_owner_across_processes() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap();
            let binary = root.join("target/release").join(if cfg!(windows) {
                "vexaim.exe"
            } else {
                "vexaim"
            });
            assert!(
                binary.exists(),
                "Build --release before running this integration test"
            );
            let (id, counters, owner, listener) = rig("external-clients").await;
            let state = client(&id, &Request::Status, false, false).await.unwrap();
            let name = state["name"].as_str().unwrap().to_string();
            let commands = vec![
                vec!["--name".to_string(), name, "session".into(), "start".into()],
                vec!["--session".into(), id.clone(), "info".into()],
                vec![
                    "--session".into(),
                    id.clone(),
                    "turn".into(),
                    "left".into(),
                    "15".into(),
                ],
                vec![
                    "--session".into(),
                    id.clone(),
                    "session".into(),
                    "close".into(),
                ],
            ];
            for args in commands {
                let executable = binary.clone();
                let output = tokio::task::spawn_blocking(move || {
                    let mut command = Command::new(executable);
                    command.arg("--json").args(args);
                    #[cfg(windows)]
                    {
                        use std::os::windows::process::CommandExt;
                        command.creation_flags(0x08000000);
                    }
                    command.output().unwrap()
                })
                .await
                .unwrap();
                assert!(
                    output.status.success(),
                    "{} {}",
                    String::from_utf8_lossy(&output.stdout),
                    String::from_utf8_lossy(&output.stderr)
                );
                let result: Value = serde_json::from_slice(&output.stdout).unwrap();
                assert_eq!(result["ok"], true);
            }
            owner.await.unwrap();
            assert_eq!(counters.calls.get(), 1); // only the requested turn reached the fake robot
            assert_eq!(counters.closes.get(), 1);
            listener.abort();
            let _ = listener.await;
        })
        .await;
}
