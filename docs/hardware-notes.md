# Hardware evidence

## Blue barrel to purple Tag 0 and fast-play follow-up (Windows, 2026-10-23)

On AIM9E18 / firmware 1.0.4.b0 over Bluetooth, the 0.5.0 controller collected the
blue barrel and verified retention at robot elapsed 11.294 seconds in the kit
pen. Its continuous Tag 0 search then missed the marker after 360.3 measured
degrees. The robot stopped with the barrel still held; a native stationary
probe confirmed possession. No placement was claimed from that failed search.

A short transient continuation took stationary views 45 degrees apart, turning
at 90 DPS, settling for 300 ms and reading three times 100 ms apart. It found
Tag 0 at the third view, then used the existing `behaviors.deliver` controller
for approach, `kicker.place`, backing away and native release confirmation. That
continuation used 9.350 seconds of robot execution, separately from 15.779
seconds preparation and 1.812 seconds source upload. A final local camera frame
independently showed the separated blue barrel directly beside the purple
marker visibly labelled 0. This was not a nine-second total cold-start task.

The 0.5.1 source implements those stationary tag views in the shared controller
and adds explicit contact-based play. The new policy omits the diagnostic
retention reverse and continues from bounded contact despite unconfirmed
possession. It marks assumed evidence rather than declaring native confirmation.
Independent simulation exercises real attachment with deliberately missing
possession readings, stationary-only tag decoding, empty scenes and deadlines.

For a final source check, the exact new controller plus one whole fast-play
activity was transiently executed through the existing installed 0.5.0 owner;
no firmware or saved project was written. Native Python compiled and executed
the new module. Blue was not reacquired: the search ended after 8.842 seconds
and 61.9 degrees of accumulated rotation (not a successful full sweep).
Execution including cleanup was 9.400 seconds; stop was confirmed. The reason
for the incomplete rotation was not diagnosed. The subsequent image faced desk
objects with no blue barrel or marker in that frame. Battery was 28%, control
ready, and no further movement was attempted or human reset requested.

That check is not full 0.5.1 hardware acceptance. Keep it separate from the
earlier camera-verified delivery. The separate blue false-negative and
orange/ball motion-deadline observations remain important: contact-based play
is an explicit completion policy, not a repaired neural model or force sensor.
Bluetooth recovery and lighting limits remain as recorded below. Photos and
raw traces stay local under `.vexaim/behaviors/` and are never release assets.

## Composed behavior investigation (Windows, 2026-10-23)

AIM9E18, firmware 1.0.4.b0, was prepared once with USB unplugged and a persistent
Bluetooth owner. All subsequent checks were autonomous. No saved robot project,
firmware write or Wi-Fi transport was used. Results below are development
candidate evidence, not acceptance of successful pickup/delivery.

- Six stationary samples in each normal/display context advanced the private
  Timer and system clock together. Native reads took 0–2 ms. A 400 ms native
  timer callback fired after 403 ms and 406 ms respectively. Display preparation
  took 23.142 seconds; it was separate from 1.026 seconds of Python execution.
- The first 0.5.0 candidate found a blue barrel after 161.1 degrees of search,
  aligned by its detected bearing and reported stopped. Robot execution was
  5.383 seconds, with 1.148 seconds preparation and 0.495 seconds upload.
- The initial pickup attempt completed two bounded contact strokes, then failed
  `not_collected` after 9.348 seconds, with stop confirmed. It did not reach the
  CLI timeout or claim possession. Native-camera images before/after a 60 mm
  reverse showed the barrel amid shoes/laces, with an obstructed approach.
  Attachment was not independently confirmed; native possession remained false.
- A sideways viewpoint test ended `target_lost_before_contact` after 6.709
  seconds. Subsequent controller changes were loaded transiently into the same
  candidate for investigation: asynchronous stop confirmation, a short detection
  grace interval, a wider recent-alignment gate for cropped cargo, and a lateral
  offset during the single contact retry. The first follow-up stopped after
  3.877 seconds on target loss. A later scan stopped after 361.4 measured degrees
  and 9.408 seconds with `not_found`, without circling to the 60-second fallback.
