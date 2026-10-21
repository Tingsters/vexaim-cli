# Hardware evidence

## Device-command candidate (2026-10-20)

The published CI-built 0.3.0-rc.2 Windows candidate connected to AIM6518 over
Bluetooth in 18.207 seconds (discovery 8.039 s, connection 3.691 s, preparation
6.476 s), reporting battery 71% and stopped true. Windows showed no present AIM
USB serial endpoints. Two native camera observations returned fully decoded
640x480 JPEGs: 21,970 bytes in 8.015 s and 21,443 bytes in 8.066 s. Both were
opened in Codex's image reader within the turn and visibly showed the white VEX
controller. Both confirmed control ready and stopped before/after; the second
included a successful empty native detection result. Agent recognition does not
depend on the robot's limited object classes.

The test exposed two defects missed by desktop simulation: AIM MicroPython's
`str.endswith` rejects a tuple, breaking vision commands, and 256-byte/35 ms
printing truncated the live capability report. After refreshing only the
transient helpers with the source fixes, get-data returned an empty list,
largest-object returned null for an empty scene, and take-snapshot returned an
object with all 12 fields. That detection is not a verified classification of
the controller. A 6,000-character patterned payload transferred exactly with
128-byte/100 ms pacing (5.053 s), and a complete 4,064-character capability report
followed (4.218 s). Of 118 unique native methods, six were absent: robot.get_name
and the five robot.link methods. These remain unsupported, never fabricated.

Orientation, acceleration on all three axes, Z turn rate, all four cargo
predicates, native vision count, controller connection/axis, touchscreen pressed
state and cursor row/column, battery voltage/current and timer reads returned
successfully. The controller was disconnected and cargo predicates were false;
this does not verify button handling or detection of real cargo. A two-second
heading sample run delivered ten JSON Lines records and a one-second timer
watch delivered one callback with zero dropped events. Live info then confirmed
stopped, battery 66%. These checks used rc.2 plus the transient helper fixes,
rather than an unchanged released rc.3 binary.

A subsequent close/start revealed a teardown race, addressed by publishing the
closing state before its acknowledgement and waiting for endpoint release.
The locally rebuilt owner reconnected in 18.967 s at battery 65%, but the next
camera attempt failed with Windows HRESULT 0x800704C7 and a following info call
reported the link down. No image or effects results came from that attempt.
No shutdown/reset command or wheel/kicker movement was requested. The disconnect's cause
is unresolved; screen/power confirmation and further checks remain pending.

The following paragraph records the earlier, separate first attempt:

The command expansion's first stationary Windows BLE connection to AIM6518
completed in 18.636 seconds, including discovery 8.047 s, connection 4.258 s and
helper preparation 6.330 s. It reported battery 72%, stopped true and gyro not
calibrating. This development build preceded the prerelease version bump.

The subsequent image and individual-sensor requests found the link down before
execution. They produced no image or sensor acceptance results; no new movement
or kicker action ran. A fresh power-on confirmation was then requested. The updated
acceptance harness captures immediately after startup to avoid an idle gap.

The 0.3 candidates have simulated command/runtime/image tests and four-platform
software checks, independently of hardware evidence. USB sessions, the new native
action catalogue, separate LCD command, in-motion concurrency/cancellation, real
vision targets, linked second robot and Codex/Claude image-to-action acceptance
still need their own supervised checks. Existing 0.2 hardware evidence below
does not establish acceptance for these new wrappers. Asset upload encoding is
unverified and remains disabled; independent wheel signs/units are experimental.

## Standalone Windows Bluetooth smoke test (2026-10-20)

With USB unplugged and physical readiness confirmed, the 0.2.0 candidate reused
the existing credential for AIM6518 without pairing again. PowerShell captured
startup JSON in 13.9 seconds while the background connection remained alive.

One newly authorized 15-degree right turn dispatched in 124 ms, took 965 ms
including stop confirmation, reported +15.75 degrees and stopped true. This is
robot-sensor evidence, not independent physical accuracy verification. Defaults
remain conservative and no movement was replayed after an uncertain result.

