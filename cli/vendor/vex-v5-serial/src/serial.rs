//! Implements discovering, opening, and interacting with vex devices connected over USB. This module does not have async support.

use futures_util::{AsyncReadExt, AsyncWriteExt, FutureExt, io::BufReader};
use log::{debug, error, trace, warn};
use std::time::Duration;
use thiserror::Error;
use vex_cdc::{
    Decode, DecodeError, Encode, FixedString, FixedStringSizeError, VarU16,
    cdc::CdcReply,
    cdc2::{Cdc2Ack, system::UserDataPacket},
};

// these are re-exported so consumers can access USB port info, because SerialPortType must be named to unwrap UsbPortInfo
pub use serialport::{SerialPortInfo, SerialPortType, UsbPortInfo};

use crate::{Connection, ConnectionType, RawPacket, trim_packets};

/// The USB vendor ID for VEX devices
pub const VEX_USB_VID: u16 = 0x2888;

/// The USB PID of the V5 Brain
pub const V5_BRAIN_USB_PID: u16 = 0x0501;

/// The USB PID of the EXP Brain
pub const EXP_BRAIN_USB_PID: u16 = 0x600;

/// The USB PID of the V5 Controller
pub const V5_CONTROLLER_USB_PID: u16 = 0x0503;

pub const AIR_HORNET_USB_PID: u16 = 0x0a00;

pub const AIR_CONTROLLER_USB_PID: u16 = 0x0a10;

pub const AIM_USB_PID: u16 = 0x0700;

/// USB interface number of the AIM's user serial port (interfaces 2-3 are a UVC camera).
const AIM_USER_INTERFACE: u8 = 4;

pub const AIV_USB_PID: u16 = 0x0800;

pub const V5_SERIAL_BAUDRATE: u32 = 115200;

/// Async serial port handle.
///
/// On Unix this is `async-serial`'s non-blocking TTY adapter. `async-serial` cannot compile on Windows
/// (it imports `std::os::fd`), and `async-io` cannot poll COM ports, so on Windows (or with the `blocking-io`
/// feature, which lets the same code be tested on any OS) a blocking `serialport` handle is driven on a
/// thread pool through `blocking::Unblock`.
#[cfg(not(any(windows, feature = "blocking-io")))]
type AsyncSerialPort = async_serial::AsyncSerialPort;
#[cfg(any(windows, feature = "blocking-io"))]
type AsyncSerialPort = split::SplitPort;

/// Thread-pool adapter used where `async-serial` is unavailable.
///
/// Reads and writes use separate clones of the port handle. A single `blocking::Unblock` reads ahead in the
/// background; when that read hits the port's timeout, the error would otherwise be reported by the *next write*.
#[cfg(any(windows, feature = "blocking-io"))]
mod split {
    use blocking::Unblock;
    use futures_util::io::{AsyncRead, AsyncWrite};
    use std::{
        io,
        pin::Pin,
        task::{Context, Poll},
    };

    #[derive(Debug)]
    pub struct SplitPort {
        read: Unblock<Box<dyn serialport::SerialPort>>,
        write: Unblock<Box<dyn serialport::SerialPort>>,
    }

    impl SplitPort {
        pub fn new(port: Box<dyn serialport::SerialPort>) -> serialport::Result<Self> {
            let write = port.try_clone()?;
            Ok(Self {
                read: Unblock::new(port),
                write: Unblock::new(write),
            })
        }
    }

    impl AsyncRead for SplitPort {
        fn poll_read(mut self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &mut [u8]) -> Poll<io::Result<usize>> {
            Pin::new(&mut self.read).poll_read(cx, buf)
        }
    }

    impl AsyncWrite for SplitPort {
        fn poll_write(mut self: Pin<&mut Self>, cx: &mut Context<'_>, buf: &[u8]) -> Poll<io::Result<usize>> {
            Pin::new(&mut self.write).poll_write(cx, buf)
        }
        fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Pin::new(&mut self.write).poll_flush(cx)
        }
        fn poll_close(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
            Pin::new(&mut self.write).poll_close(cx)
        }
    }
}

#[cfg(not(any(windows, feature = "blocking-io")))]
fn open_port(info: &VexSerialPort, timeout: Duration) -> Result<AsyncSerialPort, SerialError> {
    use async_serial::AsyncSerialPortBuilder;
    Ok(async_serial::new(&info.port_info.port_name, V5_SERIAL_BAUDRATE)
        .timeout(timeout)
        .parity(serialport::Parity::None)
        .stop_bits(serialport::StopBits::One)
        .open_async()?)
}