- Native JPEG diagnostics completed in 15.185 and 18.556 seconds and left control
  ready. No successful release/kicker operation was reached. The session stayed
  healthy through these checks, with no reconnects after candidate startup.

After closing that owner for a binary update, two new-candidate startup attempts
failed (`Not connected`, then `Packet timeout`). Discovery still found AIM9E18;
a third attempt using the previous released binary found no matching robot.
Testing checkpointed without requesting another physical setup. This does not
establish a new sleep or transport diagnosis. The final loader caches the vision
controller on first use rather than adding it to every session startup; that
change has automated coverage but has not had a fresh hardware acceptance run.

The short clock controls did not reproduce Goose's missed internal deadlines.
The new callbacks, finite phase loops and system-clock checks are tested bounds,
not a claimed diagnosis of that earlier failure. A clear-path physical pickup,
orange/ball pickup and complete tag delivery still require hardware acceptance.
The 15-second pickup / 30-second delivery values are targets, not measured passes.
An obscured or cropped native detection cannot guarantee arbitrary-clutter
navigation. Do not replace missing possession evidence with a success claim.
Photos, JSONL traces and investigation scripts remain local under
`.vexaim/behaviors/` and are not included in the release.

For a future short repeat, prepare the robot/session/objects at the beginning,
then use `python dev/accept-behaviors.py --tool PATH --session ID --output-dir LOCAL`.
That defaults to stationary timing/helper checks. Add `--motion-ready --cargo
BLUE_BARREL --tag 0` only after the initial floor/object setup. It checkpoints
on failure, does not replay motion or request later human help, and preserves
the persistent owner. It checks at least 35% starting battery and reports native
evidence separately from independently verified physical attachment.

## Windows AIM 1.0.4 investigation (2026-10-21)

The revised packaged Windows candidate (`fbfb9ac`, harness `4ccc82d`) has now
passed its first clean-boot acceptance run: **1214.266 seconds**. A second charged
clean-boot run remains pending; this is not yet a two-run acceptance result.
The earlier controls and failures below explain why the follow-up was needed.

The 2026-10-22 source sync combines the merged Mac camera/constants/pairing fixes
with the fresh-namespace imports and raw-banner parsing from PR #10, retaining
the Windows ownership and display recovery path. The combined source passes
73 CLI tests, 25 USB-only tests, 17 acceptance-harness tests and 15 lease tests.
It has not been retested on the robot. The first acceptance result above belongs
to `fbfb9ac`; a new matching package needs hardware acceptance after this sync.

AIM6518 now reports `1.0.4.b0` from GATT firmware/software revisions, VEXos and
both CPUs. The unchanged rc.6 baseline disabled its monitor for that unfamiliar
profile, then failed its live check after 420 silent seconds; discovery found no
robot. Installed Windows VEXcode also lost its idle connection after about
900 seconds from its last setup command despite continuous status notifications.
The visible built-in REPL control likewise did not complete endurance. These are
failed controls, not proof of a particular firmware power-management cause.

