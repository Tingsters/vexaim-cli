# AIM display investigation

This developer spike investigates why `robot.screen` calls return normally while
the physical AIM LCD stays on its menu. It does not change student prerequisites:
the implementation must work over Bluetooth, without a saved robot project.
USB is permitted only as a diagnostic comparison. Camera JPEG capture is already
independent of the LCD and must not acquire a display-initialization dependency.

## Evidence and result

On AIM6518 (AIM REV1 / BLE firmware 1.0.0.b0), the corrected HAPPY constant and
a six-second transient drawing program left the LCD on its menu. The student
confirmed blue LEDs and a chirp, but no visible emoji or circle. LCD screenshots
also showed the menu. This rules out an enum-name problem as the complete cause;
it does not prove the firmware cannot draw from a remote session.

The official [Emoji API](https://api.vex.com/aim/home/python/Emoji.html) says emojis
overlay drawings; the [Screen API](https://api.vex.com/aim/home/python/Screen.html)
supports origin, clipping, colors, text and shapes. Official AIM screen-drawing
project templates need no explicit Python display-layer call.

The official [WebSocket Robot constructor](https://github.com/VEX-Robotics/AIM_Websocket_Library/blob/main/vex/aim.py)
calls `_program_init()`. Its [message definition](https://github.com/VEX-Robotics/AIM_Websocket_Library/blob/main/vex/vex_messages.py)
uses `program_init`. The constructor also resets heading, so copying its entire
initialization would be inappropriate. Live Bluetooth testing confirmed missing
program display activation and a required remote-status keepalive. Initialization
alone briefly showed the startup face/chirp, then returned to the menu. With
status polls every 100 ms, drawings and emojis stayed visible.

The cached official VEXcom 1.0.2b2 executable, SHA-256
`cc15efc812e19a08ca5f2f864305720c8fa513b390e9004f8b806b6f40e4d40e`, has symbols and
help for `--aimrc start`, `stop`, and `screen` operations. Inspection establishes:

| Field | Value |
| --- | --- |
| CDC family | `0x57` (ordinary capture uses `0x56`) |
| Extended remote command | `0x7f` |
| Payload | 32 zero-initialized bytes; byte 0 is `0x20`, byte 1 is operation |
| Start / stop | `0x19` / `0x1a` |
| Clear / show emoji / hide emoji | `0x15` / `0x16` / `0x17` |
| Circle | `0x2d`; signed little-endian 16-bit x/y/radius at offset 8 |
| Emoji parameters | emoji / look bytes at offsets 8 / 9; use firmware named constants rather than assuming numeric mappings |
| Keepalive | family `0x57`, extended read-only status query `0x7e`, no payload |

Offline emulation of `_aimrc_command_program_start`, `_aimrc_command_program_stop`
and `_aimrc_command_screen` verified the start/stop/show/hide payload fixtures.
These commands carry no program filename or slot and are distinct from program
uploads. `_aimrc_command_delay` calls `_aimrc_RcStatusCmd` every 100 ms while
waiting; this revealed the missing keepalive. The tested BLE route executes
remote writes without returning the USB-style acknowledgments. The CLI sends
start once, polls status and independently verifies AIM program screen ID 20.
Do not send the WebSocket JSON over CDC or guess undocumented layer values.

## Run the stationary matrix

Read the robot skill. Close the existing CLI session before opening this probe;
only one owner may use the robot. Obtain power-on/stationary readiness immediately
before running, keep USB unplugged, and close VEXcode. Pair beforehand through
the CLI's masked local prompt; the probe only reuses the native credential vault.

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/display-probe.py --name AIM6518 --case normalize --ready
```

Use each case once, in this order. Watch the physical LCD during the nine-second
pattern and record what appeared separately from API success:

1. `normalize`: explicit origin, full clipping region, blue clear, white circle,
   centered text, HAPPY, then hide the emoji.
2. `remote-draw`: native remote clear/circle/emoji/hide, without initialization.
3. `init-after-repl`: prepare Python, remote-start, then normalized Python drawing.
4. `init-before-repl`: remote-start, re-enter the REPL, then Python drawing.
5. `init-native`: remote-start, then native remote drawing.

Each run saves a local JSON report under ignored `.vexaim/display-spike/`.
`completed` means the protocol/control sequence finished; `visibility_verified`
remains false until independent image/human evidence is recorded. An unchanged
menu is not a display pass. Errors are not replayed. Both notification channels
remain subscribed through Python cleanup. Remote-stop is sent only if start was
attempted; recovery verifies stopped state. No motors/kicker/calibration/reset or
file writes are available in the remote-command whitelist.

For the working path, add `--observe-unacknowledged --keepalive` to an init case.
This explicitly permits observation of a single unacknowledged write, not replay
or fabricated acknowledgment. The probe's keepalive is bounded to 60 seconds.
The successful Python path works both before and after REPL synchronization;
it preserves the existing Robot object and needs no undocumented layer selection.

For a promising case, repeat with `--capture .vexaim/display-spike/drawing.png`.
It captures the final drawing, never changes LCD modes, and adds up to 55 seconds.
The read-only 240x240 RGB565 buffer is decoded to PNG; no FILE_EXIT is sent.
Open the PNG in the agent's image reader and inspect its actual pixels.

If all Bluetooth cases fail, compare the same normalized Python drawing over
USB using the CLI's existing Windows serial implementation. If remote-init
comparison is then needed, add only the source-derived display packets to that
diagnostic adapter; do not change the student transport or use USB as a fallback.

## CLI implementation and acceptance

The 0.3.0-rc.5 candidate prepares the program display for native screen writes
and `exec` source referring to `.screen`, leaving ordinary sensor/LED/motion/
camera requests independent. A transport wrapper serializes keepalive with user
and system traffic, including while a Python program or image read is pending;
the owner services it while idle. It uses no competing connection or radio task.
Stop cancels keepalive before the motion stop and then releases display mode.
Close, failure and 60 seconds of inactivity also end the display lease. Polling
does not extend the owner's existing 30-minute idle shutdown.

Only the fixed read-only keepalive avoids a redundant pairing-characteristic
read on every poll; the owner has already authenticated, and normal commands
retain their authentication checks. The first integrated LCD transfer exposed
that overhead by exceeding 45 seconds. LCD reads now have a separate 55-second
budget inside the existing 60-second host deadline; JPEG reads retain 45 seconds.
Both image types keep CRC/address/size checks and preserve prior files on failure.

Two further display findings were isolated: numeric emoji 6 selected a sunglasses
face on this firmware, while named HAPPY worked; white text on white fill rendered
as a white bar. The probe now uses named constants and a contrasting blue fill.
The operator confirmed readable LCD TEST text, centered white circle, named HAPPY
and restoration of the drawing after hide. A local LCD screenshot independently
confirmed the blue background/circle before the text contrast correction.

Visible text and shapes, replacement by HAPPY, and restoration after hide must
work across three Bluetooth connections, including clean boot and previously
navigated menus. Record heading, position, calibration and stopped state before
and after initialization; do not silently accept resets. Recheck Python, sensor
queries and native camera JPEG capture after the display experiment.

Existing VEX-style commands and retained Python variables are preserved; no new
student mode, saved project, reset, menu-navigation step or USB cable is needed.
Unsupported firmware fails clearly rather than claiming visible success.
Hardware findings belong in `hardware-notes.md`; update the matching basic skill
and workshop reference only to the level actually observed.
