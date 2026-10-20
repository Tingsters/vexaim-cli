# How vexaim works

The CLI connects to the AIM's MicroPython console over USB or Bluetooth and sends
transient Python. Its preamble creates `robot = Robot()` and imports VEX constants.
It does not upload a saved project or modify firmware.

USB uses the AIM console ports. Windows requires DTR assertion and a compatible
serial adapter; the vendored patches retain those fixes. Linux may need the
provided udev rule to avoid ModemManager interference after reconnecting.

Bluetooth uses native OS BLE through patched btleplug and the VEX console protocol.
Pairing credentials stay in the native OS vault. A named session owner retains
the radio connection, notifications and prepared REPL helpers. Later CLI processes
use private current-user Windows named pipes or Unix sockets; there is no TCP
listener and no repeated scan for each prompt.

Finite movement helpers enforce their bounds and deadline on the robot. Stop can
preempt work over a healthy connection; uncertain movements are never replayed.
Arbitrary exec programs remain the caller's responsibility and lack helper bounds.

Camera capture uses native system commands to download 640x480 JPEG frames over
BLE, independently of the LCD menu. USB capture uses the native camera interface.
Transfers and REPL work share a session with explicit recovery after cancellation.

Release bundles contain the executable, its matching general-purpose skill and
installers. The separate workshop depends on the latest stable bundle and adds
its own teaching skill. The CLI and robot operate without workshop files.