An independent Bluetooth-only LCD read returned a complete 240x240 RGB565 frame;
the decoded PNG visibly shows REPL Mode. No photo, log or extracted official app
asset is published. The rc.7 candidate recognizes the exact new profile for
existing health, camera and display operations, retaining `prevents_sleep:false`.
Its first new-profile endurance run failed after 86.7 measured seconds, before
camera/display checks. The monitor reached 124 acknowledged System Alive polls
then three failures; live recovery and discovery found no robot. Enabling this
known request on 1.0.4 is not a sleep fix. At that stage, new-profile display and
fresh-boot acceptance still needed verification. No wheels, kicker, firmware
write or saved-project upload ran.
A background waiting Thread subsequently lost its link after 162.343 seconds;
the operator independently confirmed power-off. A standalone finite main-loop
wait also failed to return its final frame, ending with a closed Bluetooth
object error after 466.218 host seconds; discovery then found no robot. Local
timeout and connection-handoff rejections are recorded separately as harness
failures. Neither Python control is accepted as sleep prevention.
A home-only Back plus System Alive control failed after one acknowledged input
and three polls, then reconnected without physical power-on. The recovered
session downloaded a native 640x480 JPEG in 10.875 seconds; local pixels show
the controller and postcapture control was ready. Read-only inspection found
a callable private `Robot._sleep_disable` helper. Its zero-argument query returns
a Boolean; setting `True` returns `None` and reads back `True`. Nevertheless,
the no-argument control failed after 166.922 seconds and the one-time setter
control after 267.704 seconds, both around five minutes from boot. The latter
acknowledged 132 health polls before three failures. The flag was subsequently
shown to survive ordinary exec, live info and stop with the same Robot object.
That one-time setter was not adopted as a standalone startup fix. A finite main-execution
comparison with explicit readback/restoration is a separate developer control,
not accepted sleep prevention. The finite main-with-helper comparison also
returned no final frame and failed after 466.485 host seconds with a closed
Bluetooth object; a fresh scan found no robot. The subsequent short timing
comparison showed 0–1 ms per batch of 30 cached sensor reads with either flag
value. It restored `False` and closed normally, at 53% battery and stopped.
The first combined setup lost program 27 during ordinary interrupting raw entry
and correctly stopped before calling the helper. Waiting for a prompt and using
Ctrl-A without Ctrl-C retained program 27/screen 19. That combined control passed
1200.014 quiet seconds: a final live read retained its marker, advanced system
time from 119837 to 1320275 ms, reported stopped and read True. Original False
restoration and stopping its own system REPL confirmed. Battery changed 49% to
36%. This is mechanism evidence; normal CLI integration and two fresh-boot
candidate passes are still pending.

The integration candidate now automatically prepares that context on the exact
complete 1.0.4 profile and uses a finite robot-side power lease tied to client
inactivity. Its acceptance gates cover real watchdog execution, normal
camera/display/stop recovery and two clean-boot 20-minute runs. The standalone
mechanism control does not certify the integration.
The first packaged integration run proved robot-side watchdog expiry and passed
420 quiet seconds with the same lease, then returned a verified camera image.
It failed at 458 seconds when display activation replaced its interpreter.
Diagnostic output also exposed a program-status-bit ownership rejection after
stop. The follow-up rebuilds helpers at display entry and follows the official
AIM low-nibble program-slot parsing while retaining explicit ownership guards.
A short display/stop/live-info recovery passed, followed by 135.828-second and
98-second smoke checks. During the latter's LCD transfer, the same watchdog
advanced from 10 to 486 ticks.

The first full revised run then passed both 420-second quiet intervals, retaining
the same watchdog within each context (47→4238 ticks before display, 41→4233
after stop). Actual 1500 ms watchdog expiry/restoration also passed. Both native
640x480 camera images showed the controller; the LCD frame showed the rendered
emoji and its watchdog advanced 9→494 ticks during capture. Robot system time
advanced continuously from 50648 to 1254792 ms, battery changed 41%→28%, and all
samples reported stopped. Independent read-only inspection after session close
confirmed native program 0. No motor, kicker, firmware or saved-project operation
ran. The second run is awaiting a recharge/restart to avoid low-battery ambiguity.
See the investigation for the full chronology and failed-run evidence.
See [source provenance, controls and measured status](firmware-1.0.4-investigation.md).

## Session keepalive candidate (2026-10-21)

Two stationary checks exposed why a successful connection is insufficient proof
of sustained liveness. The rc.5 display-only control reached uptime 316650 ms
at 91% battery, stopped at (0,0), then lost the link. The next exact-name scan
found no AIM6518. The first local rc.6 System Alive candidate acknowledged its
initial request, but a later background probe exceeded its 500 ms total deadline
and stopped polling permanently. The quiet test failed at 370 seconds; discovery
again found no robot. Neither run passed endurance. No motors or kicker ran.

