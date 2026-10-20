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

pub const PREAMBLE: &str = "try:\n    robot\nexcept NameError:\n    from vex import *\n    from vex_globals import *\n    robot = Robot()\n";

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
}

impl std::fmt::Display for Fail {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Fail::NoRobot => write!(
                f,
                "no VEX device found: check the USB cable is plugged in and carries data, and the robot is on"
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
        }
    }
}

fn is_disconnect(e: &str) -> bool {
    let e = e.to_lowercase();
    e.contains("broken pipe") || e.contains("no such device") || e.contains("input/output error")
}

pub fn devices() -> Result<Vec<SerialDevice>, Fail> {
    match serial::find_devices() {
        Ok(d) => Ok(d),
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

fn is_timeout(e: &(dyn std::error::Error + 'static)) -> bool {
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

fn complete_raw_frame(b: &[u8]) -> bool {
    // BLE can deliver the final '>' in its own notification. Consume it before
    // the next command, otherwise that delayed prompt corrupts the next 'OK'.
    b.starts_with(b"OK") && frame_end(b).is_some_and(|(_, end)| b.get(end + 1) == Some(&b'>'))
}

fn parse_frame(b: &[u8]) -> (String, String) {
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