#[cfg(any(windows, feature = "blocking-io"))]
fn open_port(info: &VexSerialPort, timeout: Duration) -> Result<AsyncSerialPort, SerialError> {
    let name = &info.port_info.port_name;
    let mut port = serialport::new(name, V5_SERIAL_BAUDRATE)
        .timeout(timeout)
        .data_bits(serialport::DataBits::Eight)
        .flow_control(serialport::FlowControl::None)
        .parity(serialport::Parity::None)
        .stop_bits(serialport::StopBits::One)
        .open()
        .map_err(|source| SerialError::PortSetup { port: name.clone(), operation: "open", source })?;
    prepare_user_port(info, cfg!(windows), |level| port.write_data_terminal_ready(level))?;
    Ok(split::SplitPort::new(port)?)
}

// Keep DTR setup checked: SerialPortBuilder::dtr_on_open is only best-effort.
// Linux asserts DTR on open; Windows leaves it low and the AIM's REPL stays silent.
#[cfg(any(windows, feature = "blocking-io", test))]
fn prepare_user_port(
    info: &VexSerialPort,
    windows: bool,
    mut set_dtr: impl FnMut(bool) -> serialport::Result<()>,
) -> Result<(), SerialError> {
    let aim = matches!(&info.port_info.port_type,
        SerialPortType::UsbPort(usb) if usb.vid == VEX_USB_VID && usb.pid == AIM_USB_PID);
    if windows && aim && info.port_type == VexSerialPortType::User {
        set_dtr(true).map_err(|source| SerialError::PortSetup {
            port: info.port_info.port_name.clone(),
            operation: "assert DTR for the AIM MicroPython REPL",
            source,
        })?;
    }
    Ok(())
}