The hardened local candidate uses a 3-second total / 2-second reply deadline,
up to three read-only retries and cached confirmation counts/age. Stop and close
preempt background polling; the unchanged owner idle deadline still expires.
The checksum-verified CI Windows candidate connected at 86% battery and stopped
at (0,0). It completed 92 acknowledged System Alive polls, with zero recorded
failures until the link disappeared around 333 seconds of robot uptime. Three
subsequent bounded probes failed; cached health correctly changed to unhealthy
and the harness failed after 187 seconds, before its first quiet interval ended.
Live info confirmed the link was down, and discovery found no AIM6518. This
rules out a merely unserviced or over-short heartbeat deadline as the explanation
for this run: System Alive acknowledgments alone do not prevent the observed
shutdown. No camera/display acceptance or second quiet interval ran. No motors
or kicker ran. Do not publish rc.6 as a verified sleep fix.

Further investigation compares the existing AIM native flags/status queries
(`0x56/0x20` and `0x56/0x22`) independently of legacy System Alive. The developer
probe uses one BLE owner, existing vault authentication and no menu inputs.
Software and installer tests alone do not establish that any probe prevents sleep.
Subsequent home-Back controls also failed to sustain their status-only links,
including a Rust control beginning at system time 372988 ms. The CLI reconnected
without a further power-on, distinguishing these short errors from shutdown.
Adding only the two known AIM status notification subscriptions to System Alive
also failed: 87 polls through 178.52 seconds from system time 523308 ms, followed
by link loss and no exact-name discovery match. The combined System Alive plus
home-only Back control and read-only power-API inspection are prepared but not
verified. All these controls were stationary; no wheel or kicker command ran.
See [investigation and autonomous procedure](keepalive-investigation.md).

## Bluetooth display lifecycle candidate (2026-10-20)

Local Windows 0.3.0-rc.5 now displays named HAPPY, text and shapes over Bluetooth
on AIM6518 (AIM REV1 / BLE 1.0.0.b0), without USB, saved projects or firmware
changes. This is local candidate evidence, not a published release or CI hardware
certification. See [protocol provenance and investigation](display-investigation.md).

Normalized Python drawing alone left the LCD on its menu. Source-derived remote
start briefly showed a default face/chirp, but the program display disappeared
before drawing when the probe waited three seconds for an ACK. No 0x57 ACKs
arrived, despite the physical effect. Inspection of official VEXcom's delay
function revealed read-only remote-status polls every 100 ms. With that keepalive,
both start-before-REPL and start-after-REPL variants displayed the drawing and
emoji. The operator confirmed blue background, white circle, readable LCD TEST,
HAPPY and restoration of the drawing after hide. Numeric emoji 6 produced a
sunglasses face in the probe; named firmware constants produced HAPPY. White
text on white fill had independently caused a solid white bar.

The static-CRT portable Windows binary passed its PE dependency check (15 OS
imports; no Visual C++ runtime DLLs) and 33 installer assertions under PowerShell
5.1. Its normal screen command held HAPPY on the physical LCD. A local 240x240
LCD PNG (10,013 bytes) completed in 41.625 seconds with control ready. The first
integrated transfer had exceeded 45 seconds because every heartbeat also read
the pairing characteristic; the fixed read-only keepalive avoids that overhead.
Ordinary commands still check authentication. LCD transfers have a separate
55-second budget; native JPEG transfers retain 45 seconds.

Three connections with the final portable implementation passed display checks,
including a user-confirmed fresh boot and a manually selected Dashboard/AI Vision
camera view. HAPPY replaced that view, then the blue LCD TEST drawing appeared;
the operator confirmed both. Two further reconnects repeated HAPPY, drawing,
stop and live info successfully. HAPPY commands took about 0.54-0.56 seconds;
reconnect startup remained about 18.5-18.8 seconds. Reuse a session for ordinary
prompts. The original Robot object and marker 6518 survived activation and drawing.

During active display, native 640x480 JPEGs completed in 6.489 seconds (17,359
bytes) and 7.805 seconds (21,170 bytes), with control ready. The agent opened the
images and recognized the VEX controller/desk scene. Native heading, forward
acceleration, cargo and vision queries passed. Camera capture after stop also
passed in 6.500 seconds (17,503 bytes), after the required live info recovery
check. The first acceptance script omitted that recovery step and was correctly
rejected; a corrected follow-up passed. Photos/reports stay local and ignored.

