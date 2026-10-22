# Windows AIM 1.0.4 investigation

## Evidence and scope

On 2026-10-21 the operator installed Windows VEXcode AIM and completed its
offered 249-8581-000 update from VEXos 1.0.0 to 1.0.4. The official app had
required an update before allowing the requested Bluetooth connection. This is
operator evidence; diagnostic version readings and new-firmware endurance must
be recorded separately. Do not downgrade the robot or overwrite saved projects.

The earlier 1.0.0 tests remain failed evidence: 92 acknowledged legacy System
Alive polls did not prevent the observed loss. Short errors that recovered
without physical power-on are transport failures, not confirmed sleep.

Windows PnP inspection after installation found the AIM's two serial interfaces
using Microsoft `usbser.inf`, its composite interface using `usb.inf`, and its
camera using `usbvideo.inf`. The Bluetooth stack uses Microsoft and MediaTek
drivers. VEX Drivers 2.0.0 also installed packages for several other products;
their presence is not evidence the AIM requires them. No driver was changed by
this investigation. Both host software and firmware changed, so successful
post-update behavior alone cannot identify which change caused an improvement.

A later read-only Windows check found a healthy Generic Bluetooth Radio using
Microsoft's driver and a MediaTek adapter with problem code 22. Microsoft defines
[Code 22 as a disabled device](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/cm-prob-disabled),
so its broad `Error` status must not be mistaken for a newly detected radio fault.
No relevant sleep or Bluetooth power event was found in the recent System log;
that absence alone does not prove a firmware cause. Adapter state, drivers and
Windows power settings were left unchanged.

## Official source reference

The installed Windows VEXcode AIM 4.67.0 archive is read locally by
`dev/inspect-vexcode.py`. Its SHA-256 is
`e1a87163d40f1c779cc7a9067d896e1e115952c9f4a4f46dde9ab8a2c8348c13`.
Extracted code and its manifest remain ignored under `.vexaim/keepalive`.

The AIM-specific `getConnectedDeviceInfoAIM` path in the bundled Bluetooth
manager reads GATT `2a26` into `appVersion2`, and `2a28` into `appVersion`.
The former is the existing CLI's `firmware` field. It must not silently be
renamed to a bootloader version: other products interpret the same generic
characteristic differently. The CLI preserves it and adds explicit
`gatt_firmware_revision` and `gatt_software_revision` fields. A single known
read-only SYS_STATUS request also records VEXos, CPU0 and CPU1 versions when
available; absent or failed optional readings are unknown, not zero versions.

The official AIM interface's firmware check compares against its current
catalogue and checks disagreement between CPU0 and CPU1. That is an identified
update condition, not proof of the particular reason for the operator's prompt.
Its AIM connection path authenticates after service/characteristic discovery,
then enables admin and remote-control status notifications. This source trace
does not yet establish a sleep-prevention mechanism. No other product's
`disableSleep` method is eligible for use on AIM.

The collector also includes the Windows Electron entry point and preload bridge.
The bridge delegates Bluetooth device selection to Chromium; inspection found no
AIM sleep-maintenance loop there. In the AIM-specific terminal path,
`sendDataUserPort` checks program state and starts built-in system program 2
before writing terminal input when no program is running. The Bluetooth manager
implements that start through the existing file-load/run protocol with system
vendor `0x0f` and name `___v_02.bin`. This invokes an installed system program;
it uploads no file. It is a concrete lifecycle difference from direct raw-REPL
entry; its power behavior must be measured independently of its program field.

