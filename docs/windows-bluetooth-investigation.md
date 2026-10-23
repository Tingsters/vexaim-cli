# Windows Bluetooth adapter investigation

This is a transport investigation, separate from the AIM power lease. An awake
robot, a final LCD image and a cached ready result do not establish a live link.
The robot communicates over Bluetooth; "USB radio" refers to the computer's
Bluetooth dongle, not a cable to the robot.

## Established evidence

The 22 October one-hour core test recorded 33 automatic recoveries. Its 32
sampled outages averaged 21.63 seconds, totaled 692.30 seconds and reached
65.69 seconds. A subsequent offline correlation found a BTHUSB adapter
initialization event within ten seconds of **every** sampled outage (33 such
events during that interval). File creation time supplies the historical UTC
anchor, so this is not submillisecond synchronization.

Windows also repeatedly changed the radio's PnP LastArrivalDate. The active
Generic Bluetooth Radio uses USB `0a12:0001`, Microsoft's `bth.inf`, driver
10.0.26100.9711. Its parent is an ASMedia `174c:2074` USB hub under an AMD
USB 3.20 controller. The built-in MediaTek radio has problem code 22 (disabled),
not a newly established driver failure. No driver or power setting was changed.

BTHUSB 18 describes controller link-key storage; 34 describes unsupported
peripheral-role capabilities. Neither message alone proves the cause of a
central/client connection failure. Repeated initialization plus independent
PnP arrival changes is stronger evidence. The exact trigger is unresolved.

The released owner retains `ThroughputOptimized` for its whole lifetime, even
while idle. Microsoft's [connection parameter guidance](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.bluetoothledevice.requestpreferredconnectionparameters)
recommends using that request sparingly for bulk transfers. The investigation
compares it with no application parameter request. This is a hypothesis, not
evidence that the request caused the radio to reset. MaintainConnection and the
validated AIM power lease remain unchanged in both comparisons.

## Developer builds and one-time setup

Build with `cargo build --locked --release --manifest-path cli/Cargo.toml
--features ble-diagnostics`. Keep a verified released executable separately.
Only this feature reads `VEXAIM_DIAGNOSTIC_CONNECTION_PROFILE`, accepting
`throughput` (the default) or `os-default`. Normal builds ignore the override.
Owner health records requested/accepted/actual parameters and request errors.
Student commands and release defaults are unchanged.

Before unattended work, charge to at least 90%, put the computer on power and
move its Bluetooth dongle directly to a computer port. Then turn on the AIM,
unplug its USB cable and leave it stationary with an object in view. Close
VEXcode and any old CLI owner. Pair/verify access while the operator is present;
do not depend on a new code or operating-system prompt after they leave.

Distinguish robot power from the computer's power: a robot cable to the computer
enumerates AIM serial ports and its USB camera even when intended only for
charging. Remove it for the Bluetooth-only comparison. A wall charger can
support a separately labeled powered-link test, but cannot establish battery-only
sleep prevention. The runner checks Windows PnP for an AIM USB data connection
before starting clients and throughout measurement; detecting one invalidates
the Bluetooth-only result. Record external charging separately; PnP cannot see
a wall charger.

Maintainer runner (Python and websocket-client are **not student dependencies**):

```powershell
uv run --no-project --with websocket-client==1.8.0 python dev/ble_diagnostics.py `
  --released PATH_TO_RELEASED_EXE --candidate PATH_TO_DIAGNOSTIC_EXE `
  --name AIM6518 --output dist/ble-investigation/RUN --stationary-ready `
  --official-auth-stdin
