# Bluetooth connection and recovery

Use vexaim 0.2.0 or newer. Select the exact robot name and Bluetooth explicitly;
the CLI never silently selects another robot or falls back to USB. Close VEXcode,
switch the AIM on, and keep it nearby. USB can be disconnected for wireless use.

```sh
vexaim bluetooth scan
vexaim --name AIM1234 bluetooth pair
vexaim --transport bluetooth --name AIM1234 doctor
```

Pairing asks for the robot's displayed code in a masked local terminal. Never
request it in chat or put it in arguments, logs or a plaintext file. Credentials
stay in the native OS vault. Ordinary operations reuse them. Windows OS bonding
status alone does not indicate whether VEX application authentication succeeded.
The credential-store identity is unchanged from the original workshop builds.

For repeated actions, follow `sessions-and-motion.md`: start/reuse one named
session, retain the returned ID and use it for Python, movement, snapshots and
stop. Do not repeat discovery and doctor for each healthy request.

```sh
vexaim --json --name AIM1234 session start
vexaim --json --session SESSION_ID info
vexaim --session SESSION_ID snap -o photo.jpg
vexaim --session SESSION_ID session close
```

Native camera capture downloads a 640x480 JPEG independently of the LCD mode.
No AI Vision navigation, preview, reset, Python camera project or USB cable is
needed. Windows captures have been verified; other OS/firmware combinations need
their own hardware evidence. Snapshot transfers take several seconds and are
optional; do not insert one as a prerequisite for every movement.

The experimental 0.3.0-rc.6 release sends and acknowledges the existing System
Alive request every two seconds on AIM REV1 / BLE 1.0.0.b0. The tested robot still
lost power/connectivity around five minutes despite 92 acknowledged replies.
This is link health monitoring, not verified sleep prevention; metadata reports
`prevents_sleep:false`. Do not recommend this candidate as a sleep fix.
This is separate from the display heartbeat: camera/sensor work and idle prompts
do not need a visible program screen. Startup/live info report `keepalive.active`.
Unknown firmware reports inactive rather than claiming equivalent verification.
Stop and the 60-second LCD lease do not end session liveness; close and the
30-minute owner idle deadline do. Heartbeats do not renew that deadline.
Cached health reports successful poll counts, acknowledgment age and consecutive
failures. Only the fixed read-only probe retries, up to three failures; student
actions are never replayed. After an error, obtain live info before fresh motion.

The rc.7 compatibility candidate also recognizes the observed AIM REV1 /
`1.0.4.b0` profile. Its System Alive request is unchanged and still reports
`prevents_sleep:false`; new-firmware endurance is not yet accepted. Older builds
can disable their monitor or reject camera/display solely because a firmware
revision is unfamiliar, even when Python works. Record startup/live `device_info`
once after an update and use a documented compatible CLI/skill pair. Do not
bypass an unknown-profile guard or downgrade firmware to silence it.

If discovery fails, check robot power and proximity before retrying. Current
binaries can sleep despite REPL activity, and a keepalive cannot recover an
already powered-off robot or guarantee battery/radio health. Give a clear
power-on cue. After a link failure close/start the session, obtain live
status and confirm stopped state before a new movement. Never replay a movement
whose outcome is uncertain. Cached status is not proof of a live connection.
Brief link errors can recover without physical power-on. After a failure, make
at most three bounded read-only recovery attempts before requesting physical
help. Record discovery loss as unavailable connectivity unless power-off was
independently observed; a visible REPL/emoji screen is not an endurance result.

The session owns its connection; standalone commands will refuse to take it over.
Use its ID or close it deliberately. A cancelled camera transfer requires a
fresh session before another snapshot; live info can restore movement first.
Wireless stop depends on the connection; a nearby person must be able to use
the physical switch.

For unattended stationary diagnostics, collect charging, power-on, USB removal
and VEXcode closure together before starting. Use bounded automated checks; do
not deliberately exhaust an old keepalive control when recovery would require
someone who is unavailable to press power. Never move an unattended robot.

Technical protocol evidence, including the Windows notify-versus-indicate fix,
is recorded at https://github.com/Tingsters/vexaim-cli/blob/main/docs/bluetooth.md.
Firmware and saved programs should remain unchanged.