Position stayed (0,0); heading changed only by about 0.007 degrees across the
clean-boot display/camera sequence, with no calibration. Final repeated checks
reported stopped at battery 27%, heading about 1.094 degrees and position (0,0).
No wheel or kicker commands ran. All sessions were explicitly closed. Menu-exit
reactivation, idle expiry, disconnects and no-replay behavior also have simulated
regressions; the physical takeover test used AI Vision as its starting screen.

## Device-command candidate (2026-10-20)

### Published rc.3 stationary follow-up

The unmodified, checksum-verified CI Windows 0.3.0-rc.3 binary connected to
AIM6518 in 18.794 seconds at battery 64%, stopped true. Its native camera
observation returned a 21,441-byte 640x480 JPEG in 7.976 seconds, with control
ready and stopped before/after. Codex opened the image in the same turn and
recognized the white VEX controller.

The acceptance run recorded 52 checks: 48 succeeded; robot-name and two link
queries were explicitly unsupported, and the happy emoji was rejected because
the dispatcher did not search the firmware's `Emoji` / `EmojiLook` aliases.
The read-only sweep included every acceleration/gyro axis, orientation, vision,
cargo, One Stick axes/buttons/battery, touchscreen coordinates/cursor, battery
and timer. Disconnected-controller and empty-cargo results do not verify real
button presses or loaded cargo. The live capability report transferred intact.

Adding the two emoji aliases to the transient helper made the native CLI
`screen show-emoji happy` return successfully. LCD screenshots after a circle
and happy emoji both remained the home menu (240x240 PNG, 13,296 bytes; 38.654 s
and 39.885 s). After a later reconnect, a six-second transient Python sequence
set blue LEDs, played CHIRP at volume 25, requested a happy emoji for three
seconds, then hid it and requested a white circle for three seconds. The user
confirmed blue lights and audible chirp, but the LCD stayed on its menu even
during execution. Lights/sound were cleaned up and live info confirmed stopped
at battery 60%. Visible display output remains unresolved in this REPL workflow;
the API acknowledgement alone is not acceptance. No wheel or kicker movement ran
during those stationary checks.

After fresh physical readiness on a clear floor, the published rc.3 owner ran
exactly one 15-degree right turn, 50 mm forward move, 20 mm left strafe, a
300 ms `(0,10,0)` native vector move, one SOFT kick and place. All six commands
completed successfully; stopped state was confirmed after each drive action
and at the end. Drive action times, including cleanup, were 893, 1,058, 629 and
533 ms respectively. The turn's gyro delta was about +15.30 degrees. The user
confirmed the movements and kicker looked right. This confirms the requested
directions and visible actuator behavior, not independently measured distances
or accuracy. Final battery was 55%. No failed movement was replayed.

The retry also exposed a preamble defect: a retained `robot` caused API imports
to be skipped, leaving ALL_LEDS/HAPPY undefined. Explicit imports restored both
on the live robot. The fix always refreshes VEX API imports while constructing
Robot only when absent. Tests cover both retained and newly constructed robots.
The acceptance harness now cleans up every effect in a finally block, reports
cleanup failures, distinguishes unsupported from failed checks, and cannot
report a completed sweep as passing when a read failed. These changes and the
emoji aliases are in rc.4; live evidence above uses rc.3 and transient fixes.

### Earlier rc.2 checks

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
software checks, independently of hardware evidence. USB sessions, catalogue
operations beyond the checks above, in-motion concurrency/cancellation, real
vision targets, linked second robot and closed-loop visual action acceptance
still need their own supervised checks. Asset upload encoding is unverified
and remains disabled; independent wheel signs/units are experimental.

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

The later [Windows Bluetooth investigation](windows-bluetooth-investigation.md)
records the 22 October 2026 OS-default connection-policy acceptance: a
60-minute interval without resets, the retained initial LCD deadline failure,
its successful corrected recheck, CI-built Windows camera/stop/cleanup and
10.1-second controlled recovery. It also records the image-transfer performance
trade-off and the exact build/firmware boundaries. It does not extend the older
coverage below to other platforms or second-computer handoff.

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
