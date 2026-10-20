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

If discovery fails, check robot power and proximity before retrying. The robot can
sleep while work is idle; a connection does not promise to keep it awake. Give a
clear power-on cue. After a link failure close/start the session, obtain live
status and confirm stopped state before a new movement. Never replay a movement
whose outcome is uncertain. Cached status is not proof of a live connection.

The session owns its connection; standalone commands will refuse to take it over.
Use its ID or close it deliberately. A cancelled camera transfer requires a
fresh session before another snapshot; live info can restore movement first.
Wireless stop depends on the connection; a nearby person must be able to use
the physical switch.

Technical protocol evidence, including the Windows notify-versus-indicate fix,
is recorded at https://github.com/Tingsters/vexaim-cli/blob/main/docs/bluetooth.md.
Firmware and saved programs should remain unchanged.
