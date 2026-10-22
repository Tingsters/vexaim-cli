//! Owned AIM system-REPL context and a finite robot-side sleep lease.
use crate::{
    display::DisplayConnection,
    repl::{Fail, PREAMBLE, Repl},
};
use serde_json::{Value, json};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use vex_v5_serial::{
    Connection,
    generic::GenericConnection,
    protocol::{
        FixedString,
        cdc2::{
            Cdc2Ack,
            file::{FileLoadAction, FileLoadActionPacket, FileVendor},
            system::SystemFlagsPacket,
        },
    },
};

type Console = Repl<DisplayConnection<GenericConnection>>;
const RUNTIME: &str = include_str!("power.py");
/// Display activation restarts the robot's Python namespace, so the lease code cannot rely on
/// names defined earlier in the session.
const JSON: &str = "import json as _va_json\n";
const LEASE: Duration = Duration::from_secs(30 * 60);

pub struct Power {
    supported: bool,
    token: String,
    owned_program: bool,
    needs_arm: bool,
    suspended: bool,
    attempted_lease: bool,
    original: Option<bool>,
    confirmed: Option<Instant>,
    deadline: Instant,
    last_background: Instant,
}

fn fail(message: impl ToString) -> Fail {
    Fail::Session(message.to_string())
}
fn is_repl(program: u8, flags: u32) -> bool {
    program == 27 && flags.to_le_bytes()[3] == 19
}
fn supported(identity: &Value) -> bool {
    identity["model"] == "AIM"
        && identity["hardware"] == "REV1"
        && ["firmware", "vexos_version", "cpu0_version", "cpu1_version"]
            .iter()
            .all(|key| identity[*key] == "1.0.4.b0")
}

impl Power {
    pub fn new(identity: &Value) -> Self {
        let supported = supported(identity);
        Self {
            supported,
            token: format!(
                "{}_{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos()
            ),
            owned_program: false,
            needs_arm: supported,
            suspended: false,
            attempted_lease: false,
            original: None,
            confirmed: None,
            deadline: Instant::now() + LEASE,
            last_background: Instant::now() - Duration::from_secs(2),
        }
    }
    pub fn touch(&mut self, received: Instant) {
        self.deadline = received + LEASE;
    }
    pub fn request_arm(&mut self) {
        if self.supported {
            self.needs_arm = true;
            self.confirmed = None;
        }
    }
    pub fn resume(&mut self) {
        self.suspended = false;
    }
    pub fn suspend(&mut self) {
        self.suspended = true;
        self.confirmed = None;
        if self.supported {
            self.needs_arm = true;
        }
    }
    pub fn background_due(&mut self) -> bool {
        if self.needs_arm
            && !self.suspended
            && self.deadline > Instant::now()
            && self.last_background.elapsed() >= Duration::from_secs(1)
        {
            self.last_background = Instant::now();
            true
        } else {
            false
        }
    }
    pub fn repair_pending(&self) -> bool {
        self.supported && self.needs_arm && !self.suspended
    }
    pub fn status(&self) -> Value {
        json!({"supported":self.supported,"active":self.confirmed.is_some() && !self.needs_arm && !self.suspended && self.deadline>Instant::now(),
            "method":"system-repl-sdk-lease","lease_ms":LEASE.as_millis(),"remaining_ms":self.deadline.saturating_duration_since(Instant::now()).as_millis(),
            "last_confirmed_ms_ago":self.confirmed.map(|t|t.elapsed().as_millis()),"restore_to":self.original,
            "experimental":true})
    }

    /// Check native state before any background Python. Never interrupt or
    /// replace an unowned program merely to hold the power lease.
    pub async fn check_role(&self, repl: &mut Console) -> Result<(), Fail> {
        if !self.supported {
            return Ok(());
        }
        let flags = repl
            .connection_mut()
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await
            .map_err(fail)?
            .map_err(fail)?;
        if flags.current_program & 0x0f == 0
            || (self.owned_program && is_repl(flags.current_program, flags.flags))
        {
            Ok(())
        } else {
            Err(Fail::ProgramOwned(
                "Another program owns the AIM; its execution was not interrupted or replaced"
                    .into(),
            ))
        }
    }

