//! Real local IPC with a fake radio owner: no robot/credentials required.
use super::*;
use std::future::pending;
use std::process::Command;

#[derive(Clone, Default)]
struct Counters {
    calls: Rc<Cell<usize>>,
    halts: Rc<Cell<usize>>,
    closes: Rc<Cell<usize>>,
    idles: Rc<Cell<usize>>,
    fail_idle: Rc<Cell<bool>>,
    hold_idle: Rc<Cell<bool>>,
    write_once: Rc<Cell<bool>>,
    write_started: Rc<Cell<bool>>,
    hold_write: Rc<Cell<bool>>,
    write_completed: Rc<Cell<bool>>,
}
struct Fake {
    counters: Counters,
    needs_check: bool,
}
impl Backend for Fake {
    fn idle_is_read_only(&self) -> bool {
        !self.counters.write_once.get()
    }
    async fn perform(
        &mut self,
        request: &Request,
        events: &Events,
        _: Instant,
    ) -> Result<Value, Fail> {
        if matches!(request, Request::Info | Request::Doctor) {
            self.needs_check = false;
            return Ok(
                json!({"ok":true,"needs_check":false,"robot_state":{"stopped":true},"keepalive":{"active":true}}),
            );
        }
        if self.needs_check {
            return Err(failure("info required before fresh motion"));
        }
        if matches!(request, Request::Exec { source, .. } if source == "foreign") {
            self.needs_check = true;
            return Err(Fail::ProgramOwned("Another program owns the AIM".into()));
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
    async fn idle(&mut self) -> Result<Option<Value>, Fail> {
        self.counters.idles.set(self.counters.idles.get() + 1);
        if self.counters.write_once.replace(false) {
            self.counters.write_started.set(true);
            while self.counters.hold_write.get() {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            self.counters.write_completed.set(true);
        }
        if self.counters.hold_idle.get() {
            pending::<()>().await;
        }
        if self.counters.fail_idle.replace(false) {
            self.needs_check = true;
            return Err(failure("keepalive failed"));
        }
        Ok(None)
    }
}

#[tokio::test(flavor = "current_thread")]
async fn heartbeat_does_not_extend_owner_idle_deadline() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (_normal_tx, normal) = mpsc::unbounded_channel();
            let (_priority_tx, priority) = mpsc::unbounded_channel();
            let cache = Rc::new(RefCell::new(json!({"state":"ready"})));
            let counters = Counters::default();
            let backend = Fake {
                counters: counters.clone(),
                needs_check: false,
            };
            tokio::time::timeout(
                Duration::from_secs(3),
                actor_with_idle(
                    backend,
                    normal,
                    priority,
                    cache.clone(),
                    Rc::new(Cell::new(false)),
                    Duration::from_millis(350),
                ),
            )
            .await
            .expect("idle health checks must not renew the owner lease");
            assert!(counters.idles.get() >= 2);
            assert_eq!(counters.halts.get(), 1);
            assert_eq!(counters.closes.get(), 1);
            assert_eq!(cache.borrow()["state"], "closed");
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn failed_idle_keepalive_requires_live_recovery_without_replaying_actions() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("idle-health").await;
            counters.fail_idle.set(true);
            tokio::time::timeout(Duration::from_secs(3), async {
                while counters.fail_idle.get() {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
            let status = client(&id, &Request::Status, false, false).await.unwrap();
            assert_eq!(status["needs_check"], true);
            assert_eq!(status["keepalive"]["healthy"], false);
            assert!(
                status["keepalive_error"]
                    .as_str()
                    .unwrap()
                    .contains("keepalive failed")
            );
            let turn = Request::Turn {
                left: true,
                degrees: 15.0,
                speed: 30.0,
            };
            assert_eq!(client(&id, &turn, false, false).await.unwrap()["ok"], false);
            assert_eq!(counters.calls.get(), 0);
            assert_eq!(
                client(&id, &Request::Info, false, false).await.unwrap()["ok"],
                true
            );
            let status = client(&id, &Request::Status, false, false).await.unwrap();
            assert_eq!(status["keepalive"]["active"], true);
            assert!(status.get("keepalive_error").is_none());
            assert_eq!(client(&id, &turn, false, false).await.unwrap()["ok"], true);
            assert_eq!(counters.calls.get(), 1);
            client(&id, &Request::Close, false, false).await.unwrap();
            owner.await.unwrap();
            listener.abort();
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn stop_and_close_preempt_a_pending_background_heartbeat() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("idle-priority").await;
            counters.hold_idle.set(true);
            tokio::time::timeout(Duration::from_secs(2), async {
                while counters.idles.get() == 0 {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
            let result = tokio::time::timeout(
                Duration::from_secs(1),
                client(&id, &Request::Stop, false, false),
            )
            .await
            .expect("stop must preempt a pending heartbeat")
            .unwrap();
            assert_eq!(result["stopped"], true);
            assert_eq!(counters.calls.get(), 0);
            tokio::time::sleep(Duration::from_millis(150)).await;
            tokio::time::timeout(
                Duration::from_secs(1),
                client(&id, &Request::Close, false, false),
            )
            .await
            .expect("close must preempt a pending heartbeat")
            .unwrap();
            owner.await.unwrap();
            listener.abort();
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn ordinary_clients_wait_for_background_writes_but_stop_preempts_them() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("idle-write").await;
            counters.write_once.set(true);
            counters.hold_write.set(true);
            tokio::time::timeout(Duration::from_secs(2), async {
                while !counters.write_started.get() {
                    tokio::time::sleep(Duration::from_millis(5)).await;
                }
            })
            .await
            .unwrap();
            let query_id = id.clone();
            let ordinary = tokio::task::spawn_local(async move {
                client(&query_id, &Request::Info, false, false).await
            });
            tokio::time::sleep(Duration::from_millis(50)).await;
            assert!(
                !ordinary.is_finished(),
                "ordinary reads must not cancel a partial REPL write"
            );
            assert!(!counters.write_completed.get());
            counters.hold_write.set(false);
            tokio::time::timeout(Duration::from_secs(2), ordinary)
                .await
                .unwrap()
                .unwrap()
                .unwrap();
            assert!(counters.write_completed.get());

            counters.write_started.set(false);
            counters.write_completed.set(false);
            counters.hold_write.set(true);
            counters.write_once.set(true);
            tokio::time::timeout(Duration::from_secs(2), async {
                while !counters.write_started.get() {
                    tokio::time::sleep(Duration::from_millis(5)).await;
                }
            })
            .await
            .unwrap();
            let stopped = tokio::time::timeout(
                Duration::from_secs(1),
                client(&id, &Request::Stop, false, false),
            )
            .await
            .unwrap()
            .unwrap();
            assert_eq!(stopped["stopped"], true);
            assert!(
                !counters.write_completed.get(),
                "priority stop must cancel a background write"
            );
            client(&id, &Request::Close, false, false).await.unwrap();
            owner.await.unwrap();
            listener.abort();
        })
        .await;
}

#[tokio::test(flavor = "current_thread")]
async fn rejected_program_ownership_does_not_trigger_an_automatic_stop() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let (id, counters, owner, listener) = rig("foreign-program").await;
            let reply = client(
                &id,
                &Request::Exec {
                    source: "foreign".into(),
                    timeout: 5,
                    preamble: false,
                },
                false,
                false,
            )
            .await
            .unwrap();
            assert_eq!(reply["ok"], false);
            assert_eq!(reply["rejected"], true);
            assert_eq!(reply["needs_check"], true);
            assert_eq!(counters.calls.get(), 0);
            assert_eq!(counters.halts.get(), 0);
            client(&id, &Request::Close, false, false).await.unwrap();
            owner.await.unwrap();
            listener.abort();
        })
        .await;
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
async fn start_waits_for_slow_closing_owner_without_spawning_a_competitor() {
    tokio::task::LocalSet::new()
        .run_until(async {
            let name = format!("test-closing-{}", std::process::id());
            let id = ipc::id_for(&name).unwrap();
            let mut listener = ipc::Listener::bind(&id).await.unwrap();
            let cache = Rc::new(RefCell::new(json!({
                "ok":true,"protocol":PROTOCOL,"name":name,"state":"closing"
            })));
            let (normal, _normal_rx) = mpsc::unbounded_channel();
            let (priority, _priority_rx) = mpsc::unbounded_channel();
            let listener_cache = cache.clone();
            let listening = tokio::task::spawn_local(async move {
                while let Ok(stream) = listener.accept().await {
                    tokio::task::spawn_local(handle(
                        stream,
                        normal.clone(),
                        priority.clone(),
                        listener_cache.clone(),
                        Rc::new(Cell::new(false)),
                    ));
                }
            });
            // A legitimate successor becomes ready later than the old fixed 500 ms.
            let ready = tokio::task::spawn_local(async move {
                tokio::time::sleep(Duration::from_millis(1100)).await;
                cache.borrow_mut()["state"] = json!("ready");
            });
            let value = tokio::time::timeout(Duration::from_secs(4), start(&name))
                .await
                .unwrap()
                .unwrap();
            assert_eq!(value["state"], "ready");
            ready.await.unwrap();
            listening.abort();
            let _ = listening.await;
        })
        .await;
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
