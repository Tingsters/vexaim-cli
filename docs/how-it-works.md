# How vexaim works

The CLI connects to the AIM's MicroPython console over USB or Bluetooth and sends
transient Python. Its preamble creates `robot = Robot()` and imports VEX constants.
It does not upload a saved project or modify firmware.

USB uses the AIM console ports. Windows requires DTR assertion and a compatible
serial adapter; the vendored patches retain those fixes. Linux may need the
provided udev rule to avoid ModemManager interference after reconnecting.

Bluetooth uses native OS BLE through patched btleplug and the VEX console protocol.
Pairing credentials stay in the native OS vault. A session owner retains
the selected USB or Bluetooth connection and prepared REPL helpers. Bluetooth
owners also retain both notification subscriptions. Later CLI processes
use private current-user Windows named pipes or Unix sockets; there is no TCP
listener and no repeated scan for each prompt.

Finite movement helpers enforce their bounds and deadline on the robot. Stop can
preempt work over a healthy connection; uncertain movements are never replayed.
Arbitrary exec programs remain the caller's responsibility and lack helper bounds.

Camera capture uses native system commands to download 640x480 JPEG frames over
BLE, independently of the LCD menu. USB capture uses the native camera interface.
Transfers and REPL work share a session with explicit recovery after cancellation.
Camera observations validate/decode native JPEGs and return immutable local files
with host timing, robot state and control readiness, for the agent's native image
reader. LCD screenshots are separate 240x240 RGB565-to-PNG display captures.

The native device catalogue drives validation and VEX method dispatch on both
transports. Bounded background VEX threads use private timers, action IDs and
resource conflict checks. Sensor/effect calls share serialized console transactions
while robot motion continues. No additional network model client is included.

Release bundles contain the executable, its matching general-purpose skill and
installers. The separate workshop depends on the latest stable bundle and adds
its own teaching skill. The CLI and robot operate without workshop files.