/// The information of a generic vex serial port
#[derive(Clone, Debug)]
pub struct VexSerialPort {
    pub port_info: serialport::SerialPortInfo,
    pub port_type: VexSerialPortType,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum VexSerialPortType {
    User,
    System,
    Controller,
}

/// Assigns port types by port location.
/// Windows reports the USB MI interface number with `usbportinfo-interface` enabled.
fn types_by_location(ports: &[SerialPortInfo]) -> Option<Vec<VexSerialPort>> {
    debug!("Attempting to infer serial port types by port location.");
    let mut vex_ports = Vec::new();

    for port in ports {
        // Get the info about the usb connection
        // This is always going to succeed because of earlier code.
        let SerialPortType::UsbPort(info) = port.clone().port_type else {
            continue;
        };

        if cfg!(target_os = "macos") && port.port_name.starts_with("/dev/tty.") {
            // https://pbxbook.com/other/mac-tty.html
            debug!(
                "Ignoring port named {:?} because it is a call-in device",
                port.port_name
            );
            continue;
        }

        match info.pid {
            V5_CONTROLLER_USB_PID => vex_ports.push(VexSerialPort {
                port_info: port.clone(),
                port_type: VexSerialPortType::Controller,
            }),
            V5_BRAIN_USB_PID
            | EXP_BRAIN_USB_PID
            | AIR_CONTROLLER_USB_PID
            | AIR_HORNET_USB_PID
            | AIM_USB_PID
            | AIV_USB_PID => {
                if let Some(mut location) = info.interface {
                    if cfg!(target_os = "macos") {
                        location -= 1; // macOS is 1-indexed
                    }

                    // The AIM exposes a UVC camera on interfaces 2 and 3, so its user
                    // (REPL/console) serial port is interface 4 rather than 2.
                    if info.pid == AIM_USB_PID && location == AIM_USER_INTERFACE {
                        debug!("Found a 'user' serial port over an AIM connection.");
                        vex_ports.push(VexSerialPort {
                            port_info: port.clone(),
                            port_type: VexSerialPortType::User,
                        });
                        continue;
                    }

                    match location {
                        0 => {
                            debug!("Found a 'system' serial port over a Brain connection.");
                            vex_ports.push(VexSerialPort {
                                port_info: port.clone(),
                                port_type: VexSerialPortType::System,
                            })
                        }
                        1 => warn!(
                            "Found a controller serial port over a Brain connection! Things are most likely broken."
                        ),
                        2 => {
                            debug!("Found a 'user' serial port over a Brain connection.");
                            vex_ports.push(VexSerialPort {
                                port_info: port.clone(),
                                port_type: VexSerialPortType::User,
                            })
                        }
                        _ => warn!("Unknown location for V5 device: {}", location),
                    }
                }
            }
            // Unknown product
            _ => {}
        }
    }

    // If nothing was recognised by location, return `None` so the name-based fallbacks can run.
    if vex_ports.is_empty() {
        return None;
    }

    Some(vex_ports)
}

/// Assign port types based on the last character of the port name.
/// This is the fallback option for macOS.
/// This is a band-aid solution and will become obsolete once serialport correctly gets the interface number.
fn types_by_name_darwin(ports: &[SerialPortInfo]) -> Option<Vec<VexSerialPort>> {
    assert!(cfg!(target_os = "macos"));

    debug!("Attempting to infer serial port types by name. (Darwin fallback)");
    let mut vex_ports = Vec::new();

    for port in ports {
        if cfg!(target_os = "macos") && port.port_name.starts_with("/dev/tty.") {
            // https://pbxbook.com/other/mac-tty.html
            debug!(
                "Ignoring port named {:?} because it is a call-in device",
                port.port_name
            );
            continue;
        }

        let Some(interface) = port.port_name.chars().last() else {
            continue;
        };
        match interface {
            '1' => {
                debug!("Found a 'system' serial port over a Brain connection.");
                vex_ports.push(VexSerialPort {
                    port_info: port.clone(),
                    port_type: VexSerialPortType::System,
                });
            }
            '2' => {
                debug!("Found a controller serial port.");
                vex_ports.push(VexSerialPort {
                    port_info: port.clone(),
                    port_type: VexSerialPortType::Controller,
                });
            }
            '3' => {
                debug!("Found a 'user' serial port over a Brain connection.");
                vex_ports.push(VexSerialPort {
                    port_info: port.clone(),
                    port_type: VexSerialPortType::User,
                });
            }
            _ => {
                warn!("Unknown location for V5 device: {}", interface);
            }
        }
    }

    Some(vex_ports)
}

/// Infers port type by numerically sorting port product names.
/// This is the fallback option for windows.
/// The lower number port name is usually the user port according to pros-cli comments:
/// [https://github.com/purduesigbots/pros-cli/blob/develop/pros/serial/devices/vex/v5_device.py#L75]
fn types_by_name_order(ports: &[SerialPortInfo]) -> Option<Vec<VexSerialPort>> {
    debug!("Attempting to infer serial port types by order. (Windows fallback)");
    if ports.len() != 2 {
        return None;
    }

    let mut vex_ports = Vec::new();

    let mut sorted_ports = ports.to_vec();
    // Sort by product name
    sorted_ports.sort_by_key(|info| info.port_name.clone());
    sorted_ports.reverse();

    // Higher Port
    vex_ports.push(VexSerialPort {
        port_info: sorted_ports.pop().unwrap(),
        port_type: VexSerialPortType::System,
    });
    // Lower port
    vex_ports.push(VexSerialPort {
        port_info: sorted_ports.pop().unwrap(),
        port_type: VexSerialPortType::User,
    });

    // If we could not infer the type of all connections, fail
    if vex_ports.len() != ports.len() {
        return None;
    }

    Some(vex_ports)
}

/// Finds all available VEX serial ports that can be connected to.
fn find_ports() -> Result<Vec<VexSerialPort>, SerialError> {
    // Get all available serial ports
    let ports = serialport::available_ports()?;

    // Create a vector that will contain all vex ports
    let mut filtered_ports = Vec::new();

    // Iterate over all available ports
    for port in ports {
        // Get the serial port's info as long as it is a usb port.
        // If it is not a USB port, ignore it.
        let SerialPortType::UsbPort(port_info) = port.clone().port_type else {
            continue;
        };

        // If the Vendor ID does not match the VEX Vendor ID, then skip it
        if port_info.vid != VEX_USB_VID {
            continue;
        }

        filtered_ports.push(port);
    }

    let vex_ports = types_by_location(&filtered_ports)
        .or_else(|| {
            if cfg!(target_os = "macos") {
                types_by_name_darwin(&filtered_ports)
            } else {
                types_by_name_order(&filtered_ports)
            }
        })
        .ok_or(SerialError::CouldntInferTypes)?;

    Ok(vex_ports)
}

/// Finds all connected V5 devices.
pub fn find_devices() -> Result<Vec<SerialDevice>, SerialError> {
    // Find all vex ports, iterate using peekable.
    let mut ports = find_ports()?.into_iter().peekable();

    // Create a vector of all vex devices
    let mut devices = Vec::<SerialDevice>::new();

    // Manually use a while loop to iterate, so that we can peek and pop ahead
    while let Some(port) = ports.next() {
        // Find out what type it is so we can assign devices
        match port.port_type {
            VexSerialPortType::System => {
                // Peek the next port. If it is a user port, add it to a brain device. If not, add it to an unknown device
                if match ports.peek() {
                    Some(p) => p.port_type == VexSerialPortType::User,
                    _ => false,
                } {
                    devices.push(SerialDevice {
                        system_port: port,
                        user_port: ports.next(),
                    });
                } else {
                    devices.push(SerialDevice {
                        system_port: port,
                        user_port: None,
                    });
                }
            }
            VexSerialPortType::User => {
                // If it is a user port, do the same thing we do with a system port. Except ignore it if there is no other port.
                if match ports.peek() {
                    Some(p) => p.port_type == VexSerialPortType::System,
                    _ => false,
                } {
                    devices.push(SerialDevice {
                        system_port: ports.next().unwrap(),
                        user_port: Some(port),
                    });
                }
            }
            VexSerialPortType::Controller => devices.push(SerialDevice {
                system_port: port,
                user_port: None,
            }),
        }
    }

    // Return the devices
    Ok(devices)
}

#[derive(Clone, Debug)]
pub struct SerialDevice {
    system_port: VexSerialPort,
    user_port: Option<VexSerialPort>,
}

impl SerialDevice {
    pub fn connect(&self, timeout: Duration) -> Result<SerialConnection, SerialError> {
        SerialConnection::open(self.clone(), timeout)
    }

