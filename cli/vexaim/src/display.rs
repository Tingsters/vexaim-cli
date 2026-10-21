//! One connection owner serializes all display keepalive and ordinary traffic.
use crate::repl::{Fail, is_timeout};
use serde_json::Value;
use std::time::{Duration, Instant};
use vex_v5_serial::{
    Connection, ConnectionType,
    protocol::{
        cdc::{CdcCommand, CdcReply},
        cdc2::aim::{RemoteDisplayPacket, RemoteStatusPacket, ScreenStatusPacket},
    },
};

const PERIOD: Duration = Duration::from_millis(100);
const LEASE: Duration = Duration::from_secs(60);
pub trait DisplayTransport: Connection {
    async fn poll_display(&mut self) -> Result<(), Self::Error> {
        self.send(RemoteStatusPacket).await
    }
}
impl DisplayTransport for vex_v5_serial::bluetooth::BluetoothConnection {
    async fn poll_display(&mut self) -> Result<(), Self::Error> {
        self.poll_aim_remote_status().await
    }
}
impl DisplayTransport for vex_v5_serial::generic::GenericConnection {
    async fn poll_display(&mut self) -> Result<(), Self::Error> {
        match self {
            Self::Bluetooth(conn) => Ok(conn.poll_aim_remote_status().await?),
            Self::Serial(_) => self.send(RemoteStatusPacket).await,
        }
    }
}
impl<C: DisplayTransport> DisplayTransport for &mut C {
    async fn poll_display(&mut self) -> Result<(), Self::Error> {
        (**self).poll_display().await
    }
}
pub fn program_uses_display(source: &str) -> bool {
    source.contains(".screen")
}
pub struct DisplayConnection<C> {
    inner: C,
    active: bool,
    last: Instant,
    idle_deadline: Instant,
}
impl<C: DisplayTransport> DisplayConnection<C>
where
    C::Error: 'static,
{
    pub fn new(inner: C) -> Self {
        Self {
            inner,
            active: false,
            last: Instant::now(),
            idle_deadline: Instant::now(),
        }
    }
    pub fn inner(&self) -> &C {
        &self.inner
    }
    pub fn inner_mut(&mut self) -> &mut C {
        &mut self.inner
    }
    pub fn active(&self) -> bool {
        self.active
    }
    fn touch(&mut self) {
        self.idle_deadline = Instant::now() + LEASE;
    }
    pub async fn foreground(&mut self) -> Result<bool, Fail> {
        if !self.active {
            return Ok(false);
        }
        let status = self
            .handshake(ScreenStatusPacket, Duration::from_millis(250), 0)
            .await
            .map_err(|e| Fail::Session(e.to_string()))?
            .map_err(|e| Fail::Session(e.to_string()))?;
        if status.screen_id == 20 {
            return Ok(true);
        }
        // The student may have left the program through the physical menus.
        // Stop polling; only a fresh display request may activate it again.
        self.active = false;
        Ok(false)
    }
    pub async fn enable(&mut self, identity: &Value) -> Result<(), Fail> {
        if !self.inner.connection_type().is_bluetooth() {
            return Ok(());
        }
        if identity["model"] != "AIM"
            || identity["hardware"] != "REV1"
            || identity["firmware"] != "1.0.0.b0"
        {
            return Err(Fail::Session(
                "Remote display is verified only for AIM REV1 / BLE firmware 1.0.0.b0".into(),
            ));
        }
        self.touch();
        if self.active {
            return Ok(());
        }
        // No ACK is returned on the tested BLE path. Send start once, then
        // verify program screen 20 independently through ordinary SYS_STATUS.
        self.active = true;
        self.last = Instant::now() - PERIOD;
        self.inner
            .send(RemoteDisplayPacket { start: true })
            .await
            .map_err(|e| Fail::Session(e.to_string()))?;
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            self.tick()
                .await
                .map_err(|e| Fail::Session(e.to_string()))?;
            let status = self
                .handshake(ScreenStatusPacket, Duration::from_millis(250), 0)
                .await
                .map_err(|e| Fail::Session(e.to_string()))?
                .map_err(|e| Fail::Session(e.to_string()))?;
            if status.screen_id == 20 {
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err(Fail::Session("Display activation was sent once, but the AIM program screen was not confirmed; no drawing was replayed".into()));
            }
            smol::Timer::after(PERIOD).await;
        }
    }
    pub async fn disable(&mut self) -> Result<(), C::Error> {
        let was_active = self.pause();
        if was_active {
            self.finish_stop().await?;
        }
        Ok(())
    }
    pub fn pause(&mut self) -> bool {
        std::mem::replace(&mut self.active, false)
    }
    pub async fn finish_stop(&mut self) -> Result<(), C::Error> {
        tokio::time::timeout(
            Duration::from_millis(500),
            self.inner.send(RemoteDisplayPacket { start: false }),
        )
        .await
        .map_err(|_| C::Error::from(vex_v5_serial::protocol::cdc2::Cdc2Ack::Timeout))?
    }
    pub async fn tick(&mut self) -> Result<(), C::Error> {
        if self.active && self.last.elapsed() >= PERIOD {
            self.last = Instant::now();
            let result =
                tokio::time::timeout(Duration::from_millis(500), self.inner.poll_display())
                    .await
                    .unwrap_or_else(|_| {
                        Err(C::Error::from(
                            vex_v5_serial::protocol::cdc2::Cdc2Ack::Timeout,
                        ))
                    });
            if let Err(e) = result {
                self.active = false;
                return Err(e);
            }
        }
        Ok(())
    }
    pub async fn idle(&mut self) -> Result<(), C::Error> {
        if self.active && Instant::now() >= self.idle_deadline {
            return self.disable().await;
        }
        self.tick().await
    }
}
impl<C: DisplayTransport> Connection for DisplayConnection<C>
where
    C::Error: 'static,
{
    type Error = C::Error;
    fn connection_type(&self) -> ConnectionType {
        self.inner.connection_type()
    }
    async fn send(&mut self, packet: impl CdcCommand) -> Result<(), Self::Error> {
        self.touch();
        self.tick().await?;
        self.inner.send(packet).await
    }
    async fn recv<P: CdcReply>(&mut self, timeout: Duration) -> Result<P, Self::Error> {
        let deadline = Instant::now() + timeout;
        loop {
            self.touch();
            self.tick().await?;
            let remaining = deadline.saturating_duration_since(Instant::now());
            let result = self
                .inner
                .recv(if self.active {
                    remaining.min(PERIOD)
                } else {
                    remaining
                })
                .await;
            match result {
                Err(e) if self.active && is_timeout(&e) && Instant::now() < deadline => continue,
                other => return other,
            }
        }
    }
    async fn read_user(&mut self, buf: &mut [u8]) -> Result<usize, Self::Error> {
        self.touch();
        self.tick().await?;
        self.inner.read_user(buf).await
    }
    async fn write_user(&mut self, buf: &[u8]) -> Result<usize, Self::Error> {
        self.touch();
        self.tick().await?;
        self.inner.write_user(buf).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::VecDeque;
    use vex_v5_serial::{
        bluetooth::BluetoothError,
        generic::GenericError,
        protocol::{VEX_CRC16, cdc2::Cdc2Ack},
    };

    #[derive(Default)]
    struct Radio {
        sent: Vec<Vec<u8>>,
        replies: VecDeque<Option<Vec<u8>>>,
        fail_send: bool,
    }
    impl DisplayTransport for Radio {}
    impl Connection for Radio {
        type Error = GenericError;
        fn connection_type(&self) -> ConnectionType {
            ConnectionType::Bluetooth
        }
        async fn send(&mut self, p: impl CdcCommand) -> Result<(), Self::Error> {
            let mut bytes = vec![0; p.size()];
            p.encode(&mut bytes);
            self.sent.push(bytes);
            if self.fail_send {
                return Err(BluetoothError::Timeout.into());
            }
            Ok(())
        }
        async fn recv<P: CdcReply>(&mut self, timeout: Duration) -> Result<P, Self::Error> {
            match self.replies.pop_front().flatten() {
                Some(bytes) => Ok(P::decode(&mut bytes.as_slice())?),
                None => {
                    tokio::time::sleep(timeout).await;
                    Err(BluetoothError::Timeout.into())
                }
            }
        }
        async fn read_user(&mut self, _: &mut [u8]) -> Result<usize, Self::Error> {
            Ok(0)
        }
        async fn write_user(&mut self, buf: &[u8]) -> Result<usize, Self::Error> {
            Ok(buf.len())
        }
    }
    fn status(screen: u8) -> Vec<u8> {
        let mut bytes = vec![0xaa, 0x55, 0x56, 11, 0x20, 0x76, 4, 6, 17, screen, 5, 9, 32];
        bytes.extend_from_slice(&VEX_CRC16.checksum(&bytes).to_be_bytes());
        bytes
    }
    fn identity() -> Value {
        json!({"model":"AIM","hardware":"REV1","firmware":"1.0.0.b0"})
    }
    fn ready() -> DisplayConnection<Radio> {
        let mut radio = Radio::default();
        radio.replies.push_back(Some(status(20)));
        DisplayConnection::new(radio)
    }
    fn count(c: &DisplayConnection<Radio>, family: u8, opcode: u8) -> usize {
        c.inner
            .sent
            .iter()
            .filter(|b| b[4] == family && b[5] == opcode)
            .count()
    }
    #[tokio::test]
    async fn activates_once_and_keeps_existing_connection() {
        let mut c = ready();
        c.enable(&identity()).await.unwrap();
        c.enable(&identity()).await.unwrap();
        assert!(c.active());
        assert_eq!(count(&c, 0x57, 0x7f), 1);
        assert_eq!(count(&c, 0x56, 0x20), 1);
        c.last = Instant::now() - PERIOD;
        c.idle().await.unwrap();
        assert!(count(&c, 0x57, 0x7e) >= 2);
    }
    #[tokio::test]
    async fn manual_menu_exit_requires_a_fresh_display_request() {
        let mut c = ready();
        c.enable(&identity()).await.unwrap();
        c.inner.replies.push_back(Some(status(0)));
        assert!(!c.foreground().await.unwrap());
        assert!(!c.active());
        c.idle().await.unwrap();
        assert_eq!(count(&c, 0x57, 0x7f), 1);
        c.inner.replies.push_back(Some(status(20)));
        c.enable(&identity()).await.unwrap();
        assert_eq!(count(&c, 0x57, 0x7f), 2);
    }
    #[tokio::test]
    async fn rejects_unknown_firmware_without_writes() {
        let mut c = ready();
        let mut id = identity();
        id["firmware"] = json!("new");
        assert!(c.enable(&id).await.is_err());
        assert!(c.inner.sent.is_empty());
        assert!(!c.active());
    }
    #[tokio::test]
    async fn normal_state_and_camera_traffic_does_not_activate_display() {
        let mut c = ready();
        c.send(ScreenStatusPacket).await.unwrap();
        c.read_user(&mut [0; 8]).await.unwrap();
        c.idle().await.unwrap();
        assert!(!c.active());
        assert_eq!(count(&c, 0x57, 0x7f), 0);
        assert_eq!(count(&c, 0x57, 0x7e), 0);
    }
    #[tokio::test]
    async fn stop_is_once_and_idle_lease_expires() {
        let mut c = ready();
        c.enable(&identity()).await.unwrap();
        c.idle_deadline = Instant::now() - PERIOD;
        c.idle().await.unwrap();
        c.idle().await.unwrap();
        c.disable().await.unwrap();
        assert!(!c.active());
        assert_eq!(count(&c, 0x57, 0x7f), 2);
        assert_eq!(c.inner.sent.last().unwrap()[8], 0x1a);
    }
    #[tokio::test]
    async fn failed_keepalive_disables_itself_without_retry() {
        let mut c = ready();
        c.enable(&identity()).await.unwrap();
        c.inner.fail_send = true;
        c.last = Instant::now() - PERIOD;
        assert!(c.tick().await.is_err());
        let sent = c.inner.sent.len();
        c.tick().await.unwrap();
        assert!(!c.active());
        assert_eq!(c.inner.sent.len(), sent);
    }
    #[tokio::test]
    async fn camera_wait_interleaves_keepalive_without_restarting_or_replaying() {
        let mut c = ready();
        c.enable(&identity()).await.unwrap();
        c.inner.replies.extend([None, None, None, Some(status(20))]);
        let result: Result<_, Cdc2Ack> = c
            .recv::<Result<vex_v5_serial::protocol::cdc2::aim::ScreenStatusReply, Cdc2Ack>>(
                Duration::from_millis(700),
            )
            .await
            .unwrap();
        assert_eq!(result.unwrap().screen_id, 20);
        assert!(count(&c, 0x57, 0x7e) >= 3);
        assert_eq!(count(&c, 0x57, 0x7f), 1);
    }
    #[tokio::test]
    async fn activation_rejection_leaves_cleanup_possible_and_never_restarts() {
        let mut c = ready();
        let mut nack = status(20);
        nack[5] = 0xff;
        let crc = VEX_CRC16.checksum(&nack[..13]);
        nack[13..].copy_from_slice(&crc.to_be_bytes());
        c.inner.replies.clear();
        c.inner.replies.push_back(Some(nack));
        assert!(c.enable(&identity()).await.is_err());
        c.disable().await.unwrap();
        assert_eq!(count(&c, 0x57, 0x7f), 2);
        assert!(!c.active());
    }
    #[test]
    fn ordinary_exec_does_not_need_a_display_program() {
        assert!(!program_uses_display("print(robot.get_battery_level())"));
        assert!(program_uses_display("robot.screen.show_emoji(HAPPY)"));
        assert!(program_uses_display(
            "screen = robot.screen\nscreen.print('hi')"
        ));
    }
}
