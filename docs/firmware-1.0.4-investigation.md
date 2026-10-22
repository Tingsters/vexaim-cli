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
entry, but its effect on the inactivity timer has not yet been measured.

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
reference excludes discovery/setup and requires fresh status notifications,
uninterrupted host monitoring and a final read after 900 seconds. Its result
remains pending until that interval completes.

The ignored `stationary_source_lifecycle_control` test in
`dev/aim-lifecycle-rust.rs` prepares two separate source-derived controls:
the official connection's three remote-service notifications, or its built-in
REPL start. It accepts only the observed AIM REV1 / `1.0.4.b0` profile and a
confirmed no-program state, never stops/replaces an existing program, sends no
actuator command, and checks persistent Python state after 420 silent seconds.
The REPL control invokes only the named existing system binary, once, and stops
it at cleanup only if it is still the current program. No production behavior
is changed by an ignored diagnostic.

With VEXcode and ordinary CLI owners closed, select exactly one control:

```powershell
$env:VEXAIM_HARDWARE_READY='stationary-bluetooth-no-actuators'
$env:VEXAIM_HARDWARE_NAME='AIM6518'
$env:VEXAIM_LIFECYCLE_MODE='official-notifications' # or builtin-repl
$env:VEXAIM_LIFECYCLE_OUTPUT="$PWD/.vexaim/keepalive/lifecycle-control.json"
cargo test --locked --manifest-path cli/Cargo.toml -p vexaim stationary_source_lifecycle_control -- --ignored --nocapture
```

Full new-firmware acceptance is pending. These observations alone do not
establish a sleep-prevention mechanism or unchanged camera/display protocols.
Movement and kicker regressions
require a separate supervised readiness check. Two-robot behavior requires a
second robot and remains untested without it. Publish matching binaries/skills
only after the stated Windows hardware gate passes.