Five consecutive stationary stop commands and session close passed after adding
bounded polling for the firmware's delayed stopped flag. A final stationary
sequence passed stop, live info, native JPEG capture, live info and close. The
JPEG was 640x480 / 27,578 bytes and took 9,855 ms; the following Python state read
took 183 ms and confirmed stopped at battery 83%. Images remain local.

The test found and corrected two issues before publication: fixed/immediate
stop checks produced false failures, and Windows background owners inherited
PowerShell capture handles. Tests cover delayed/never-confirmed stops and require
capture-pipe EOF while the child owner is still alive.

USB was not retested in this standalone smoke test. Broader movement accuracy,
in-motion interruption, faster speeds, surface variation and macOS hardware
remain separate acceptance work. A small-turn smoke test does not validate them.

## Historical hardware evidence

These dated investigation notes were imported from the original workshop.
For current installation and commands see ../README.md and the generic vex-aim
skill. Development-version references below describe the binaries tested then.

# Hardware notes: what has actually been tested

Linux tests: one robot (VEX AIM, firmware reported as 1.0.0-beta.2), one Linux x86_64 computer, USB only,
October 2026. Windows diagnostics were added on October 19, 2026, on one Windows 11 x86_64 computer.
Anything not listed here is **untested**.

## Windows Bluetooth feasibility, October 19, 2026

- BLE discovery found AIM6518 advertising `0x0670`; GATT connected with MTU 256.
  Device Information reported AIM / REV1 / `1.0.0.b0`. This BLE firmware string
  is recorded separately from the earlier USB/Python firmware description.
- With Windows PnP confirming **no AIM USB endpoints present**, the instructor
  probe accepted the displayed numeric-digit code and saved it in Windows
  Credential Manager. TXUser notifications delivered a raw-REPL prompt and
  stationary Python battery/state: initially 100%, stopped true; a later read
  reported 97%, with subsequent pre-capture reads of 94% and 93%. Separate
  reconnects reused the vault entry. Windows OS bonding
  remained false, demonstrating that OS bonding is not the VEX authentication check.
- A probe attempted with USB attached was rejected before pairing and is excluded.
  A later connection dropped, followed by two scans with no AIM detected. The
  student confirmed the robot had switched off, and acknowledged power-on before
  another stationary probe. This is not
  a completed reconnection/reliability acceptance run.
- Native vision introspection showed no `get_camera_image`; no `camera` import
  was available. A CDC screen-capture command received a valid-CRC ACK `0x76`.
  A complete 115,200-byte LCD framebuffer transferred in 27.406 s with per-packet
  CRC/address validation. It was decoded as 240x240 RGB565 into a local JPEG;
  the student confirmed it showed LCD contents, not the camera scene. Layer 1
  returned size zero. Those initial experiments did not establish camera capture;
  the later manual-mode test below did retrieve camera imagery.
- Console recovery after the LCD-transfer experiments failed. Five-minute idle
  sleep is documented by VEX, but its role here is unproven. The probe no longer
  sends a program-upload completion command after read-only framebuffer access;
  that change alone was not a verified recovery fix. The later camera spike
  isolated a notification-lifetime issue: system unsubscribe silenced Python
  responses, even without a framebuffer transfer. Re-registering user notifications
  failed to recover it; retaining both subscriptions through cleanup succeeded.
  A complete 115,200-byte LCD capture then took 25.656 s including preview startup,
  hid the preview and read battery 81%, stopped true in the same connection.
  The student confirmed this image still showed LCD contents. Keeping the preview
  Python program alive did not establish camera access. A preview-only control
  also showed no camera scene and recovered normally. Native `socket`, `network`,
  `camera` and `framebuf` modules were unavailable; no image endpoint was identified.
  The spike outcome is unresolved camera access, not proven firmware incapability.
- After the student manually selected AI Vision on the robot's touchscreen,
  a system-channel-only LCD capture retrieved actual camera imagery over BLE.
  USB absence was checked; no REPL or preview-mode commands were sent. The
  complete 115,200-byte buffer took 29.781 s including setup (before JPEG
  encoding). Its local 240x240 image visibly showed the requested VEX controller,
  with LCD borders and a back-button overlay. This establishes conditional camera
  access on the existing firmware. The later navigation test below established
  Bluetooth mode selection too; unobstructed full field of view and repeated
  camera acceptance remain unverified.