    pub fn system_port(&self) -> &VexSerialPort {
        &self.system_port
    }

    pub fn user_port(&self) -> Option<&VexSerialPort> {
        self.user_port.as_ref()
    }
}

/// An open serial connection to a V5 device.
#[derive(Debug)]
pub struct SerialConnection {
    system_port: (VexSerialPort, AsyncSerialPort),
    user_port: Option<(VexSerialPort, BufReader<AsyncSerialPort>)>,
    incoming_packets: Vec<RawPacket>,
}

impl SerialConnection {
    /// Opens a new serial connection to a V5 Brain.
    pub fn open(device: SerialDevice, timeout: Duration) -> Result<Self, SerialError> {
        Ok(Self {
            system_port: {
                let stream = open_port(&device.system_port, timeout)?;

                (device.system_port, stream)
            },
            user_port: if let Some(port) = device.user_port {
                let stream = open_port(&port, timeout)?;

                Some((port, BufReader::new(stream)))
            } else {
                None
            },
            incoming_packets: Default::default(),
        })
    }

    pub fn system_port(&self) -> &VexSerialPort {
        &self.system_port.0
    }

    pub fn user_port(&self) -> Option<&VexSerialPort> {
        self.user_port.as_ref().map(|port| &port.0)
    }

    /// Receives a single packet from the serial port and adds it to the queue of incoming packets.
    async fn receive_one_packet(&mut self) -> Result<(), SerialError> {
        // Read the header into an array
        let mut header = [0u8; 2];
        self.system_port.1.read_exact(&mut header).await?;

        // Verify that the header is valid
        if header != [0xAA, 0x55] {
            warn!("Skipping packet with invalid header: {:x?}.", header,);
            return Ok(());
        }

        // Create a buffer to store the entire packet
        let mut packet = Vec::from(header);

        let mut byte_buf = [0_u8; 1];

        // Push the command's ID
        packet.push({
            self.system_port.1.read_exact(&mut byte_buf).await?;
            byte_buf[0]
        });

        // Get the size of the packet
        // We do some extra logic to make sure we only read the necessary amount of bytes
        let first_size_byte = {
            self.system_port.1.read_exact(&mut byte_buf).await?;
            byte_buf[0]
        };
        let size = if VarU16::check_wide(first_size_byte) {
            let second_size_byte = {
                self.system_port.1.read_exact(&mut byte_buf).await?;
                byte_buf[0]
            };
            packet.extend([first_size_byte, second_size_byte]);

            // Decode the size of the packet
            VarU16::decode(&mut [first_size_byte, second_size_byte].as_slice())?
        } else {
            packet.push(first_size_byte);

            // Decode the size of the packet
            VarU16::decode(&mut [first_size_byte].as_slice())?
        }
        .into_inner() as usize;

        // Read the rest of the packet
        let mut payload = vec![0; size];
        self.system_port.1.read_exact(&mut payload).await?;

        // Completely fill the packet
        packet.extend(payload);

        trace!("received packet: {:x?}", packet);

        // Push the packet to the incoming packets buffer
        self.incoming_packets.push(RawPacket::new(packet));

        Ok(())
    }
}

impl Connection for SerialConnection {
    type Error = SerialError;

