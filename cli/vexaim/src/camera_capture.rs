//! Read-only capture authorization and opt-in maintainer timing diagnostics.
use crate::{
    display::{DisplayConnection, DisplayTransport},
    repl::Fail,
};
use serde_json::{Value, json};
use std::time::{Duration, Instant};
use std::{io::Write, path::PathBuf};
use vex_v5_serial::{
    Connection,
    bluetooth::{BluetoothConnection, BluetoothIoMetrics, FileReadAuthorization},
    generic::GenericConnection,
    protocol::cdc2::file::FileDataReadPacket,
};

pub(crate) trait CaptureTransport: Connection {
    fn capture_metrics(&self) -> Option<BluetoothIoMetrics>;
    async fn authorize_capture(&mut self) -> Result<Option<FileReadAuthorization>, Self::Error>;
    async fn verify_capture(
        &mut self,
        authorization: Option<FileReadAuthorization>,
    ) -> Result<(), Self::Error>;
    async fn send_capture_read(
        &mut self,
        packet: FileDataReadPacket,
        authorization: Option<&FileReadAuthorization>,
    ) -> Result<(), Self::Error>;
}

impl CaptureTransport for BluetoothConnection {
    fn capture_metrics(&self) -> Option<BluetoothIoMetrics> {
        Some(self.io_metrics())
    }
    async fn authorize_capture(&mut self) -> Result<Option<FileReadAuthorization>, Self::Error> {
        self.authorize_file_reads().await.map(Some)
    }
    async fn verify_capture(
        &mut self,
        authorization: Option<FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        if let Some(authorization) = authorization {
            self.verify_file_reads(authorization).await?;
        }
        Ok(())
    }
    async fn send_capture_read(
        &mut self,
        packet: FileDataReadPacket,
        authorization: Option<&FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        match authorization {
            Some(authorization) => self.send_authorized_file_read(authorization, packet).await,
            None => self.send(packet).await,
        }
    }
}

impl CaptureTransport for GenericConnection {
    fn capture_metrics(&self) -> Option<BluetoothIoMetrics> {
        match self {
            Self::Bluetooth(c) => c.capture_metrics(),
            Self::Serial(_) => None,
        }
    }
    async fn authorize_capture(&mut self) -> Result<Option<FileReadAuthorization>, Self::Error> {
        match self {
            Self::Bluetooth(c) => Ok(c.authorize_capture().await?),
            Self::Serial(_) => Ok(None),
        }
    }
    async fn verify_capture(
        &mut self,
        authorization: Option<FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        if let Self::Bluetooth(c) = self {
            c.verify_capture(authorization).await?;
        }
        Ok(())
    }
    async fn send_capture_read(
        &mut self,
        packet: FileDataReadPacket,
        authorization: Option<&FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        match self {
            Self::Bluetooth(c) => Ok(c.send_capture_read(packet, authorization).await?),
            Self::Serial(c) => Ok(c.send(packet).await?),
        }
    }
}

impl<C: CaptureTransport + DisplayTransport> CaptureTransport for DisplayConnection<C>
where
    C::Error: 'static,
{
    fn capture_metrics(&self) -> Option<BluetoothIoMetrics> {
        self.inner().capture_metrics()
    }
    async fn authorize_capture(&mut self) -> Result<Option<FileReadAuthorization>, Self::Error> {
        self.inner_mut().authorize_capture().await
    }
    async fn verify_capture(
        &mut self,
        authorization: Option<FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        self.inner_mut().verify_capture(authorization).await
    }
    async fn send_capture_read(
        &mut self,
        packet: FileDataReadPacket,
        authorization: Option<&FileReadAuthorization>,
    ) -> Result<(), Self::Error> {
        // Keep the owner's display/status scheduling; only the typed file read skips repeated authentication.
        self.tick().await?;
        self.inner_mut()
            .send_capture_read(packet, authorization)
            .await
    }
}

pub(crate) struct Options {
    pub operation_auth: bool,
    pub block_timeout: Duration,
    pub transfer_timeout: Duration,
    pub diagnostic: bool,
    pub report_path: Option<PathBuf>,
    pub payload_window: bool,
    pub reply_pacing: bool,
}