- After a fresh power/readiness acknowledgement, the AIM-specific `0x65`
  navigation command selected the AI Vision LCD camera view entirely over BLE.
  Fresh screenshots verified Drive -> Projects -> Dashboard -> Drivetrain tile
  -> AI Vision tile -> live camera. All five actions received valid `65 76`
  acknowledgements; no motion/test controls were selected. USB was absent and
  Python was not entered. The final 240x240 frame showed the VEX controller,
  with a back-button overlay. Capture took 30.047 s before JPEG encoding, so
  it does not satisfy the end-to-end 30-second target. `center` and `right` were
  hardware tested; later work also verified `back`. `left` remains source/unit tested only. The older
  V5 `0x2A` touch command was rejected with a valid-CRC `2a ff` NACK.
- The repaired Rust discovery example independently found the robot exactly once
  and returned after eight seconds. Eight BLE unit tests, six USB library tests,
  and ten existing CLI tests passed locally during transport work. The spike's
  fifty-three instructor-probe tests pass locally and cover PIN handling, framing,
  pacing, overflow, deadlines, complete framebuffer reads, corrupt/misaddressed
  blocks, empty layers, active preview lifetime, cancellation/cleanup and retaining
  system notifications until subsequent Python work completes, and system-only
  LCD capture without user-channel writes, and AIM navigation packet mappings,
  CRC/NACK validation and no automatic retries after ambiguous failures, and
  menu-icon confirmation with remembered carousel positions, unsupported
  firmware/layouts, home recovery limits, Dashboard ID `32` versus camera ID `34`,
  and leaving an already active camera alone.
  A two-request pipeline failed its live control after 560 bytes; three/four
  outstanding requests have simulated coverage only. Use sequential reads.
- The instructor automatic selector recognized Dashboard and AI Vision from
  two fresh icon-band captures per target and handled a remembered AI Vision
  selection. Its live full route was `back, back, center, center`: 45.563 s
  for navigation and 75.047 s including raw-frame download. The image showed
  the VEX controller. ID `0` was home, `32` the Dashboard carousel, and `34`
  the camera. A prior shortcut treating `32` as camera was rejected by visual
  review and removed; no drivetrain test was selected. A separate fresh frame
  at ID `34` also showed the controller. No Python, reboot or actuators were used.
  Reconnecting with automatic selection recognized the active camera in 0.062 s,
  sent no menu inputs, and captured a second verified controller image in
  29.468 s before JPEG conversion.
  Direct reads starting at the lower label rows returned a valid-CRC error
  (`-41`); icon recognition now reads sequentially through row 103, about half
  the data needed for text-label recognition. This is calibrated development
  functionality, not complete Bluetooth release acceptance.
- A later source-based check of CDC capture layer `8` retrieved a **native
  640x480 JPEG camera image** in 3.453 s (13,641 bytes), with USB absent and
  CRC/address/length checks. Visual review showed the VEX controller, with no
  LCD border or back button. The JPEG was saved without resizing, cropping or
  recompression. Source provenance was the official VEXcom JPEG-layer branch
  for its separate camera product; AIM applicability was established by this
  hardware result. Layer `1`, repeated while AI Vision was active, returned a
  nonempty 240x240 RGB565 frame but still included the LCD UI.
  Three further native captures passed from home screen `0`, with no navigation:
  close-up controller (2.594 s), controller farther back (4.594 s) and the
  student-confirmed replacement pink spinner (4.781 s). All were 640x480 without
  UI overlays, over fresh BLE connections with USB absent. Python state reads
  passed before/after the latter two, reporting 38% then 37% battery and stopped
  true. Native camera feasibility is passed on this Windows/firmware combination.
  The new instructor `--native-camera` path and existing local
  RGB565 encoder have unit coverage, including atomic output, JPEG dimensions,
  invalid/truncated responses, timeout cleanup and retained subscriptions.