    /// Start only the fixed system binary observed in Windows VEXcode. A NACK
    /// 0x01 is provisional only here, with independent program AND screen proof.
    pub async fn arm(&mut self, repl: &mut Console) -> Result<bool, Fail> {
        if !self.supported || !self.needs_arm {
            return Ok(false);
        }
        let flags = repl
            .connection_mut()
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await
            .map_err(fail)?
            .map_err(fail)?;
        if self.owned_program && is_repl(flags.current_program, flags.flags) {
            if !repl.is_raw() {
                repl.sync_waiting_without_interrupt().await?;
            }
            self.needs_arm = false;
            return Ok(false);
        }
        if flags.current_program & 0x0f != 0 {
            return Err(Fail::ProgramOwned(
                "A program is already running; no program was stopped or replaced to keep AIM awake"
            .into()));
        }
        self.owned_program = true;
        // Cancellation while the native program starts must not leave a client
        // assuming that a newly restarted friendly console is still raw.
        repl.invalidate();
        let ack = repl
            .connection_mut()
            .handshake(
                FileLoadActionPacket {
                    vendor: FileVendor::Sys,
                    action: FileLoadAction::Run,
                    file_name: FixedString::new("___v_02.bin").map_err(fail)?,
                },
                Duration::from_secs(2),
                0,
            )
            .await
            .map_err(fail)?;
        match ack {
            Ok(_) | Err(Cdc2Ack::WriteError) => {}
            Err(error) => return Err(fail(error)),
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            let state = repl
                .connection_mut()
                .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
                .await
                .map_err(fail)?
                .map_err(fail)?;
            if is_repl(state.current_program, state.flags) {
                break;
            }
            if Instant::now() >= deadline || state.current_program & 0x0f != 0 {
                return Err(fail(
                    "System REPL program 27/screen 19 was not confirmed; start was not replayed",
                ));
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        repl.sync_waiting_without_interrupt().await?;
        let after = repl
            .connection_mut()
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await
            .map_err(fail)?
            .map_err(fail)?;
        if !is_repl(after.current_program, after.flags) {
            return Err(fail(
                "Raw entry did not retain the verified system REPL; no sleep setting was applied",
            ));
        }
        self.needs_arm = false;
        Ok(true)
    }

    pub async fn acquire(
        &mut self,
        repl: &mut Console,
        install: bool,
        replace_worker: bool,
    ) -> Result<(), Fail> {
        if !self.supported {
            return Ok(());
        }
        let remaining = self
            .deadline
            .saturating_duration_since(Instant::now())
            .as_millis();
        if remaining == 0 {
            self.confirmed = None;
            return Err(fail(
                "AIM power lease expired with its client idle deadline",
            ));
        }
        let remaining = remaining.min(LEASE.as_millis());
        let restore = match self.original {
            None => "None",
            Some(true) => "True",
            Some(false) => "False",
        };
        let code = if install || !self.attempted_lease {
            format!(
                "{PREAMBLE}{JSON}{RUNTIME}\nprint(_va_json.dumps(_va_power_acquire('{}',{remaining},{restore},{})))\n",
                self.token,
                if replace_worker { "True" } else { "False" }
            )
        } else {
            format!(
                "{JSON}print(_va_json.dumps(_va_power_lease.renew('{}',{remaining})))\n",
                self.token
            )
        };
        self.attempted_lease = true;
        self.confirmed = None;
        let value = execute(repl, &code, 12).await?;
        if value["token"] != self.token
            || value["active"] != true
            || value["sleep_disabled"] != true
            || !value["restore_to"].is_boolean()
            || value["watchdog_ticks"].as_u64().unwrap_or(0) == 0
            || value["watchdog_age_ms"]
                .as_f64()
                .is_none_or(|age| age > 3000.0)
        {
            return Err(fail("AIM power lease/watchdog was not confirmed"));
        }
        self.original = value["restore_to"].as_bool();
        self.confirmed = Some(Instant::now());
        Ok(())
    }

    pub async fn release(&mut self, repl: &mut Console) -> Result<(), Fail> {
        self.confirmed = None;
        if self.attempted_lease {
            let value = execute(
                repl,
                &format!(
                    "{JSON}print(_va_json.dumps(_va_power_lease.release('{}')))\n",
                    self.token
                ),
                5,
            )
            .await?;
            if value["token"] != self.token
                || value["active"] != false
                || !value["restore_to"].is_boolean()
                || value["sleep_disabled"] != value["restore_to"]
            {
                return Err(fail("Original AIM sleep setting was not restored"));
            }
            self.attempted_lease = false;
        }
        Ok(())
    }

    pub async fn stop_owned(&mut self, repl: &mut Console) -> Result<(), Fail> {
        if !self.owned_program {
            return Ok(());
        }
        let flags = repl
            .connection_mut()
            .handshake(SystemFlagsPacket {}, Duration::from_secs(2), 0)
            .await
            .map_err(fail)?
            .map_err(fail)?;
        if is_repl(flags.current_program, flags.flags) {
            repl.connection_mut()
                .handshake(
                    FileLoadActionPacket {
                        vendor: FileVendor::User,
                        action: FileLoadAction::Stop,
                        file_name: FixedString::new("null").map_err(fail)?,
                    },
                    Duration::from_secs(2),
                    0,
                )
                .await
                .map_err(fail)?
                .map_err(fail)?;
        }
        self.owned_program = false;
        Ok(())
    }
}

async fn execute(repl: &mut Console, code: &str, seconds: u64) -> Result<Value, Fail> {
    let result = repl.exec(code, Duration::from_secs(seconds)).await?;
    if result.timed_out || !result.stderr.is_empty() {
        return Err(fail(format!(
            "AIM power lease Python failed: {}",
            result.stderr.trim()
        )));
    }
    serde_json::from_str(result.stdout.trim()).map_err(fail)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn new_power_path_requires_every_observed_revision() {
        let profile = json!({"model":"AIM","hardware":"REV1","firmware":"1.0.4.b0","vexos_version":"1.0.4.b0","cpu0_version":"1.0.4.b0","cpu1_version":"1.0.4.b0"});
        assert!(supported(&profile));
        for field in [
            "model",
            "hardware",
            "firmware",
            "vexos_version",
            "cpu0_version",
            "cpu1_version",
        ] {
            let mut unknown = profile.clone();
            unknown.as_object_mut().unwrap().remove(field);
            assert!(!supported(&unknown));
            unknown[field] = json!("1.0.0.b0");
            assert!(!supported(&unknown));
        }
    }
    #[test]
    fn program_and_screen_must_both_match_before_adopting_our_repl() {
        assert!(is_repl(27, 0x13000000));
        assert!(!is_repl(27, 0));
        assert!(!is_repl(0, 0x13000000));
        assert!(!is_repl(27, 0x14000000));
    }
}
