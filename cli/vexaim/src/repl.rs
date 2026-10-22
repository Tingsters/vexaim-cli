//! MicroPython raw-REPL client over the AIM user serial port, using vex-v5-serial's
//! `Connection::{read_user, write_user}` only.
use std::time::{Duration, Instant};
use vex_v5_serial::{
    Connection,
    serial::{self, SerialConnection, SerialDevice, SerialError},
};

pub const CTRL_A: u8 = 0x01; // enter raw REPL
pub const CTRL_B: u8 = 0x02; // leave raw REPL
pub const CTRL_C: u8 = 0x03; // interrupt
pub const CTRL_D: u8 = 0x04; // execute (raw REPL)

// An existing robot does not imply constants were imported in this REPL.
// Refresh API names on every prepared exec, but preserve the robot instance.
/// Imports the VEX API and creates `robot`. If the constants are missing after the wildcard
/// imports (seen once on a freshly connected robot: `NameError: ALL_LEDS`), drop the cached
/// modules and import them again.
pub const PREAMBLE: &str = "from vex import *\nfrom vex_globals import *\ntry:\n    ALL_LEDS\nexcept NameError:\n    import sys\n    sys.modules.pop('vex_globals', None)\n    from vex_globals import *\ntry:\n    robot\nexcept NameError:\n    robot = Robot()\n";

#[derive(Debug)]
pub enum Fail {
    NoRobot,
    Ambiguous(usize),
    InvalidDevice(usize, usize),
    NoUserPort,
    Open(String),
    NotRepl(String),
    Io(String),
    Bluetooth(String),
    Session(String),
    #[cfg(feature = "bluetooth")]
    ProgramOwned(String),
}

impl std::fmt::Display for Fail {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Fail::NoRobot => write!(
                f,
                "no VEX AIM found: check the USB cable is plugged in and carries data, and the robot is on"
            ),
            Fail::Ambiguous(n) => write!(
                f,
                "{n} VEX devices found; choose one with --device N (see `vexaim doctor`)"
            ),
            Fail::InvalidDevice(i, n) => write!(
                f,
                "device index {i} is out of range for {n} detected device(s); choose a listed index from `vexaim doctor`"
            ),
            Fail::NoUserPort => write!(f, "found the robot's system port but no user (REPL) port"),
            Fail::Open(e) => write!(
                f,
                "could not open/configure the robot's serial ports ({e}). {}",
                open_hint(std::env::consts::OS)
            ),
            Fail::NotRepl(e) => write!(
                f,
                "the user port did not respond like a MicroPython REPL ({e})"
            ),
            Fail::Io(e) if is_disconnect(e) => write!(
                f,
                "the robot disconnected during the command ({e}): USB unplugged or the robot powered off. Output may be incomplete, and a movement command may or may not have run: check the robot before re-running anything"
            ),
            Fail::Io(e) => write!(f, "robot I/O error: {e}"),
            Fail::Bluetooth(e) => write!(f, "Bluetooth: {e}"),
            Fail::Session(e) => write!(f, "Session: {e}"),
            #[cfg(feature = "bluetooth")]
            Fail::ProgramOwned(e) => write!(f, "{e}"),
        }
    }
}

fn is_disconnect(e: &str) -> bool {
    let e = e.to_lowercase();
    e.contains("broken pipe") || e.contains("no such device") || e.contains("input/output error")
}

pub fn devices() -> Result<Vec<SerialDevice>, Fail> {
    match serial::find_devices() {
        Ok(d) => Ok(d.into_iter().filter(|dev|matches!(&dev.system_port().port_info.port_type,serialport::SerialPortType::UsbPort(usb) if usb.vid==0x2888 && usb.pid==0x0700)).collect()),
        // nothing recognisable is plugged in (the library reports this as a type-inference failure)
        Err(SerialError::CouldntInferTypes) => Ok(Vec::new()),
        Err(e) => Err(Fail::Io(e.to_string())),
    }
}