- The 0.2.0-dev Rust CLI now implements explicit Bluetooth selection, pairing/
  native credential storage, doctor/info/exec/stop and native JPEG snapshots.
  Its initial live doctor authenticated but got zero REPL bytes. A control with
  Bleak forced to use indications also got zero bytes, while normal notifications
  worked. `btleplug` 0.13.5 preferred indications for characteristics advertising
  both. A vendored Windows fix prefers notifications; the next Rust doctor
  reported ready, MicroPython core 1.22.0 / compatibility 3.4.0 / battery 35%.
  A subsequent info read reported battery 34%, stopped true, heading and position.
  Rust snap saved a verified 640x480 spinner image (21,656 bytes) in 26.754 s.
  One intervening setup failed with missing characteristics; source inspection
  found that a failed Windows service enumeration could return an empty list.
  That API failure is now propagated. This does not establish the cause of every
  future enumeration failure.
  With a temporary throughput preference retained for the connection lifetime,
  the next native CLI JPEG took 7.908 s (22,029 bytes), at an actual 15 ms
  connection interval. The spinner was visually verified locally. A separate
  post-capture info connection returned battery 33%, stopped true and position
  `(0, 0)`. No actuation or reset was used.
- Native camera feasibility does not complete the planned ten-frame release run.
  No motor, kicker, LED, speaker or touchscreen input acceptance tests were
  performed over BLE. Full sensor/actuator and reliability acceptance remains
  pending; published 0.1.1 remains USB-only. The robot later slept after tests;
  no shutdown/reset command was sent and no cause is claimed from that event.

Procedure, local report commands, limitations and remaining acceptance criteria:
[Bluetooth investigation](bluetooth.md). Local reports are in ignored `dist/`;
they do not contain pairing codes. Do not commit the local Showtail trail.

## Verified on Linux

| Area | Result |
|---|---|
| USB discovery | Robot enumerates as `2888:0700` with serial interfaces 0 (system) and 4 (user) plus a UVC camera. Upstream `vex-v5-serial` returned no user port; fixed by the vendored patch. |
| System port | Read-only `SystemVersion` query answers in about 1.3 ms (product `Aim`). |
| REPL over the library | `write_user`/`read_user` round trips: 10/10 in four separate runs, about 40 ms each. Raw-REPL framing (`OK`, stdout, `\x04`, stderr, `\x04`) parsed correctly, including tracebacks. |
| Steady state | 100/100 consecutive `vexaim exec` calls succeeded (mean about 0.7 s per CLI invocation including process start, REPL sync and cleanup). |
| Unplug/replug | 20/20 recoveries over four runs (15/15 with the udev rule installed): working again within about 2 s after a stable replug. Cutting the cable mid-command gives a clear "robot disconnected" error. |
| Actuators | LED on/off, emoji, sounds (play, note), a 50 mm forward move, and `kicker.kick(SOFT)` executed without error. A human confirmed the kicker moved. LED/emoji/sound effects were not visually confirmed in the test log. |
| Sensors | Battery, IMU (heading, rotation, pitch, roll), position, AI Vision queries (empty scene). |
| Camera | `vexaim snap` returns clean 640x480 JPEGs; the V4L2 buffer is zero-padded and is trimmed. |
| Language | f-strings, comprehensions, try/except, `asyncio`, `Thread`, `json`, `math`, `random` work. |
| Agent use | A fresh agent given only the skill completed a student-style task (diagnostic, battery, LEDs, camera, version) with no failures. Goose lists the skill from a project `.agents/skills` folder. |
| ModemManager (Linux) | Without the udev rule ModemManager probes both ports for 6-9 s after every enumeration (journal-confirmed), causing busy ports and recoveries up to 14 s. With the rule: no probes, recoveries about 0.7-1.7 s. |

## Windows: what is and is not verified

- Upstream's serial layer (`async-serial` 0.2.0) does not compile on Windows. Vendored patch 0002 replaces it on Windows with
  a thread-based adapter (`blocking::Unblock`, separate read and write handles).
- The whole CLI builds natively for `x86_64-pc-windows-msvc` with Rust 1.99.1, Visual Studio 2022
  C++ Build Tools (MSVC 14.44), and Windows SDK 10.0.26100.0.
