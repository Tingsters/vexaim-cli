---
name: vex-aim
description: Control a VEX AIM robot over USB or Bluetooth using vexaim. Run Python, read sensors, move, stop, set lights and sounds, and capture camera photographs from ordinary requests.
---

# Control a VEX AIM robot

Use the executable in this skill's own `bin/` directory: `bin/vexaim` on
macOS/Linux, `bin/vexaim.exe` on Windows. Invoke its full path; do not assume it
is on PATH. This skill is independent of any workshop or saved robot project.
Install/update the executable and skill together from
https://github.com/Tingsters/vexaim-cli or https://tingsters.github.io/vexaim-cli/.
Normal installation needs no Rust, Python packages, VEXcode or special Wi-Fi.

## Connect once, then reuse

Select the requested transport and exact robot. For Bluetooth, read
`references/bluetooth.md` and `references/sessions-and-motion.md`. Start/reuse one
named session and retain its returned ID across requests. Startup already reads
live status; do not scan, reconnect and run doctor before every healthy action.
Cached session status does not prove the robot is still awake.

For USB, run `vexaim doctor` initially and after a connection failure. A successful
check reports `verdict: ready` and battery. For Bluetooth use its transport/name
options or the existing session; a USB diagnostic cannot diagnose a wireless link.
Close VEXcode and other programs using the robot. Installation does not require
the robot to be connected; ask for power-on/readiness when interaction needs it.

Translate ordinary requests into finite actions. "Spin in a circle" means one
360-degree turn in place, left unless specified. Honor explicit direction and
distance. Use `turn`/`move` helpers where applicable and compose actions for other
ideas; arbitrary Python is available. Do not require surface labels, targets or
calibration before ordinary movement.

Announce movement and establish a clear, level area with a person near the power
switch. Preserve readiness within the current interaction rather than asking
again before every action. Motion helpers have finite bounds and a robot-side
deadline; arbitrary `exec` does not inherit these limits. Bluetooth stop requires
a working link and is not a guaranteed emergency stop.

## Execute and inspect

`exec` supplies `robot = Robot()`, `from vex import *`, and
`from vex_globals import *`. Variables persist in the transient MicroPython REPL.
Nothing is saved as a robot project or installed into its firmware.

```sh
vexaim info
vexaim exec 'print(robot.get_battery_level())'
vexaim exec -f my_program.py
vexaim snap -o photo.jpg
vexaim stop
```

For a Bluetooth session, include `--session ID` before the subcommand. See the
session reference for progress/result JSON and responsive `turn`/`move` calls.
Print small summaries: bursts above roughly 2 KB can lose console output.
Default execution timeout is 30 seconds; errors return a traceback and failure.

PowerShell needs `&` before a quoted executable path. Prefer piped here-strings
or `exec -f` for multiline Python, avoiding shell argument-quoting differences:

```powershell
$vexaim = Join-Path $env:USERPROFILE '.agents/skills/vex-aim/bin/vexaim.exe'
@'
robot.led.on(ALL_LEDS, BLUE)
wait(1, SECONDS)
robot.led.off(ALL_LEDS)
'@ | & $vexaim exec -
```

For Claude's installation use `.claude` instead of `.agents`.

## Recover carefully

After an interruption, obtain live status and confirm stopped state before a new
movement. Never automatically replay a movement whose delivery is uncertain.
If the robot sleeps or the link fails, explicitly ask for power-on when needed,
close/start the session and verify live state. Do not ask for USB replugging when
the selected transport is Bluetooth. Busy actions are rejected, never queued.

`snap` downloads a native 640x480 JPEG independently of the LCD menu. Do not reset
the robot or navigate to AI Vision for a photograph. After cancelling a camera
transfer, another snapshot requires a fresh session; live status can restore
ordinary movement first. View captures locally and obtain consent before sending
them elsewhere. An image or the robot's IMU alone cannot certify a physically
exact turn. Automatic camera-based movement correction is not enabled.

Keep the current 30 DPS turn default unless independent hardware evidence supports
a change. Do not imply every allowed speed or platform has been tested with a
robot. Actual coverage: https://github.com/Tingsters/vexaim-cli/blob/main/docs/hardware-notes.md.

## References

- `references/sessions-and-motion.md`: persistent connections, movement and stop.
- `references/bluetooth.md`: pairing, transport selection and Bluetooth recovery.
- `references/troubleshooting.md`: known failures, including the Windows DTR fix.
- `references/api.md`: available Python APIs, constants and observed limitations.
- `references/examples.md`: short Python examples for creative compositions.

For Linux USB only, `linux/install-udev.sh` avoids ModemManager interference.
Ask before its administrator action and explicitly cue a USB reconnect afterward.
macOS and Windows do not need that rule.