    fn connection_type(&self) -> ConnectionType {
        if self.user_port.is_some() {
            ConnectionType::Wired
        } else {
            ConnectionType::Controller
        }
    }

    async fn send(&mut self, packet: impl Encode) -> Result<(), SerialError> {
        // Encode the packet
        let mut encoded = vec![0; packet.size()];
        packet.encode(&mut encoded);

        trace!("sent packet: {:x?}", encoded);

        // Write the packet to the serial port
        match self.system_port.1.write_all(&encoded).await {
            Ok(_) => (),
            Err(e) => return Err(SerialError::IoError(e)),
        };

        match self.system_port.1.flush().await {
            Ok(_) => (),
            Err(e) => return Err(SerialError::IoError(e)),
        };

        Ok(())
    }

    async fn recv<P: CdcReply>(&mut self, timeout: Duration) -> Result<P, SerialError> {
        // Return an error if the right packet is not received within the timeout
        futures_util::select! {
            result = async {
                loop {
                    for packet in self.incoming_packets.iter_mut() {
                        match packet.decode_and_use::<P>() {
                            Some(Ok(decoded)) => {
                                trim_packets(&mut self.incoming_packets);
                                return Ok(decoded);
                            }
                            Some(Err(e)) => {
                                error!("Failed to decode packet with valid header: {}", e);
                                packet.used = true;
                                return Err(SerialError::DecodeError(e));
                            }
                            None => {}
                        }
                    }

                    trim_packets(&mut self.incoming_packets);
                    self.receive_one_packet().await?;
                }
            }.fuse() => result,
            _ = async_io::Timer::after(timeout).fuse() => Err(SerialError::Timeout)
        }
    }

    async fn read_user(&mut self, buf: &mut [u8]) -> Result<usize, SerialError> {
        if let Some((_, user_port)) = &mut self.user_port {
            Ok(user_port.read(buf).await?)
        } else {
            let mut data = Vec::new();
            loop {
                let fifo = self
                    .handshake(
                        UserDataPacket {
                            channel: 1, // stdio channel
                            write: None,
                        },
                        Duration::from_millis(100),
                        1,
                    )
                    .await??;
                if let Some(read) = fifo.data {
                    data.extend(read.as_bytes());
                    break;
                }
            }

            let len = data.len().min(buf.len());
            buf[..len].copy_from_slice(&data[..len]);

            Ok(len)
        }
    }

    async fn write_user(&mut self, mut buf: &[u8]) -> Result<usize, SerialError> {
        if let Some((_, user_port)) = &mut self.user_port {
            // `write` may accept only part of the buffer; make sure all of it goes out.
            user_port.write_all(buf).await?;
            user_port.flush().await?;
            Ok(buf.len())
        } else {
            let buf_len = buf.len();
            while !buf.is_empty() {
                let (chunk, rest) = buf.split_at(std::cmp::min(224, buf.len()));
                _ = self
                    .handshake(
                        UserDataPacket {
                            channel: 2, // stdio channel
                            write: Some(
                                FixedString::new(String::from_utf8(chunk.to_vec()).unwrap())
                                    .unwrap(),
                            ),
                        },
                        Duration::from_millis(100),
                        1,
                    )
                    .await??;
                buf = rest;
            }

            Ok(buf_len)
        }
    }
}

#[derive(Error, Debug)]
pub enum SerialError {
    #[error("could not {operation} on {port}: {source}")]
    PortSetup {
        port: String,
        operation: &'static str,
        #[source]
        source: serialport::Error,
    },