- That adapter was forced on with `--features blocking-io` and tested against the real robot **on Linux**: doctor, exec,
  error and timeout/interrupt paths, 100/100 consecutive calls. A first version of it failed on hardware (a read timeout was
  reported as the next write's error), which is why reads and writes use separate handles.
- Windows 11 build 26200, built-in Microsoft `usbser` driver 10.0.26100.9278: USB discovery identified
  system COM4 (`MI_00`) and user COM3 (`MI_04`). The installed 0.1.0 executable opened both but raw REPL
  initialization returned no bytes, including after power-cycling in an earlier agent session.
- Direct PowerShell/.NET serial probes held baud rate (115200), 8N1, no flow control, and RTS low constant.
  DTR low returned no bytes. Setting DTR high on the same connection immediately returned the raw REPL
  prompt and executed `print`. Fresh-open true/false/true comparisons repeated the result: both DTR-high
  connections read battery 100%, stopped true, MicroPython core 1.22.0, Python compatibility 3.4.0.
  The unmodified Rust executable still failed afterward: DTR is required on every open.
- The rebuilt **vexaim 0.1.1** executable and the executable extracted through the checksum-verified ZIP
  installer both reported `verdict: ready`, battery 100%, MicroPython core 1.22.0, Python compatibility
  3.4.0, and stopped true. No actuators or camera were used.
- The packaged executable passed **100/100 consecutive round trips** in PowerShell 7.6.7 (mean 1062.8 ms
  per process invocation). One-line execution, multiline stdin, a file path containing spaces, Python
  errors, timeout/interrupt and recovery all passed. An out-of-range device index reported not ready.
- All 10 CLI and 6 vendored serial unit tests passed locally. Installer regression tests passed all
  18 assertions in both Windows PowerShell 5.1.26100.9711 and PowerShell 7.6.7: dry run, both agent
  destinations, upgrade, single-agent selection, checksum/missing-checksum rejection, old/malformed/
  failed-version rejection, foreign-skill protection, and uninstall isolation.
- Reproduce stationary validation with `dev/test-hardware.ps1` and installer checks with
  `dev/test-install.ps1`. Local reports are generated in the ignored `dist/` folder; these results do not
  establish Windows camera or actuator support.
- Two automated USB reconnect cycles and one manually verified reconnection returned to ready. An initial
  third automated attempt did not include a completed reconnection and is excluded; this is not an
  uninterrupted automated 3/3 run. The manual reconnection check read battery 98% and stopped true;
  the subsequent PowerShell 5.1 run read 100% while connected over USB.
- The reconnect harness now waits for all AIM serial endpoints to disappear and for both endpoints to
  remain present for at least one second using `Get-PnpDevice -PresentOnly`, rather than advancing on a
  transient CIM serial-port snapshot. Every reconnect attempt saves its diagnostic output beside the
  requested report, including failures. The stable-presence check was exercised with the connected robot;
  simulated transient and partially enumerated states were rejected in both PowerShell 5.1 and 7.

## Known limits

- Output bursts over about 2 KB are lost (robot firmware).
- No software safety limits on motion. Physical supervision is required.
- Uploading and running a stored program through the library was tried and **not** made to work; it is not needed.

## Not tested

- Windows USB camera/actuators and macOS hardware, including camera permissions and signing/SmartScreen/Gatekeeper behaviour.
- Turns, `kicker.place/push`, harder kicks, longer or faster moves, `Ctrl-C` during a move.
- AI Vision on real objects (tags, balls, barrels).
- Complete Bluetooth hardware/reliability acceptance and the ten-frame camera release run;
  Linux/macOS Bluetooth hardware; several robots at once; many robots in one room.
- Goose desktop end to end with a real robot.
- Other firmware versions beyond the USB and BLE versions specifically recorded above.

## Local development validation

The current change passed 18 combined-CLI tests, 13 USB-only CLI tests,
three protocol tests (including the new camera-block CRC/truncation cases),
14 combined transport tests, eight isolated Bluetooth transport tests,
47 active Windows btleplug tests (three ignored upstream), and 53 instructor-probe
tests. The checksum-verified development ZIP passed 20 installer assertions in
each of PowerShell 7.6.7 and Windows PowerShell 5.1.26100.9711, including valid
prerelease version handling and refusal of obsolete 0.1.0 builds. The updated
skill validated. These local checks do not substitute for other-platform CI or
physical sensor/actuator acceptance.