pub fn pick(mut all: Vec<SerialDevice>, index: Option<usize>) -> Result<SerialDevice, Fail> {
    let i = selected_index(all.len(), index)?;
    Ok(all.remove(i))
}

fn selected_index(count: usize, index: Option<usize>) -> Result<usize, Fail> {
    match (count, index) {
        (0, _) => Err(Fail::NoRobot),
        (_, Some(i)) if i < count => Ok(i),
        (n, Some(i)) => Err(Fail::InvalidDevice(i, n)),
        (1, None) => Ok(0),
        (n, None) => Err(Fail::Ambiguous(n)),
    }
}

pub fn open_hint(os: &str) -> &'static str {
    match os {
        "linux" => {
            "Close other serial tools. Install linux/install-udev.sh and re-plug, or wait 30 s if ModemManager is probing."
        }
        "windows" => {
            "Close VEXcode and other serial tools, then re-plug. If DTR setup fails, retain the COM port and Windows error when reporting it."
        }
        _ => "Close VEXcode and other serial tools, then re-plug the robot.",
    }
}

pub fn repl_hint(os: &str) -> &'static str {
    match os {
        "linux" => {
            "Wait 30 s after plugging in unless the udev rule is installed. Close other serial tools, then retry; power-cycle if still stuck."
        }
        "windows" => {
            "Use vexaim 0.1.1 or newer (0.1.0 leaves DTR low and the AIM REPL silent). Close other serial tools, re-plug, and retry; power-cycle if still stuck. `vexaim stop` also needs a working REPL."
        }
        _ => {
            "Close other serial tools, re-plug, and retry; power-cycle if still stuck. `vexaim stop` also needs a working REPL."
        }
    }
}

pub struct Repl<C = SerialConnection> {
    conn: C,
    raw: bool,
}

pub struct ExecResult {
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
    pub elapsed: Duration,
}