    #[error("IO Error: {0}")]
    IoError(#[from] std::io::Error),

    #[error("Packet decoding error: {0}")]
    DecodeError(#[from] DecodeError),

    #[error("Packet timeout")]
    Timeout,

    #[error("NACK received: {0:?}")]
    Nack(#[from] Cdc2Ack),

    #[error("Serialport Error")]
    SerialportError(#[from] serialport::Error),

    #[error("Could not infer serial port types")]
    CouldntInferTypes,

    #[error(transparent)]
    FixedStringSizeError(#[from] FixedStringSizeError),
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `serialport` reports the CDC *data* interface on macOS (communication interface + 1) and
    /// `types_by_location()` compensates for that, so feed it numbers the way each OS reports them.
    fn reported(interface: u8) -> u8 {
        if cfg!(target_os = "macos") {
            interface + 1
        } else {
            interface
        }
    }

    fn usb_port(name: &str, pid: u16, interface: u8) -> SerialPortInfo {
        SerialPortInfo {
            port_name: name.to_string(),
            port_type: SerialPortType::UsbPort(UsbPortInfo {
                vid: VEX_USB_VID,
                pid,
                serial_number: None,
                manufacturer: None,
                product: None,
                interface: Some(reported(interface)),
            }),
        }
    }

    #[test]
    fn aim_interfaces_0_and_4_are_system_and_user() {
        let ports = [
            usb_port("/dev/ttyACM0", AIM_USB_PID, 0),
            usb_port("/dev/ttyACM1", AIM_USB_PID, 4),
        ];
        let found = types_by_location(&ports).unwrap();
        assert_eq!(found.len(), 2);
        assert_eq!(found[0].port_type, VexSerialPortType::System);
        assert_eq!(found[1].port_type, VexSerialPortType::User);
    }

    #[test]
    fn brain_interfaces_0_and_2_still_work() {
        let ports = [
            usb_port("/dev/ttyACM0", V5_BRAIN_USB_PID, 0),
            usb_port("/dev/ttyACM1", V5_BRAIN_USB_PID, 2),
        ];
        let found = types_by_location(&ports).unwrap();
        assert_eq!(found[0].port_type, VexSerialPortType::System);
        assert_eq!(found[1].port_type, VexSerialPortType::User);
    }

    #[test]
    fn unrecognised_ports_yield_none_so_fallbacks_run() {
        let ports = [usb_port("/dev/ttyACM0", AIM_USB_PID, 9)];
        assert!(types_by_location(&ports).is_none());
    }

    #[test]
    fn windows_interfaces_win_over_com_number_and_enumeration_order() {
        for (system, user) in [("COM4", "COM3"), ("COM9", "COM10")] {
            let found = types_by_location(&[
                usb_port(user, AIM_USB_PID, 4),
                usb_port(system, AIM_USB_PID, 0),
            ]).unwrap();
            assert_eq!(found[0].port_type, VexSerialPortType::User);
            assert_eq!(found[0].port_info.port_name, user);
            assert_eq!(found[1].port_type, VexSerialPortType::System);
            assert_eq!(found[1].port_info.port_name, system);
        }
    }

    #[test]
    fn windows_aim_user_requires_dtr_on_every_open() {
        let info = VexSerialPort {
            port_info: usb_port("COM3", AIM_USB_PID, 4),
            port_type: VexSerialPortType::User,
        };
        let mut levels = Vec::new();
        for _ in 0..3 {
            prepare_user_port(&info, true, |level| { levels.push(level); Ok(()) }).unwrap();
        }
        assert_eq!(levels, [true, true, true]);
        // A failed setup must return before a caller can clone/use the handle.
        let error = prepare_user_port(&info, true, |_| {
            Err(serialport::Error::new(serialport::ErrorKind::Io(std::io::ErrorKind::PermissionDenied), "access denied"))
        }).unwrap_err().to_string();
        assert!(error.contains("COM3"));
        assert!(error.contains("DTR"));
        assert!(error.contains("access denied"));
    }

    #[test]
    fn dtr_setup_leaves_other_ports_and_unix_unchanged() {
        for (windows, pid, kind) in [
            (false, AIM_USB_PID, VexSerialPortType::User),
            (true, AIM_USB_PID, VexSerialPortType::System),
            (true, V5_BRAIN_USB_PID, VexSerialPortType::User),
        ] {
            let info = VexSerialPort { port_info: usb_port("port", pid, 4), port_type: kind };
            prepare_user_port(&info, windows, |_| panic!("unexpected DTR change")).unwrap();
        }
    }
}