No public AIM-specific changelog for 1.0.1 through 1.0.4 was located during this
review. The source-defined public firmware catalogue returned HTTP 403 to a
normal request. Record these gaps rather than applying V5/EXP/IQ release notes.
The [official firmware update guide](https://kb.vex.com/hc/en-us/articles/34955238148372-Updating-VEX-AIM-s-Firmware)
describes the update process but does not enumerate those release changes.
The [Link AIM guide](https://kb.vex.com/hc/en-us/articles/40659133746964-Linking-and-Unlinking-Two-VEX-AIM-Coding-Robots)
documents the observed menu feature but does not identify its introducing release.

## Autonomous stationary procedure

Prepare and test all tooling before asking the operator to wake the robot.
Collect charging, exact robot, fresh restart, USB disconnection, One Stick off,
VEXcode closure and masked pairing together. Put an object in front of the
camera. No wheel or kicker command belongs in these runs.

With the operator present, run:

```powershell
uv run --no-project python dev/attention.py --directory .vexaim/attention/aim104 rehearse
```

Explain that the three-note computer chime means return for one specific action.
Only after the operator confirms it is audible from where they will be, run
`confirm-heard` with the same directory. Playback success does not prove hearing.

For later intervention, checkpoint the hardware phase and present one action
and its reason in chat before invoking `request --action TEXT --reason TEXT`.
It saves `pending.json`, sounds at 0, 60 and 120 seconds, and waits at most ten
minutes. The agent uses `reply REQUEST_ID` only after an actual operator reply;
`--cancel` declines the request. Verify the physical condition before resuming.
The helper never connects to the robot, changes system volume or authorizes
movement. Requests expire incomplete; a late/stale reply cannot resume a run.

The endurance harness exits 0 only for a full pass, 1 for a failed measurement,
and 2 for an incomplete/cancelled measurement. It checkpoints phases and results,
uses a persistent REPL nonce, and records system time without assuming its reset
semantics establish a reboot. Waiting for the operator never counts toward
endurance. Failed runs stay failed even after recovery; start a new report.

Use a checksum-verified published rc.6 binary first, unchanged, on the updated
robot. An unfamiliar-version rejection is a compatibility gate result, not a
failed camera or proof that the new firmware broke it. `--allow-inactive-monitor`
permits an explicitly labeled baseline to measure firmware without an enabled
CLI link monitor; it never establishes sleep prevention from cached health.

Require two clean-boot runs of at least 1200 seconds, each with two 420-second
quiet windows separated by camera/display/stop checks. During quiet windows,
the harness sends cached IPC reads only. After an unexpected failure, permit
at most three read-only recovery attempts to classify it; ask for physical help
with the rehearsed cue only when required. Keep the old measurement's result.

If the unchanged combination passes, add no speculative maintenance operation.
Otherwise run an isolated 15-minute official Windows VEXcode reference, inspect
its actual Bluetooth behavior and implement only a source-supported difference.
Never connect the CLI and VEXcode simultaneously. Automatic remote-program LCD
ownership is acceptable if proved necessary, with responsive stop and explicit
close. Existing motion and owner inactivity deadlines remain unchanged.

## Acceptance status

The unchanged published rc.6 baseline connected wirelessly at 94% battery and
reported stopped. Its unfamiliar-profile gate disabled legacy System Alive.
After 420 seconds with no foreground or background CLI radio traffic, the next
live read reported a disconnected link; a fresh connection attempt and a scan
found no AIM6518. This run failed before camera/display checks. Discovery loss
alone does not establish physical power-off or its cause. Its local report is
under `.vexaim/keepalive/firmware104-baseline-1`.

After the operator's next power-on, installed Windows VEXcode authenticated
automatically and read both GATT application revisions as `1.0.4.b0`. A local
DevTools observation records characteristic UUIDs, command IDs and notification
counts without recording authentication bytes or terminal payloads. The timed
reference excluded discovery/setup and required fresh status notifications,
uninterrupted host monitoring and a final read after 900 seconds. It failed:
the connected state disappeared at 841 seconds of timed observation. The last
status notification arrived about 899 seconds after the last setup command;
Windows reported disconnection about ten seconds later. Approximately 9004 robot
status and 9001 AI-status notifications arrived, with no recurring host writes.
A new CLI connection attempt and scan found no AIM6518. This is consistent with
an approximately 15-minute idle limit on that connection, but neither the timer's
implementation nor physical power-off was independently established. The local
redacted report is `.vexaim/keepalive/official104-reference.json`.

Consequently matching idle subscriptions alone is not accepted as sleep
prevention.

The built-in terminal start returned code `0x01`, classified as `WriteError` by
the generic CDC library. Its encoded packet matches the installed official
builder byte for byte. Follow-up read-only inspection captured the LCD showing
`REPL Mode`, screen ID 19 and program field 27. Therefore the generic NACK alone
did not establish that no state change occurred. No start was replayed, and the
generic ACK decoder was not loosened. System-directory enumeration listed only
`settings.bin`; the built-in mode did not require a file upload.

A separately labeled continuation adopted that known control's REPL. Raw console
entry retained program field 27 and read stopped state at system time 703337 ms,
74% battery. The Bluetooth connection disappeared after 70 quiet seconds, before
its requested 1200 seconds completed; subsequent discovery found no robot.
This control also failed. Neither a visible REPL mode nor its program field
establishes sleep prevention.

The compatibility candidate now recognizes exactly AIM REV1 / `1.0.4.b0` alongside
the previous `1.0.0.b0` profile. The new revision was read from both GATT fields,
VEXos and both CPUs. This permits the existing acknowledged System Alive health
monitor and bounded camera/display checks; it changes no wire request, firmware,
saved program or movement default. VEXcode itself sent System Alive on 1.0.4.
The candidate still reports `prevents_sleep:false`. Its first hardware run also
failed: startup reported stopped at 73% battery; the harness sampled 71% battery
at system time 223041 ms. The link monitor reached 124 acknowledged polls before
three consecutive failures stopped it. The quiet interval ended after 86.7
seconds, before either camera/display phase. Live info could not reach the robot;
one new connection attempt and a scan found no AIM6518. The timing is consistent
with the earlier approximately five-minute loss, but physical power-off was not
independently observed in this unattended run. Firmware 1.0.4 plus the existing
System Alive monitor is therefore also a failed sleep-prevention candidate.
No speculative power API or built-in-program activation was added to production
startup. The local report is under
`.vexaim/keepalive/firmware104-monitor-acceptance-1`.

The next isolated comparison is executing Python versus waiting at a REPL.
`dev/probe-python-lifecycle.py` uses only the documented AIM
[`wait`](https://api.vex.com/aim/home/python/Logic/Controls.html) and
[`Thread`](https://api.vex.com/aim/home/python/Logic/Threads.html) primitives.
Its `main` mode runs a finite waiting loop; its `thread` mode runs the same loop
in a background thread and returns to the console. Neither mode moves the robot,
uploads a saved project, presses menu buttons or calls a possible power API.
This tests a program-lifecycle hypothesis, not a documented sleep-prevention
promise. Each report requires a persistent marker, advancing loop count, full
robot/host interval and final live stopped state. A passing seven-minute control
would still not satisfy the full acceptance gate or justify a release claim.

The persistent-session API limits an individual `exec` request to 120 seconds.
Thread startup therefore uses a 30-second request regardless of the observation
duration. A short `main` control can use 60 through 90 seconds. For a longer
`main` comparison, explicitly select the verified robot with `--standalone-name`:
the probe checks identity and stopped state, closes the session, waits for its
local endpoint to disappear, then uses one standalone Bluetooth execution.
That comparison has no background System Alive monitor. No production timeout
or motion deadline is increased. Select unused report paths; old reports cannot
be overwritten.

```powershell
uv run --no-project python dev/probe-python-lifecycle.py <candidate.exe> --session <ID> --mode thread --duration 420 --output .vexaim/keepalive/python-thread-104.json
uv run --no-project python dev/probe-python-lifecycle.py <candidate.exe> --session <ID> --mode main --duration 420 --standalone-name AIM6518 --output .vexaim/keepalive/python-main-104.json
```

On the next power-on, a first `main` attempt was rejected locally because the
probe requested 450 seconds through the session API. No long Python ran; this
is a harness failure, not robot sleep evidence. After correcting thread startup
to 30 seconds, the background Thread returned its marker successfully, starting
at 69% battery and stopped. Its link monitor failed after 162.343 seconds; the
operator independently saw the robot power off and switched it on again.
Starting a background Thread therefore did not solve the observed problem.

The first standalone handoff was also refused locally while its closing session
endpoint still existed. The probe now observes endpoint release before opening
another connection. A fresh report then ran the main-loop comparison with a
finite 420-second waiting loop, starting at 66% battery and stopped. It returned
no final Python frame; after 466.218 host seconds the CLI failed with Bluetooth
HRESULT `0x80000013`, "The object has been closed," during a write. A new named
diagnostic found no AIM6518. This is failed connectivity evidence; the exact
disconnect time and physical power state were not independently recorded for
this run. The local reports are `python-lifecycle104-thread-1.json` and
`python-lifecycle104-main-3.json` under `.vexaim/keepalive`.

The already sourced next control combines acknowledged System Alive with the
official Back input on verified home screen zero. Its fixed packet and guards
are described in the [earlier investigation](keepalive-investigation.md). This
tests the remaining UI-inactivity hypothesis without a guessed power API; the
firmware-1.0.4 run was prepared. Passing requires seven acknowledged home-only
inputs, 420 seconds and final live stopped/system-time checks. A lost input ACK
aborts without replay.

That control subsequently acknowledged one Back input on confirmed home screen
zero and completed three polls through 4.543 seconds. It then failed with Windows
HRESULT `0x800704C7`, "The operation was canceled by the user." This error text
alone does not establish operator cancellation. A fresh CLI session reconnected
without another power cycle, at 64% battery and stopped. Classify this short
failure as transport loss, not confirmed sleep or a passing Back control.

The recovered session completed the first new-profile native camera observation:
a 27732-byte 640x480 JPEG in 10875 ms, with stopped state before and after and
`control_ready:true`. Local pixel inspection shows the controller on the floor.
The photograph remains ignored and local. Bluetooth JPEG retrieval on the
observed 1.0.4 profile therefore has direct evidence; display/stop and full
endurance acceptance remain separate.

Read-only runtime inspection also found `robot._sleep_disable`: it is callable,
its type is `bound_method`, and its docstring is absent. Its SDK module identifies
itself as `vexbdev.py`. No call site was found by searching all packaged VEXcode
JavaScript, JSON, Python, HTML and text assets, and no public `vexbdev` source was
located. Do not claim it is new in 1.0.4 or that its signature/semantics are known.
The first source read was interrupted by link loss. On a fresh power-on,
`open('vexbdev.py')` failed with `ENODEV`; the module's reported filename does not
establish that its source is accessible. A metadata probe also incorrectly
assumed the module exports `Robot`; its `AttributeError` occurred before any
helper call. Correcting inspection to `type(robot)` avoided that assumption.
The read-only `dev/inspect-power-api.py` prints metadata without calling the method.

The actual bound helper accepts a zero-argument call and returns Boolean `False`.
A subsequent explicit call with `True` returned `None`, and immediate zero-argument
readback returned `True`. These establish a query/setter interface on this robot,
not its power-management semantics. Both stationary endurance controls failed:

| Control | Initial robot time | Measured interval | Final link health |
| --- | --- | --- | --- |
| No-argument helper call | 140039 ms | 166.922 s | 99 acknowledged polls, then three failures |
| One `True` setter and readback | 41842 ms | 267.704 s | 132 acknowledged polls, then three failures |

Live info then reported the link down, and discovery found no robot. Both failures
occurred around five minutes of boot-relative time, including failure-detection
delay; exact physical shutdown times were not independently observed. Neither
run reached camera/display/stop acceptance. Do not treat a successful setter or
`True` readback as verified sleep prevention. These one-time setter controls
were not adopted as a standalone startup fix; the later combined integration
is described below.

A fresh short lifetime check retained the same `id(robot)` and `True` helper value
across a subsequent raw execution, the ordinary exec preamble, live info and stop.
The stop guard correctly required a fresh `info` before the next exec; the first
attempted post-stop query was rejected locally. Recovery confirmed the flag still
read `True`. Ordinary commands clearing the setting therefore do not explain
the earlier failure.

The next isolated comparison holds that same observed setting inside one finite
main-thread execution. `dev/probe-python-lifecycle.py --observed-sleep-control`
is explicit opt-in, requires the complete observed 1.0.4 profile, checks readback,
and restores the original Boolean setting in `finally`. Its default controls
still call no private power helper. The option supports only finite main mode;
it neither extends the normal 120-second session limit nor uploads a saved
program. A long comparison uses the existing explicit standalone handoff:

```powershell
uv run --no-project python dev/probe-python-lifecycle.py <candidate.exe> --session <ID> --mode main --duration 420 --standalone-name AIM6518 --observed-sleep-control --output .vexaim/keepalive/sleep-main-104.json
```

This comparison is not the two fresh-boot 20-minute acceptance gate. A result
requires the final worker frame, requested robot/host interval, verified original
setting restoration and a live stopped sample after reconnecting. Local tests
cover finite execution, restoration after a worker exception, preservation of a
preexisting `True` state, and refusal of unsupported modes. No sleep fix has been
accepted from the helper discovery.

The main-with-helper comparison subsequently failed after 466.485 host seconds
with Bluetooth HRESULT `0x80000013` during a write. No final worker frame,
readback or restoration result returned; a fresh scan found no robot. Do not
claim the helper remained effective inside that execution or that restoration
was confirmed. Its earlier ordinary-command persistence is separate evidence.

A later short stopped-state comparison alternated the flag False/True/True/False
and timed 30 battery reads and 30 stopped-state reads per setting. Every batch
took 0 or 1 ms. This found no measurable effect on these cached getters; it does
not establish the helper's purpose. Its original `False` value was restored,
the robot reported 53% battery and stopped, and the CLI session closed normally.

The official-app trace was also audited for an omitted write route: it wraps
`writeValue`, `writeValueWithResponse` and `writeValueWithoutResponse`, in addition
to reads and notification subscriptions. No obvious unobserved Web Bluetooth
write method explains the idle trace. This remains application-level evidence,
not a capture of Windows HCI or link-layer packets.

One combined control remains unmeasured: the official built-in REPL and the
observed SDK setting together. Prior controls measured each separately; their
failures do not establish the combination's behavior. The opt-in ignored Rust
mode `builtin-repl-sleep` first verifies no student program is running, starts
only the existing system REPL, proves program 27 AND screen 19, checks all
reported 1.0.4 revisions and stopped state, then sets/readbacks the actual helper.
It observes 1200 quiet seconds by default. Acceptance requires persistent state,
the final True readback, restoration of the original setting and stopping only
its own REPL. Unconfirmed cleanup is failure. This is a developer experiment,
with no new power opcode or saved-program upload. Normal integration is tracked
separately below.

The first combined setup did not reach the helper call or quiet measurement:
the source start confirmed program 27/screen 19, but ordinary raw-console entry
then reported program 0/screen 0. The guard rejected the control. This is a
lifecycle initialization failure, not new sleep evidence. The normal sync path
sends two Ctrl-C interrupts before Ctrl-A; an interrupt can end the system
program that this comparison needs to retain.

The developer-only comparison now waits for an actual friendly or raw prompt,
then enters raw mode with Ctrl-A when necessary, without an interrupt fallback.
The next run retained program 27/screen 19, read the original sleep value False,
set/read back True, and began the 1200-second quiet interval at robot time
119837 ms, 49% battery and stopped. Four simulated
console tests cover fragmented prompts through the first execution, an already
raw console, a missing friendly prompt and a failed raw transition. Production
sync remains the interrupting path; the candidate uses the waiting entry only
for its verified system REPL. Hardware stop/recovery validation remains pending.

This combined control completed 1200.014 quiet seconds with no foreground radio
requests. The final live read retained marker 119836, advanced robot system time
from 119837 to 1320275 ms, reported stopped and read the helper as True. Battery
changed from 49% to 36%. Restoration of the original False setting and stopping
the owned system REPL both confirmed. The local report is
`aim104-repl-sleep-combination-0fc3604ffa3e4a0b8786031222e955ed.json`.
This is the first complete mechanism control to pass. It does not yet establish
ordinary CLI stop/display/camera recovery or two fresh-boot candidate acceptance
runs. The normal CLI integration is described below.

The current integration candidate now prepares that context during supported
Bluetooth session startup. It refuses to replace an unowned running program,
preserves the system REPL at raw entry, and installs a transient Thread watchdog
with a lease bounded by the existing 30-minute client-idle deadline. Real client
work renews it; cached status and health probes do not. The watchdog restores the
original Boolean on expiry, including across the system millisecond counter's
32-bit wrap. Stop/display teardown can end the REPL; recovery checks native
program ownership and stopped state before rebuilding only that context. A
failed background recovery suspends itself until explicit live info and never
replays a student action. USB and unsupported profiles use their earlier paths.

For a warm reattach, the candidate refreshes the friendly prompt with Ctrl-B
before entering raw mode with Ctrl-A, and verifies the native program/screen
again afterward. The [upstream MicroPython console implementation](https://github.com/micropython/micropython/blob/master/shared/runtime/pyexec.c)
defines these as console-mode operations; Ctrl-D is the separate soft-reset
operation. The AIM port still requires hardware validation. No Ctrl-C fallback
is used for this waiting entry.

Fourteen simulated SDK tests cover expiry without renewal, original True/False
restoration, failed/stalled worker startup, foreign/old owners and counter wrap.
They do not prove actual Thread scheduling. Candidate acceptance still requires
a hardware watchdog-expiry check, camera/display/stop recovery and two clean-boot
20-minute runs. No release is accepted from software tests alone.

The ignored `stationary_source_lifecycle_control` test in
`dev/aim-lifecycle-rust.rs` prepares source-derived controls:
the official connection's three remote-service notifications, or its built-in
REPL start. It accepts only the observed AIM REV1 / `1.0.4.b0` profile and a
confirmed no-program state, never stops/replaces an existing program, sends no
actuator command, and checks persistent Python state after 1200 silent seconds
by default (`VEXAIM_LIFECYCLE_SECONDS` allows 420 through 1800 for labeled controls).
The REPL control invokes only the named existing system binary, once, and stops
it at cleanup only if it is still the current program. No production behavior
is changed by an ignored diagnostic.

With VEXcode and ordinary CLI owners closed, select exactly one control:

```powershell
$env:VEXAIM_HARDWARE_READY='stationary-bluetooth-no-actuators'
$env:VEXAIM_HARDWARE_NAME='AIM6518'
$env:VEXAIM_LIFECYCLE_MODE='official-notifications' # or builtin-repl / builtin-repl-sleep
$env:VEXAIM_LIFECYCLE_SECONDS='1200'
$env:VEXAIM_LIFECYCLE_OUTPUT="$PWD/.vexaim/keepalive/lifecycle-control.json"
cargo test --locked --manifest-path cli/Cargo.toml -p vexaim stationary_source_lifecycle_control -- --ignored --nocapture
```

Full new-firmware acceptance is pending. The native JPEG check passed separately;
these observations do not establish sustained sleep prevention or display recovery.
Movement and kicker regressions
require a separate supervised readiness check. Two-robot behavior requires a
second robot and remains untested without it. Publish matching binaries/skills
only after the stated Windows hardware gate passes.