pub(crate) fn is_timeout(e: &(dyn std::error::Error + 'static)) -> bool {
    #[cfg(feature = "bluetooth")]
    if let Some(inner) = e.downcast_ref::<vex_v5_serial::generic::GenericError>() {
        return match inner {
            vex_v5_serial::generic::GenericError::SerialError(e) => is_timeout(e),
            vex_v5_serial::generic::GenericError::BluetoothError(e) => is_timeout(e),
            _ => false,
        };
    }
    if let Some(SerialError::IoError(io)) = e.downcast_ref::<SerialError>() {
        return io.kind() == std::io::ErrorKind::TimedOut;
    }
    #[cfg(feature = "bluetooth")]
    if matches!(
        e.downcast_ref::<vex_v5_serial::bluetooth::BluetoothError>(),
        Some(vex_v5_serial::bluetooth::BluetoothError::Timeout)
    ) {
        return true;
    }
    false
}

impl Repl {
    pub fn open(dev: &SerialDevice) -> Result<Self, Fail> {
        if dev.user_port().is_none() {
            return Err(Fail::NoUserPort);
        }
        // short per-read timeout so we can poll with our own deadlines
        let conn = dev
            .connect(Duration::from_millis(100))
            .map_err(|e| Fail::Open(e.to_string()))?;
        Ok(Self { conn, raw: false })
    }
}

impl<C: Connection> Repl<C>
where
    C::Error: 'static,
{
    #[cfg(feature = "bluetooth")]
    pub fn from_connection(conn: C) -> Self {
        Self { conn, raw: false }
    }

    async fn write_all(&mut self, data: &[u8]) -> Result<(), Fail> {
        // chunked so the robot's UART/CDC buffer is never overrun by long programs
        for chunk in data.chunks(256) {
            self.conn.write_user(chunk).await.map_err(|e| {
                transport_io(self.conn.connection_type(), format!("write to robot: {e}"))
            })?;
            if data.len() > 256 {
                smol::Timer::after(Duration::from_millis(10)).await;
            }
        }
        Ok(())
    }

    /// Read until `pred(buf)` is true or the deadline passes.
    async fn read_until(
        &mut self,
        deadline: Instant,
        pred: impl Fn(&[u8]) -> bool,
    ) -> Result<(Vec<u8>, bool), Fail> {
        self.read_observed(deadline, pred, |_| {}).await
    }

    async fn read_observed(
        &mut self,
        deadline: Instant,
        pred: impl Fn(&[u8]) -> bool,
        mut observe: impl FnMut(&[u8]),
    ) -> Result<(Vec<u8>, bool), Fail> {
        let mut buf = Vec::new();
        loop {
            if pred(&buf) {
                return Ok((buf, true));
            }
            if Instant::now() >= deadline {
                return Ok((buf, false));
            }
            let mut chunk = [0u8; 512];
            match self.conn.read_user(&mut chunk).await {
                Ok(0) => {}
                Ok(n) => {
                    buf.extend_from_slice(&chunk[..n]);
                    observe(&buf);
                }
                Err(e) if is_timeout(&e) => {}
                Err(e) => {
                    return Err(transport_io(
                        self.conn.connection_type(),
                        format!("read from robot: {e}"),
                    ));
                }
            }
        }
    }

    async fn drain(&mut self, ms: u64) -> Result<(), Fail> {
        self.read_until(Instant::now() + Duration::from_millis(ms), |_| false)
            .await
            .map(|_| ())
    }

    /// Interrupt anything running and enter raw-REPL mode.
    pub async fn sync(&mut self) -> Result<(), Fail> {
        let mut last = String::new();
        for _ in 0..3 {
            self.write_all(&[CTRL_C, CTRL_C]).await?;
            self.drain(300).await?;
            self.write_all(&[CTRL_A]).await?;
            let (buf, ok) = self
                .read_until(Instant::now() + Duration::from_secs(2), ends_raw_prompt)
                .await?;
            last = String::from_utf8_lossy(&buf).into_owned();
            if ok {
                self.raw = true;
                return Ok(());
            }
        }
        Err(Fail::NotRepl(format!("got {last:?}")))
    }

    /// Require an already waiting system REPL, then enter raw mode without a
    /// program-ending interrupt. The caller must verify native program state.
    #[cfg(feature = "bluetooth")]
    pub async fn sync_waiting_without_interrupt(&mut self) -> Result<(), Fail> {
        self.raw = false;
        // Ctrl-B refreshes a waiting friendly prompt or leaves waiting raw mode;
        // it does not soft-reset Python. This also works after a warm reattach,
        // when the previous prompt was consumed by the prior connection.
        self.write_all(&[CTRL_B]).await?;
        let (_, ready) = self
            .read_until(Instant::now() + Duration::from_secs(5), |b| {
                b.ends_with(b">>> ")
            })
            .await?;
        if !ready {
            return Err(Fail::NotRepl(
                "Built-in REPL waiting prompt was not observed; no interrupt sent".into(),
            ));
        }
        self.write_all(&[CTRL_A]).await?;
        let (_, raw) = self
            .read_until(Instant::now() + Duration::from_secs(3), ends_raw_prompt)
            .await?;
        if !raw {
            return Err(Fail::NotRepl(
                "Built-in REPL did not enter raw mode; no interrupt sent".into(),
            ));
        }
        self.raw = true;
        Ok(())
    }

    /// Execute code in raw-REPL mode. On timeout the program is interrupted (Ctrl-C).
    pub async fn exec(&mut self, code: &str, timeout: Duration) -> Result<ExecResult, Fail> {
        self.exec_observed(code, timeout, |_| {}).await
    }

    /// Report progress while raw-REPL output is still arriving.
    pub async fn exec_observed(
        &mut self,
        code: &str,
        timeout: Duration,
        observe: impl FnMut(&[u8]),
    ) -> Result<ExecResult, Fail> {
        if !self.raw {
            self.sync().await?;
        }
        let t = Instant::now();
        self.write_all(code.as_bytes()).await?;
        self.write_all(&[CTRL_D]).await?;
        let (buf, done) = self
            .read_observed(t + timeout, complete_raw_frame, observe)
            .await?;
        if !done {
            // stop the running program, then return to a known state
            self.write_all(&[CTRL_C, CTRL_C]).await?;
            self.drain(500).await?;
            self.raw = false;
            let text = String::from_utf8_lossy(&buf);
            let out = text.strip_prefix("OK").unwrap_or(&text).to_string();
            return Ok(ExecResult {
                stdout: out,
                stderr: String::new(),
                timed_out: true,
                elapsed: t.elapsed(),
            });
        }
        let (stdout, stderr) = parse_frame(&buf);
        Ok(ExecResult {
            stdout,
            stderr,
            timed_out: false,
            elapsed: t.elapsed(),
        })
    }

    #[cfg(feature = "bluetooth")]
    pub fn connection_mut(&mut self) -> &mut C {
        &mut self.conn
    }

    #[cfg(feature = "bluetooth")]
    pub fn connection(&self) -> &C {
        &self.conn
    }
    #[cfg(feature = "bluetooth")]
    pub fn is_raw(&self) -> bool {
        self.raw
    }

    /// A cancelled transaction may have left Python running or a partial prompt.
    #[cfg(feature = "bluetooth")]
    pub fn invalidate(&mut self) {
        self.raw = false;
    }

    /// Leave raw mode so a human can use the normal `>>>` REPL afterwards.
    pub async fn close(&mut self) {
        if self.raw {
            let _ = self.write_all(&[CTRL_B]).await;
            let _ = self.drain(200).await;
            self.raw = false;
        }
    }
}

fn ends_raw_prompt(b: &[u8]) -> bool {
    b.ends_with(b"to exit\r\n>")
}

fn transport_io(kind: vex_v5_serial::ConnectionType, detail: String) -> Fail {
    if kind.is_bluetooth() {
        Fail::Bluetooth(detail)
    } else {
        Fail::Io(detail)
    }
}

/// Byte offset just past the `\x04` that ends stdout, and the one ending stderr, if both present.
fn frame_end(b: &[u8]) -> Option<(usize, usize)> {
    let first = b.iter().position(|&c| c == CTRL_D)?;
    let second = b[first + 1..].iter().position(|&c| c == CTRL_D)? + first + 1;
    Some((first, second))
}

/// Drop the raw-REPL banner ("raw REPL; CTRL-B to exit\r\n>") that can precede a reply when
/// raw mode was entered by something other than this client (for example display activation).
fn skip_banner(b: &[u8]) -> &[u8] {
    if b.starts_with(b"raw REPL") {
        if let Some(i) = b.windows(3).position(|w| w == b">OK") {
            return &b[i + 1..];
        }
    }
    b
}

fn complete_raw_frame(b: &[u8]) -> bool {
    let b = skip_banner(b);
    // BLE can deliver the final '>' in its own notification. Consume it before
    // the next command, otherwise that delayed prompt corrupts the next 'OK'.
    b.starts_with(b"OK") && frame_end(b).is_some_and(|(_, end)| b.get(end + 1) == Some(&b'>'))
}

fn parse_frame(b: &[u8]) -> (String, String) {
    let b = skip_banner(b);
    let (a, z) = frame_end(b).unwrap_or((b.len(), b.len()));
    let out = &b[2.min(b.len())..a]; // skip "OK"
    let err = if a + 1 <= z { &b[a + 1..z] } else { &b[0..0] };
    (
        String::from_utf8_lossy(out).into_owned(),
        String::from_utf8_lossy(err).into_owned(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn banner_before_reply_is_skipped() {
        let reply = b"raw REPL; CTRL-B to exit\r\n>OK\x04Traceback\r\nNameError\x04>";
        assert!(complete_raw_frame(reply));
        let (out, err) = parse_frame(reply);
        assert_eq!(out, "");
        assert!(err.starts_with("Traceback"));
        let plain = b"OK42\r\n\x04\x04>";
        assert!(complete_raw_frame(plain));
        assert_eq!(parse_frame(plain).0, "42\r\n");
    }

    #[test]
    fn preamble_reimports_constants_before_creating_robot() {
        let reimport = PREAMBLE.find("sys.modules.pop('vex_globals'").unwrap();
        let robot = PREAMBLE.find("robot = Robot()").unwrap();
        assert!(reimport < robot);
        assert!(PREAMBLE.starts_with("from vex import *\nfrom vex_globals import *\n"));
    }

    #[cfg(feature = "bluetooth")]
    mod waiting_entry {
        use super::*;
        use std::collections::VecDeque;
        use vex_v5_serial::{
            ConnectionType,
            bluetooth::BluetoothError,
            generic::GenericError,
            protocol::cdc::{CdcCommand, CdcReply},
        };

        struct Console {
            incoming: VecDeque<Vec<u8>>,
            writes: Vec<Vec<u8>>,
            raw_reply: bool,
            friendly_reply: bool,
        }
        impl Connection for Console {
            type Error = GenericError;
            fn connection_type(&self) -> ConnectionType {
                ConnectionType::Bluetooth
            }
            async fn send(&mut self, _: impl CdcCommand) -> Result<(), Self::Error> {
                panic!("Console entry must not send an admin/program command")
            }
            async fn recv<P: CdcReply>(&mut self, _: Duration) -> Result<P, Self::Error> {
                panic!("Console entry must not read an admin/program reply")
            }
            async fn read_user(&mut self, buf: &mut [u8]) -> Result<usize, Self::Error> {
                if let Some(bytes) = self.incoming.pop_front() {
                    buf[..bytes.len()].copy_from_slice(&bytes);
                    return Ok(bytes.len());
                }
                smol::Timer::after(Duration::from_millis(5)).await;
                Err(BluetoothError::Timeout.into())
            }
            async fn write_user(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
                self.writes.push(bytes.to_vec());
                if bytes == [CTRL_B] && self.friendly_reply {
                    self.incoming.push_back(b"MicroPython\r\n>>> ".to_vec());
                }
                if bytes == [CTRL_A] && self.raw_reply {
                    self.incoming
                        .push_back(b"raw REPL; CTRL-B to exit\r\n".to_vec());
                    self.incoming.push_back(b">".to_vec());
                }
                if bytes == [CTRL_D] {
                    self.incoming.push_back(b"OK1\r\n\x04\x04>".to_vec());
                }
                Ok(bytes.len())
            }
        }
        fn console(chunks: &[&[u8]], friendly_reply: bool, raw_reply: bool) -> Repl<Console> {
            Repl::from_connection(Console {
                incoming: chunks.iter().map(|b| b.to_vec()).collect(),
                writes: Vec::new(),
                raw_reply,
                friendly_reply,
            })
        }

        #[tokio::test]
        async fn waiting_entry_preserves_console_through_the_first_execution() {
            let mut repl = console(&[b"MicroPython\r\n>", b">", b"> "], true, true);
            repl.sync_waiting_without_interrupt().await.unwrap();
            let result = repl.exec("print(1)", Duration::from_secs(1)).await.unwrap();
            assert_eq!(result.stdout.trim(), "1");
            assert!(result.stderr.is_empty());
            assert_eq!(
                repl.conn.writes,
                [
                    vec![CTRL_B],
                    vec![CTRL_A],
                    b"print(1)".to_vec(),
                    vec![CTRL_D]
                ]
            );
            assert!(!repl.conn.writes.iter().flatten().any(|b| *b == CTRL_C));
        }

        #[tokio::test]
        async fn warm_raw_console_is_reprompted_without_interrupt() {
            let mut repl = console(&[b"raw REPL; CTRL-B to exit\r\n>"], true, true);
            repl.sync_waiting_without_interrupt().await.unwrap();
            assert!(repl.raw);
            assert_eq!(repl.conn.writes, [vec![CTRL_B], vec![CTRL_A]]);
        }

        #[tokio::test]
        async fn missing_waiting_prompt_never_sends_a_program_interrupt() {
            let mut repl = console(&[b"program output without a prompt"], false, true);
            assert!(repl.sync_waiting_without_interrupt().await.is_err());
            assert!(!repl.raw);
            assert_eq!(repl.conn.writes, [vec![CTRL_B]]);
        }

        #[tokio::test]
        async fn failed_raw_entry_never_falls_back_to_a_program_interrupt() {
            let mut repl = console(&[b">>> "], true, false);
            assert!(repl.sync_waiting_without_interrupt().await.is_err());
            assert!(!repl.raw);
            assert_eq!(repl.conn.writes, [vec![CTRL_B], vec![CTRL_A]]);
        }
    }

    #[test]
    fn parses_ok_frame() {
        let (o, e) = parse_frame(b"OKhello\r\n42\r\n\x04\x04>");
        assert_eq!(o, "hello\r\n42\r\n");
        assert_eq!(e, "");
    }

    #[test]
    fn parses_error_frame() {
        let (o, e) = parse_frame(b"OK\x04Traceback (most recent call last):\r\nZeroDivisionError: divide by zero\r\n\x04>");
        assert_eq!(o, "");
        assert!(e.contains("ZeroDivisionError"));
    }

    #[test]
    fn incomplete_frame_has_no_end() {
        assert!(frame_end(b"OKpartial output").is_none());
        assert!(frame_end(b"OKout\x04").is_none());
    }

    #[test]
    fn raw_reply_waits_for_fragmented_final_prompt() {
        assert!(!complete_raw_frame(b"OKhello\x04\x04"));
        assert!(complete_raw_frame(b"OKhello\x04\x04>"));
        assert!(!complete_raw_frame(b">OKhello\x04\x04>"));
    }

    #[test]
    fn disconnect_errors_are_recognised() {
        assert!(is_disconnect("IO Error: Broken pipe"));
        assert!(is_disconnect("IO Error: No such device"));
        assert!(!is_disconnect("IO Error: Operation timed out"));
    }

    #[test]
    fn bluetooth_io_failure_does_not_prescribe_a_usb_reconnect() {
        let error = transport_io(
            vex_v5_serial::ConnectionType::Bluetooth,
            "broken pipe".into(),
        )
        .to_string();
        assert!(error.contains("Bluetooth"));
        assert!(!error.contains("USB"));
    }

    #[test]
    fn raw_prompt_detected() {
        assert!(ends_raw_prompt(b"\r\nraw REPL; CTRL-B to exit\r\n>"));
        assert!(!ends_raw_prompt(b">>> "));
    }

    #[test]
    fn device_selection_requires_an_unambiguous_valid_index() {
        assert!(matches!(selected_index(0, None), Err(Fail::NoRobot)));
        assert!(matches!(selected_index(2, None), Err(Fail::Ambiguous(2))));
        assert!(matches!(
            selected_index(1, Some(1)),
            Err(Fail::InvalidDevice(1, 1))
        ));
        assert_eq!(selected_index(2, Some(1)).unwrap(), 1);
        assert_eq!(selected_index(1, None).unwrap(), 0);
    }

    #[test]
    fn windows_recovery_does_not_prescribe_linux_remedies() {
        for hint in [open_hint("windows"), repl_hint("windows")] {
            assert!(!hint.contains("ModemManager"));
            assert!(!hint.contains("udev"));
        }
        assert!(repl_hint("windows").contains("0.1.1"));
        assert!(open_hint("linux").contains("ModemManager"));
    }
}