```

Provide the existing setup code once on native stdin (use the agent tool's
retained input or a local masked prompt), never as an argument or saved file.
The code stays in memory for the official control and is not printed or saved.
No new pairing request is made. If the fresh link reports the source-defined
unpaired marker, restore this existing credential once and verify the readback;
a different active credential stops the run without overwriting it.

Use a fresh output directory for every run. `--baseline-only --baseline-seconds
180` collects a host-only baseline without connecting either application; it
does not need `--stationary-ready`. An optional `--recovery-test-exe` points to
the diagnostic Rust unit-test executable for its separately labeled controlled
disconnect test, after uninterrupted confirmation has finished.

If a control run ends before reaching the candidate, `--candidate-only` performs
a separately labeled follow-up using only the OS-default executable. Do not
pass `--official-auth-stdin` for this mode. The new report records skipped
controls as unavailable; it does not convert the earlier failed run into a pass.
Verify that the prior runner and its contained owners exited first. The candidate
must still pass live setup, its short comparison and uninterrupted confirmation.

The Windows monitor reads PnP properties and System BTHUSB metadata. It changes
no logging policy and needs no administrator permission. It captures no raw
HCI/GATT data or PIN values. Fine-grained elevated USB tracing is a separate
investigation only if these measurements cannot isolate the failure; obtain
approval up front before adding it. Do not disable USB selective suspend globally.

## Automatic phases and interpretation

After initial live stopped/battery verification, the runner observes official
VEXcode's bundled Bluetooth library for three minutes, the release for five,
and the OS-default candidate for five. Only one client is connected. An initial connection/authentication
problem is incomplete, not an unattended request to pair. Both CLI variants use
the same firmware-gated finite power lease. A failed phase stays failed.

The official control launches its own hidden installed Windows VEXcode instance
and uses its AIM device-manager class through local Chrome debugging. It replaces
only the credential UI callback with the existing-code verification described
above and observes status-notification freshness without recording payloads.
This is a library control, not an untouched UI workflow or an official power-lease
test. It runs no student project. The installed lazy BLE chunk is read in place;
no proprietary source is committed. Missing bundles, failed authentication or
missing fresh notifications make setup incomplete rather than passing a cached
connection state. `setup_verified` marks the start of unattended measurements.

If the release passes, confirm that released configuration on the current host
path. If only the candidate passes, confirm the candidate. If neither passes,
stop and analyze the host/driver evidence rather than inventing robot APIs.
The final confirmation lasts 60 minutes with live battery checks once a minute,
then local camera, drawing and stop checks. **Any** spontaneous disconnect or
adapter arrival during confirmation fails uninterrupted reliability, even if
automatic recovery succeeds. This is not the previous 35-minute no-live-command
sleep measurement and must not be labeled as one.

Two adapter arrivals stop a short comparison. Authentication changes, unknown
battery, battery below 20%, uncertain cleanup, monitoring failure or the
90-minute whole-run deadline stop affected work without asking for attendance.
An outage may recover for at most 90 seconds. Reports and photos remain local.
There are no wheels, kicker, menu-navigation, reset, firmware or saved-project
operations. The harness closes its investigative owners, restores normal robot
power policy where the link permits it, and releases its temporary host awake
request. A private Windows job contains new child processes so an interrupted
runner cannot leave a detached test owner alive. Failed power cleanup is reported
as uncertain; it is not silently relabeled as success.

The v0.4 close reply confirms stopped state before final transport/power cleanup.
The runner therefore waits for its owner process to exit before another client
connects. v0.4 does not return independent power-restoration confirmation; the
report explicitly records that verification as unavailable rather than claiming
an acknowledged stop proves it. Startup failures never use an invented
`--name ... session close` interface.

When a measurement fails during reconnection, allow the existing owner up to
60 seconds to recover, verify live stopped state, then close it. Sending v0.4's
close while its link is unavailable terminates that owner even if its initial
stop fails, preventing further repair. A failed measurement remains failed;
uncertain cleanup is recorded separately and prevents starting another client.

No corrective release is justified by correlation alone. Promote a software
change only after the controlled measurements and functional acceptance pass.
If moving the radio changes the result, report that host-path change separately
from any connection-parameter change.