impl Options {
    pub fn selected() -> Result<Self, Fail> {
        let options = Self {
            operation_auth: cfg!(target_os = "windows"),
            block_timeout: Duration::from_secs(3),
            transfer_timeout: Duration::from_secs(crate::bluetooth::CAPTURE_TRANSFER_SECS),
            diagnostic: false,
            report_path: None,
            payload_window: false,
            reply_pacing: false,
        };
        #[cfg(feature = "ble-diagnostics")]
        {
            let mut options = options;
            options.diagnostic = true;
            options.report_path =
                std::env::var_os("VEXAIM_DIAGNOSTIC_CAPTURE_REPORT").map(PathBuf::from);
            options.payload_window = match std::env::var("VEXAIM_DIAGNOSTIC_CAPTURE_WINDOW")
                .ok()
                .as_deref()
            {
                None | Some("legacy") => false,
                Some("payload") => true,
                _ => {
                    return Err(Fail::Bluetooth(
                        "Unknown diagnostic capture window mode".into(),
                    ));
                }
            };
            options.reply_pacing = match std::env::var("VEXAIM_DIAGNOSTIC_CAPTURE_PACING")
                .ok()
                .as_deref()
            {
                None | Some("legacy") => false,
                Some("reply") => true,
                _ => {
                    return Err(Fail::Bluetooth(
                        "Unknown diagnostic capture pacing mode".into(),
                    ));
                }
            };
            options.operation_auth = match std::env::var("VEXAIM_DIAGNOSTIC_CAPTURE_AUTH")
                .ok()
                .as_deref()
            {
                None => options.operation_auth,
                Some("operation") => true,
                Some("packet") => false,
                _ => {
                    return Err(Fail::Bluetooth(
                        "Unknown diagnostic capture authentication mode".into(),
                    ));
                }
            };
            for (key, target, minimum, maximum) in [
                (
                    "VEXAIM_DIAGNOSTIC_CAPTURE_BLOCK_MS",
                    &mut options.block_timeout,
                    500,
                    3000,
                ),
                (
                    "VEXAIM_DIAGNOSTIC_CAPTURE_TOTAL_MS",
                    &mut options.transfer_timeout,
                    1000,
                    240000,
                ),
            ] {
                if let Ok(value) = std::env::var(key) {
                    let value = value
                        .parse::<u64>()
                        .ok()
                        .filter(|v| (minimum..=maximum).contains(v))
                        .ok_or_else(|| {
                            Fail::Bluetooth("Invalid diagnostic capture deadline".into())
                        })?;
                    *target = Duration::from_millis(value);
                }
            }
            return Ok(options);
        }
        #[cfg(not(feature = "ble-diagnostics"))]
        Ok(options)
    }
}

pub(crate) struct Trace {
    started: Instant,
    before: BluetoothIoMetrics,
    enabled: bool,
    report_path: Option<PathBuf>,
    pub report: Value,
}

impl Trace {
    pub fn new(options: &Options, metrics: Option<BluetoothIoMetrics>) -> Self {
        Self {
            started: Instant::now(),
            before: metrics.unwrap_or_default(),
            enabled: options.diagnostic,
            report_path: options.report_path.clone(),
            report: json!({"schema_version":1,"event":"camera_capture_timing","outcome":"interrupted",
                "authentication":if options.operation_auth {"operation"} else {"packet"},
                "payload_window":options.payload_window,"reply_pacing":options.reply_pacing,
                "blocks":0,"bytes_received":0,"block_ms":[]}),
        }
    }
    pub fn finish(&mut self, ok: bool, metrics: Option<BluetoothIoMetrics>) {
        self.report["outcome"] = json!(if ok { "passed" } else { "failed" });
        if let Some(after) = metrics {
            let b = self.before;
            self.report["negotiated_mtu"] = json!(after.mtu);
            self.report["io"] = json!({
                "auth_reads":after.auth_reads.saturating_sub(b.auth_reads), "auth_ms":after.auth_us.saturating_sub(b.auth_us) as f64/1000.,
                "writes":after.writes.saturating_sub(b.writes), "write_ms":after.write_us.saturating_sub(b.write_us) as f64/1000.,
                "pacing_ms":after.pacing_us.saturating_sub(b.pacing_us) as f64/1000.,
                "notifications":after.notifications.saturating_sub(b.notifications),
                "notification_bytes":after.notification_bytes.saturating_sub(b.notification_bytes),
                "authorized_file_reads":after.authorized_file_reads.saturating_sub(b.authorized_file_reads)});
        }
    }
}

impl Drop for Trace {
    fn drop(&mut self) {
        if self.enabled {
            self.report["elapsed_ms"] = json!(self.started.elapsed().as_millis() as u64);
            eprintln!("{}", self.report);
            if let Some(path) = &self.report_path {
                // Only explicit diagnostic builds write this numeric, local JSONL report.
                if let Ok(mut stream) = std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                {
                    let _ = writeln!(stream, "{}", self.report);
                }
            }
        }
    }
}

#[cfg(all(test, not(feature = "ble-diagnostics")))]
mod tests {
    use super::*;
    #[test]
    fn normal_capture_uses_only_the_hardware_checked_optimization() {
        let options = Options::selected().unwrap();
        assert_eq!(options.operation_auth, cfg!(target_os = "windows"));
        assert!(!options.payload_window);
        assert!(!options.reply_pacing);
        assert!(!options.diagnostic);
        assert!(options.report_path.is_none());
    }
}
