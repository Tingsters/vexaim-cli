# Historical hardware evidence

These dated investigation notes were imported from the original workshop.
For current installation and commands see ../README.md and the generic vex-aim
skill. Development-version references below describe the binaries tested then.

# Bluetooth development and hardware verification

The published `vexaim 0.1.1` CLI supports USB. The local **0.2.0-dev** CLI now
implements explicit Bluetooth selection, native credential storage, Python
commands and camera snapshots. It is not a published Bluetooth release; the
remaining hardware and platform acceptance checks below still apply.

Upstream fixes have been submitted as
[btleplug #505](https://github.com/deviceplug/btleplug/pull/505) and
[vex-v5-serial #23](https://github.com/vexide/vex-v5-serial/pull/23).
The workshop vendors the patches while those PRs await review/release; native
JPEG capture and credential handling are implemented in this workshop's CLI.

**New result:** the source-defined CDC capture layer `8` returned a genuine
**640x480 camera JPEG** from AIM6518 over Bluetooth in **3.453 seconds** from
capture request through raw file completion. The complete 13,641-byte image
passed packet CRC/address/length checks and JPEG framing, and was decoded and
visually verified: it showed the VEX controller with **no LCD border or back
button**. Windows confirmed USB absence. This supersedes the earlier assumption
that only the LCD buffer was available. The instructor probe now provides
`--native-camera --jpeg-output PATH`. Subsequent controls also passed from a
fresh boot/home screen, with three visibly different frames and same-session
Python recovery. **Camera capture needs no LCD navigation, preview or reset.**
This establishes camera feasibility on this robot; full wireless release
acceptance remains separate.

## Development CLI

Build from the workshop root with an existing Rust toolchain:

```powershell
cargo build --locked --manifest-path cli/Cargo.toml
.\cli\target\debug\vexaim.exe bluetooth scan
# Pair in a local interactive terminal; type the code only at the hidden prompt.
.\cli\target\debug\vexaim.exe --name AIM6518 bluetooth pair
.\cli\target\debug\vexaim.exe --transport bluetooth --name AIM6518 doctor
.\cli\target\debug\vexaim.exe --transport bluetooth --name AIM6518 info
.\cli\target\debug\vexaim.exe --transport bluetooth --name AIM6518 snap -o dist/camera.jpg
```

Use the exact robot name from the scan, close VEXcode, and leave the robot on.
For these wireless acceptance tests disconnect USB. The normal USB workflow is
still the default; commands never fall back to another transport or silently
choose a different robot. `--device N` is a USB index and cannot select BLE.
Linux/macOS use `./cli/target/debug/vexaim`; their hardware checks are pending.
Combined Linux source builds require `libudev-dev`, `libdbus-1-dev` and
`pkg-config`; the CI and release workflows install these. USB-only source builds
can use `cargo build --no-default-features --manifest-path cli/Cargo.toml`.
Students using prebuilt 0.1.1 must use USB until a Bluetooth release is available.

The development CLI supports `exec`, `info`, `doctor`, `stop` and `snap` with the
Bluetooth flags above. `exec` has the same imports, timeout and interruption
behavior as USB. A stop still needs a working connection. Snapshots save the
native 640x480 JPEG without changing LCD mode; packet CRCs, block addresses,
lengths, JPEG markers and frame dimensions are checked before atomic replacement.
`--json` includes transport, dimensions and capture latency for snapshots.
Unsupported firmware stops without trying other layers or menu/reset commands.

Pairing stores numeric digits in the native OS vault, keyed to the selected
peripheral identity. The Windows CLI can reuse the instructor probe's existing
credential after checking the entry's username, and saves a CLI entry only after
successful authentication. No PIN arguments, echoed input or plaintext fallback
are provided. `--name NAME bluetooth forget` removes the CLI and matching legacy
Windows entries for that visible robot; it does not unpair the robot itself.
Linux requires an unlocked Secret Service and D-Bus; macOS uses Keychain and
its peripheral UUID, since CoreBluetooth does not expose a MAC address.

### Native camera feasibility controls: passed on Windows

All frames below were downloaded over separate authenticated BLE connections
with Windows confirming USB absence. The JPEGs were inspected locally at
640x480, without cropping or recompression; none had LCD UI overlays.

| Local evidence in `dist/` | Visible scene | Capture request to saved JPEG | LCD before/after | Python recovery |
| --- | --- | --- | --- | --- |
| `ble-native-home` | Close-up VEX controller | 2.594 s | home `0` / `0` | Console untouched |
| `ble-native-recovery` | Controller farther back on the desk | 4.594 s | home `0` / `0` | Passed, battery 38%, stopped true |
| `ble-native-spinner` | Pink spinner replacing controller, as confirmed by student | 4.781 s | home `0` / `0` | Passed, battery 37%, stopped true |

Each stem has a JSON protocol report and JPEG. The native capture also worked
in AI Vision mode earlier (`ble-native-jpeg-layer-eight.json`, 3.453 s to raw JPEG).
Both Python controls retained system and user notifications through the
post-capture state read. This passes the camera feasibility gate on
AIM6518 / REV1 / BLE firmware `1.0.0.b0`, including visible freshness, operation
from the home screen and Python recovery. The ten-frame release run, full sensor/
actuator checks, incorrect-code/reconnect stress tests and other OS hardware
checks remain outstanding. The student later reported another power-off after
the successful tests; no shutdown/reset command was sent and its cause is unproven.

### Compiled Windows CLI: stationary live checks

The local 0.2.0-dev binary reused the existing credential and reported `ready`
with MicroPython core 1.22.0, compatibility 3.4.0 and battery 35%. `info` read
stopped true, battery, heading and position. A native 640x480 spinner JPEG first
took 26.754 s (21,656 bytes). After adding a temporary throughput preference and
retaining its request for the connection lifetime, another capture took
**7.908 s** (22,029 bytes), with an actual interval of **15,000 microseconds**.
Both images were decoded and visually inspected locally. A separate `info`
connection afterward passed with battery 33%, stopped true and position `(0, 0)`.
This is stationary functionality evidence, not a completed stress/motor test.

The first Rust doctor authenticated but got zero REPL bytes. The Windows
`btleplug` 0.13.5 backend preferred **indications** when both modes were
advertised. A controlled Bleak run forced to indications reproduced zero user
bytes; normal notifications worked. The vendored Windows backend now prefers
**notifications** and retains both VEX subscriptions through Python work. The
next Rust doctor succeeded. One later service-enumeration failure had appeared
as missing characteristics: the library now propagates a failed Windows GATT
status instead of returning an empty service list. No robot command is retried
after an uncertain delivery.

Local photos: `dist/ble-cli-spinner.jpg` and `dist/ble-cli-spinner-fast.jpg`.
Indication control: `dist/ble-indicate-control.json`; normal notification
control: `dist/ble-rust-control.json`. These contain no pairing code.

## What has been observed

On Windows 11 on October 19, 2026, a working Bluetooth radio discovered
`AIM6518`. Its advertisement contains service `0x0670`, rather than the V5
service UUID used by the original library filter. A transient, read-only GATT
connection succeeded with MTU 256. Device Information reports model `AIM`,
hardware `REV1`, and firmware/software `1.0.0.b0`.

The connected robot exposes the VEX system, user and Code characteristics.
TXUser supports notifications and indications, but **does not support reads**.
Other characteristic labels are `Command`, `RC_Cmd`, `RC_Status` and
`RC_AI_Status`. These names do not establish an image-transfer protocol.
The initial OS bonding state was false and the VEX Code characteristic reported
the unpaired sentinel. Neither discovery nor GATT connection establishes
successful pairing, Python execution, or camera access.

The subsequent cable-free test **did** authenticate with the displayed code,
save it in Windows Credential Manager, enter raw REPL, and read battery 100%
and stopped true. Separate process reconnects reused the stored credential while
Windows still reported OS bonding false. Later pre-capture checks read 97%,
94% and finally 93%, with stopped true.
An attempt made with USB attached was rejected before pairing and is excluded
from wireless results. The native Python vision object has no
`get_camera_image`; importing a `camera` module failed. A valid-CRC CDC screen
capture request received ACK `0x76`. A full **115,200-byte LCD framebuffer** was
then read over BLE in **27.406 seconds**, validated per packet, decoded as
240x240 RGB565 and saved locally as a JPEG. The student inspected it and confirmed
that it showed **LCD screen contents, not a camera scene**. Requesting the camera
preview beforehand did not establish camera capture. Capture layer 1 returned an
empty buffer; the probe now rejects empty buffers before issuing any data read.

Those initial tests did not pass the camera gate. A subsequent test with the
student selecting AI Vision mode manually **did retrieve recognizable camera
imagery over BLE**, as recorded below. Subsequent AIM-specific Bluetooth
navigation also selected AI Vision without manual screen interaction. Clean
full-scene capture and latency were still incomplete at that stage. The native
JPEG controls above supersede that camera limitation. Motor/full-sensor
acceptance and a Bluetooth release remain pending.

Console recovery after the initial LCD transfer failed. The student confirmed
that the robot had switched off when subsequent discovery failed. VEX documents
[sleep after five minutes of inactivity](https://kb.vex.com/hc/en-us/articles/34911195338772-Charging-and-Powering-On-VEX-AIM);
that is a possible explanation, not a proven cause. The probe's use of an
upload-completion `FILE_EXIT` command was removed to match the library's read-only
download behavior. The later spike below established a separate notification
subscription problem and a working recovery strategy while the robot remained
on. It did not establish the cause of the earlier power-off.

The vendored backend now recognizes the AIM advertisement, bounds discovery,
deduplicates devices, receives user data through notifications, preserves partial
reads and interleaved system traffic, reassembles system frames, and limits
writes to the negotiated MTU and firmware packet ceiling. Authentication values
are validated without logging them. Bluetooth-only builds now include their
timer dependency. These changes have local Windows unit coverage; hardware
acceptance remains separate.

## Native JPEG snapshot (instructor development)

Use the existing saved credential; pair separately first if necessary. Keep USB
unplugged and VEXcode closed:

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --native-camera --jpeg-output dist/camera.jpg --report dist/camera.json
```

This sends the native JPEG capture request and downloads the returned `screen`
Cbuf with the established read-only file protocol. It never enters Python,
requests a preview or sends menu presses. It requires the calibrated AIM REV1 /
BLE firmware `1.0.0.b0`; home-screen capture is now verified too. Native bytes
are already JPEG, so this path needs no PowerShell
converter and performs no resizing, cropping or recompression. Both JPEG frame
markers and SOF dimensions are checked before the destination is atomically
replaced. An incomplete, corrupt or non-JPEG response leaves an existing image
unchanged and produces a failed report. Always check that new report's `ok`.

`snapshot_seconds` measures the capture request through the finished local
JPEG; its 30-second flag is a timing result, separate from visual content and
overall release acceptance. `jpeg_dimensions` records the native dimensions.
New reports also include `probe_seconds`, covering USB checks, discovery,
connection, authentication, the requested operation and teardown; do not confuse
that whole-diagnostic duration with capture latency after authentication.
The initial verified native JPEG is `dist/ble-native-jpeg-candidate.jpg`; its
protocol report is `dist/ble-native-jpeg-layer-eight.json`.

For the stationary same-session Python recovery control, add
`--python-recovery-check`. It reads battery/stopped state before and after the
native capture while retaining both notification subscriptions, and does not
call Python preview methods or operate motors/kicker. This is a separate
diagnostic that does touch the console; regular `--native-camera` does not.

## Camera requirement

This workshop's proposed Bluetooth feature requires a fresh, whole-camera-scene
image transferred entirely over BLE, with the robot USB cable disconnected and
no computer-to-robot Wi-Fi connection. Scope is one snapshot at a time, saved
locally as JPEG within 30 seconds of the capture request after authentication.
Lower resolution and raw pixels converted to JPEG on the computer are acceptable.
A verified camera-preview capture can qualify only if it preserves the full
camera field of view. LCD menus and AI object-detection metadata do not qualify.

VEX documents `get_camera_image()` as an additional method of its
[Wi-Fi WebSocket API](https://api.vex.com/aim/home/websocket/websocket_api/api_differences.html).
Its [AI Vision Utility setup](https://api.vex.com/aim/home/vexcode_tutorials/configuring-color-signatures.html)
requires a wired connection. This does not establish that native BLE images are
impossible; it does mean they cannot be promised from those interfaces.

Do not invent camera commands for unidentified GATT services, change firmware,
upload stored programs, or replace this requirement with Wi-Fi or a USB webcam.
If firmware cannot provide BLE images, record the evidence and stop feature
completion and release. A discovery/capability report is not a passed camera test.

## Verified camera imagery with manual AI Vision mode

After the initial spike, the student selected AI Vision mode on AIM6518's own
touchscreen and pointed its camera at the VEX controller. The new `--lcd-only`
probe authenticated using the saved credential and captured the default LCD
buffer **without entering Python or sending show/hide-preview commands**.
Windows PnP confirmed no AIM USB connection. The complete 115,200-byte buffer
arrived in 29.781 seconds including capture setup (29.547 seconds for the bulk
read), with CRC, address and length validation. The BLE connection remained live.

The locally decoded 240x240 RGB565 image visibly shows the white VEX controller
on a wooden table, with blue screen borders and the circular back-button overlay.
This verifies a camera-pixel acquisition path using the existing firmware and
Bluetooth transport. **The missing pixel source is no longer an absolute blocker
for this manual workflow.** It does not verify automatic selection of that LCD
mode, an unobstructed full camera field of view, repeated freshness, Python
recovery while preserving the manual mode, or the 30-second end-to-end JPEG
target; this capture's timing ended at raw-buffer receipt, before JPEG encoding.

Local evidence: `dist/ble-ai-vision-manual.json`,
`dist/ble-ai-vision-manual.rgb565` and `dist/ble-ai-vision-manual.jpg`.
The image was inspected locally for the requested controller; no publication or
external sharing was performed.

To reproduce, keep USB disconnected, select AI Vision on the robot's touchscreen,
verify that its LCD shows the camera, and leave it in that mode:

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --lcd-only --framebuffer-output dist/ble-ai-vision.rgb565 --report dist/ble-ai-vision.json
powershell -NoProfile -ExecutionPolicy Bypass -File dev/convert-rgb565.ps1 -InputPath dist/ble-ai-vision.rgb565 -OutputPath dist/ble-ai-vision.jpg
```

This mode requires an existing accepted credential. Pair first if necessary,
then select AI Vision again before capturing; do not request a pairing-code
screen during capture. It uses only known system-version, screen-capture and
read-only framebuffer commands, with no Python/user-channel writes. Do not use
the older `--framebuffer-output` mode alone for this experiment: that mode enters
REPL and requests/hides a Python preview instead of preserving the selected GUI.

The remote-navigation test below subsequently established Bluetooth selection of
the same display mode. Remaining camera work includes an unobstructed full-scene
buffer, fresh repeated captures and end-to-end latency. Keep student-facing
Bluetooth release acceptance separate from these individual proofs.

### AIM-specific remote LCD navigation

The old V5 `SYS_DASH_TOUCH` command (`0x2A`, six-byte coordinate/press payload)
was rejected by this AIM with a valid-CRC `2a ff` response for both press and
release. A fresh screenshot remained on the Dashboard tile. Do not keep retrying
that command or assume the V5 dashboard screen IDs apply to AIM.

The official VEX host tool contains a separate AIM navigation interface:
`vexcom --aim touch,center|back|left|right`. Its `_aim_command_touch` and
`_aim_TouchCommand` implementations send `AIM_TOUCH` extended command `0x65`
with a one-byte symbolic action, expecting an eight-byte CDC acknowledgement:

| Action | Payload byte |
| --- | --- |
| center | `0x51` |
| back | `0x52` |
| left | `0x53` |
| right | `0x54` |

Protocol provenance: official [VEXcom 1.0.2b2 host-tool archive](https://content.vexrobotics.com/vexos/public/vscode/vexcom/vexcom_1_0_2_2.zip),
referenced by the [VEX Robotics extension](https://marketplace.visualstudio.com/items?itemName=VEXRobotics.vexcode).
The inspected Windows executable SHA-256 is
`cc15efc812e19a08ca5f2f864305720c8fa513b390e9004f8b806b6f40e4d40e`.
The package was inspected offline; only its help was executed. It was not
installed, connected to the robot, or used to update firmware. The public AIM
Python SDK was inspected as reference material only. These are investigation
tools, not new student dependencies.

The instructor probe's `--lcd-only --lcd-nav center|back|left|right` sends exactly
one named action and captures the resulting screen, with no Python execution.
It checks the reply CRC, command and ACK and never automatically repeats an
action after a timeout/NACK. Before selecting `center`, inspect a fresh LCD
capture and confirm the current menu is safe for stationary navigation. Dashboard
also contains drivetrain/kicker tests; do not select those as part of camera
navigation. Source-format and failure-handling tests pass. `center` and `right`
also passed the live test below. Later automatic-navigation work verified `back`;
`left` still has source/unit coverage only.

### Live Bluetooth selection of AI Vision: verified

After the student confirmed AIM6518 was back on with USB unplugged, the agent
captured and inspected the LCD before every navigation action. It started on
the Drive tile and reached the camera through the following sequence, entirely
over BLE, using the saved OS-vault credential:

| Action | Visually verified resulting screen | Local evidence stem in `dist/` | Raw capture including setup/navigation |
| --- | --- | --- | --- |
| Capture only | Drive tile | `ble-nav-start` | 26.375 s |
| right | Projects tile | `ble-nav-home-right` | 25.766 s |
| right | Dashboard tile | `ble-nav-dashboard-tile` | 26.094 s |
| center | Dashboard's Drivetrain tile | `ble-nav-dashboard-open` | 25.781 s |
| right | AI Vision tile | `ble-nav-ai-tile` | 25.078 s |
| center | Live camera view showing the VEX controller | `ble-nav-ai-camera` | 30.047 s |

Each stem has a JSON report, raw RGB565 framebuffer and locally decoded JPEG.
Every navigation action received a valid-CRC `65 76` acknowledgement; each
115,200-byte framebuffer passed CRC/address/length checks. Windows PnP confirmed
USB absence for every process. No Python console, firmware update, stored-program
upload, motor command, kicker command, Drive selection or drivetrain-test
selection was used. The final display was left in AI Vision mode.

The last image clearly shows the white VEX controller on a wooden surface, with
LCD borders and the back-button overlay. **Bluetooth mode selection and camera
pixel retrieval are now demonstrated on this Windows/firmware combination.**
The final raw capture already exceeded 30 seconds by 0.047 s before JPEG encoding;
it does not pass the end-to-end latency target. Clean full-field-of-view capture,
mixed Python/camera recovery, changing-scene reliability and other-platform
hardware acceptance remain outstanding.

For a single action, once a fresh capture confirms that AI Vision is the selected
tile, the instructor command is:

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --lcd-only --lcd-nav center --framebuffer-output dist/ble-camera.rgb565 --report dist/ble-camera.json
powershell -NoProfile -ExecutionPolicy Bypass -File dev/convert-rgb565.ps1 -InputPath dist/ble-camera.rgb565 -OutputPath dist/ble-camera.jpg
```

Do not blindly replay the full action sequence from an unknown screen: `center`
can select a different behavior. Inspect the screen after each action and stop
on an unexpected menu, NACK or timeout. Subsequent camera captures from an already
active AI Vision screen omit `--lcd-nav` entirely.

### Automatic navigation after students use the menus

The clean-boot sequence `right, right, center, right, center` is useful for
manual orientation, but remembered carousel positions make it unsuitable for
automation. The instructor probe now has a selector that observes the menu
instead of counting presses:

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --lcd-only --select-ai-vision --framebuffer-output dist/ble-auto-ai-vision.rgb565 --report dist/ble-auto-ai-vision.json
powershell -NoProfile -ExecutionPolicy Bypass -File dev/convert-rgb565.ps1 -InputPath dist/ble-auto-ai-vision.rgb565 -OutputPath dist/ble-auto-ai-vision.jpg
```

Keep USB disconnected, VEXcode closed, and the robot stationary. Leave its screen
alone while the selector runs. Pair separately first if no accepted OS-vault
credential exists. Check the new JSON report has `ok: true` and
`ai_vision_selection.complete: true` before decoding its output; an old image
left by an earlier successful command is not evidence that a failed run worked.

This helper is calibrated for **English menus, AIM REV1, BLE firmware
`1.0.0.b0`**. It reads the official host tool's CDC `SYS_STATUS` (`0x20`) reply,
validates its CRC/layout, and uses the observed IDs `0` for home, `32` for
the Dashboard carousel and `34` for the camera view. **ID `32` does not mean the
camera is active.** A fresh capture at ID `34` visibly showed the VEX controller;
an earlier status-only shortcut using `32` was rejected by visual review and removed.
The helper compares fingerprints of the menu icons at rows 88–103, columns 80–159,
against our verified Dashboard and AI Vision captures. Only two icon fingerprints
are stored in source; no camera photo or cloud OCR service is required.

If the camera is already active (ID `34`), the helper sends no navigation input.
Otherwise it uses at most four Back actions to return to the home page,
searches for Dashboard with Right, and presses
Center only after **two fresh captures** identify Dashboard or AI Vision. It
observes the retained Dashboard selection after entering it. After selecting AI
Vision, it requires the camera-page status, then downloads the full
LCD frame for visual inspection. Screen status alone never marks camera pixels
verified. If entering Dashboard restores the camera directly, it also avoids
extra presses. For a known active camera, omitting `--select-ai-vision` also works.
Unknown firmware is rejected before navigation;
unknown icons cannot authorize Center. CRC failures, timeouts, NACKs and changed
confirmation images stop the run without automatically retrying a press.
Searches have fixed tile/depth limits and a five-minute selection deadline;
the entire automatic probe has a six-minute deadline.

**Transfer remains slow.** This AIM returned a valid-CRC read error (`-41` in
the address field) for a direct seek to the label rows, both with and without
the initial offset-zero read. The helper now consumes the screen file
sequentially up to the icon band, discarding earlier rows. Reading the upper icon
band instead of the lower text label roughly halves the bytes needed per check
(49,920 versus 92,160). A separate two-request
pipeline test stopped after 560 bytes with a missing reply. Keep
`--read-pipeline 1`; the automatic menu reader always uses sequential reads.
These observations concern this firmware/transport combination, not a proven
restriction on every AIM or future firmware.

There is **no verified non-destructive Bluetooth reboot command** in this
investigation. VEX documents [the physical reset button](https://kb.vex.com/hc/en-us/articles/37036387138452-Resetting-VEX-AIM)
as forcing power off, requiring a person to turn the robot on again. Its separate
[Factory Reset](https://kb.vex.com/hc/en-us/articles/34912980568084-Settings-Menu-on-VEX-AIM)
erases projects and resets settings. Neither is an appropriate automatic menu
shortcut. The inspected host tool has factory-reset/power-off routines and an
AIM `screen` command (`0x66`), but no proven ordinary AIM reboot operation;
the screen command's mode/argument meanings remain unestablished. No reset,
power-off, guessed screen command or firmware operation was sent.

This is an instructor development helper, not a new flag for the published
USB-only `vexaim` executable. It does not complete camera quality/latency,
actuator, sensor or Bluetooth release acceptance.

**Live result, AIM6518 on Windows 11:** starting with the camera open, the
full-route test used `back, back, center, center`: the first two actions returned
to home; Dashboard then restored the remembered AI Vision tile. Both target
icons matched twice before Center. Selection took **45.563 s**; selection plus
the complete raw LCD download took **75.047 s**, before JPEG conversion. The
new image visibly showed the VEX controller. USB was absent; all navigation
ACKs and framebuffer CRC/address/length checks passed. No Python, reset,
stored-program upload, motor or kicker commands were sent.

Local evidence: `dist/ble-auto-ai-vision-final.json`, `.rgb565` and `.jpg`.
An immediate reconnect with the same command recognized the already active
camera in **0.062 s**, sent **no navigation actions**, and captured another
verified controller image in **29.468 s** before JPEG conversion. Evidence:
`dist/ble-auto-ai-vision-repeat.*`. The robot was left in AI Vision mode.
`dist/ble-camera-screen-id.*` independently associates ID `34` with camera
imagery. The rejected status-only attempt remains in `dist/ble-auto-ai-vision.*`
with its failed visual review; it must not be counted as a camera success.
The original forty local protocol/automation tests passed, including the Dashboard-versus-camera
regression and remembered positions different from the live test. Only this
robot/Windows/firmware combination has live calibration; other menu histories,
languages and operating systems still need hardware acceptance.

### One-command JPEG capture and timing diagnostics

The Windows instructor probe can now write a JPEG in the same invocation:

```powershell
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --lcd-only --select-ai-vision --framebuffer-output dist/ble-snapshot.rgb565 --jpeg-output dist/ble-snapshot.jpg --report dist/ble-snapshot.json
```

The raw frame, JPEG and report must use different paths. `--jpeg-output` is
restricted to the known default 240x240 RGB565 LCD capture on Windows. It invokes
the existing local PowerShell/System.Drawing decoder with literal path arguments,
validates the result and replaces the destination only after successful encoding.
On failure or cancellation the staging directory is removed; raw bytes and an
existing destination image are retained. Check the **new report**, not an old
image left at the requested path. No photo or credential is uploaded.

`snapshot_seconds` measures wall time from the screen-capture request through
the completed JPEG, including notification teardown and conversion. It excludes
discovery, authentication and initial menu navigation. `capture_seconds` retains
its earlier meaning: the entire raw-capture workflow, including any navigation.
`jpeg_encoding_seconds` measures local conversion, and
`snapshot_within_30_seconds` compares unrounded elapsed time with the target.
This flag says nothing about camera content or full field of view; image review
and the other acceptance checks are still required.

Reports also record actual Windows connection intervals before and after the
operation, plus aggregate stop-and-wait read timings. Microsoft documents that a
[successful throughput request](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.bluetoothlepreferredconnectionparametersrequeststatus)
means Windows accepted it; parameter negotiation is a separate event.
[ConnectionInterval](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.bluetoothleconnectionparameters.connectioninterval)
is reported in 1.25 ms units. The probe records measured intervals rather than
assuming the request changed them. The sequential reader no longer adds a fixed
5 ms sleep after every request; it still awaits and validates each reply before
issuing the next request. This does not enable the failed pipeline.

For a narrowly scoped repeat of the **previously tested layer 1**, use
`--lcd-only --capture-layer 1 --framebuffer-output PATH --report PATH`, optionally
with `--select-ai-vision`. This mode requires the calibrated firmware and camera
screen `34` before sending the layer request, and never enters Python. It rejects
empty buffers before reading data. Other layer values are rejected in LCD-only
mode except the source-defined layer-8 support check below. JPEG output
is deliberately unavailable for alternate layers in this control.
The official host tool's separate-camera layer handling does not establish AIM
layer formats or meanings.

The later source review identified one specific additional capability check:
`--lcd-only --capture-layer 8`. Official VEXcom's `_v5_ScreenCaptureLayer` treats
layer 8 as compressed JPEG **for the separate AI Vision camera product**; it does
not document AIM support. The instructor control therefore requires AIM's camera
screen, inspects the first CRC-checked block, and stops immediately if it does
not start with JPEG's SOI marker. A complete payload must also have the EOI marker
before it is saved. It does not try other layer values or guess a pixel format.
This single source-based check succeeded on AIM6518: it returned a complete
640x480 JPEG without LCD UI in 3.453 s. That hardware result establishes this
path on the tested firmware, although it is not a documented public AIM API.

The operational bulk-transfer deadline is now **45 seconds**, with a 60-second
LCD-only operation budget. The camera performance target remains **30 seconds
to a finished JPEG**. A frame that finishes between 30 and 45 seconds is retained
and reported as missing the timing target; it is not discarded simply for being
slow. The first fresh-boot run reached the camera correctly in 82.187 s but hit
the old 30-second transfer cutoff with 1,024 bytes left. This exposed the need to
separate the operational deadline from the performance criterion.

## Initial camera investigation spike: result and evidence

**Initial result: unresolved camera access; superseded by the manual-mode proof above.** The spike implemented
and exercised bounded instructor diagnostics on Windows 11, AIM6518 / REV1 /
BLE Device Information firmware `1.0.0.b0`, Bleak 3.0.2. No genuine camera image
was obtained, so changing-scene and full-field-of-view acceptance were not run.
This is not evidence that a firmware change is necessarily required.

| Experiment | Observed result | Local evidence in ignored `dist/` |
| --- | --- | --- |
| Cable-free baseline | Stored credential authenticated; battery 87%, stopped true | `ble-spike-baseline.json` |
| Live Python preview during default framebuffer capture | Python signalled readiness and remained active through transfer; 115,200 bytes in 25.844 s including preview startup. Student confirmed LCD contents, no camera scene, robot still on | `ble-spike-live-1.json`, `.rgb565`, `.jpg` |
| Preview-only control; no system/file traffic | 20-second preview request, clean interrupt/hide and subsequent state read; student saw the usual LCD throughout | `ble-spike-preview-control.json` |
| Native API inspection | No `socket`, `network`, `camera`, or `framebuf` modules. `aim` had no image acquisition members or source-file path. `screen.layer` was an undocumented bound method | `ble-spike-system-retained.json` |
| System notification unsubscribe control | Python state reads passed before subscription, during subscription and after a system-version query, then timed out immediately after disabling TXData notifications | `ble-spike-system-control.json` |
| Re-register TXUser after disabling TXData | Registration succeeded but the next Python response still timed out | `ble-spike-system-restored.json` |
| Retain both subscriptions until all Python work ends | System-version control and subsequent Python reads passed | `ble-spike-system-retained.json` |
| Full capture with retained subscriptions | Complete framebuffer in 25.656 s, Python still active, preview cleanup and same-connection battery/state read passed (81%, stopped true). Student again confirmed LCD contents | `ble-spike-live-retained.json`, `.rgb565`, `.jpg` |

**Confirmed recovery strategy:** retain TXData and TXUser notifications through
all Python work, including preview cleanup. Disable them only at connection
teardown. On this Windows/Bleak/firmware combination, disabling TXData mid-session
silenced the Python response path; re-registering TXUser alone did not repair it.
The controls do not identify whether Windows, Bleak or robot firmware causes that
interaction. The Rust backend already retains its subscriptions through the
connection lifetime; the instructor probe now does too. A missed Python response
does not imply that the robot switched off.

The preview-lifetime hypothesis was tested explicitly: the Python preview
program was still active at capture completion, yet the LCD and downloaded image
did not show the camera. Returning from the short Python command is therefore
insufficient to explain the original result. An additional program/display mode
requirement remains possible, not demonstrated.

Source review established the following boundaries:

- The official [WebSocket client](https://github.com/VEX-Robotics/AIM_Websocket_Library/blob/main/vex/aim.py)
  uses a separate `ws_img` connection, binary byte `1` to start, and binary image
  messages. It supplies no BLE image command. Without native socket/network
  modules, the tested Python environment cannot use that client as an internal
  loopback bridge. No Wi-Fi connection or network configuration was attempted.
- The vendored CDC AI Vision definitions cover sensor configuration, status and
  detected-object data; no camera-frame reader was identified. The default CDC
  `screen` buffer is retrievable but contains LCD pixels in these tests.
- VEX documents [a live camera display](https://api.vex.com/aim/home/python/AI_Vision.html#show-aivision),
  but neither experiment visibly produced it. The meanings of additional capture
  layers, `screen.layer` arguments and `vision.debug_get` arguments were not
  established. No argument sweeps, guessed GATT commands or raw-memory operations
  were performed. Earlier no-argument `debug_get` failure was not repeated.
- Direct retrieval of the official VEXcode web application returned HTTP 403.
  Its client implementation and capture traffic were therefore not inspected;
  no access-control workaround or VEXcode installation was attempted.

**Initial recommendation:** keep the student CLI USB-only and establish a pixel
source before optimizing transfer. The subsequent manual-mode and remote-navigation
tests established a source and Bluetooth mode selection; remaining work is
capture quality, latency and reliability. Validate three
changing full-scene captures within 30 seconds each, including one after a fresh
BLE connection, and require Python state reads after every capture. Full feature
acceptance below remains separate.

Draft questions for VEX (not sent):

1. On AIM firmware reporting `1.0.0.b0` through BLE, is there a supported CDC,
   GATT or on-robot MicroPython operation to read a clean AI Vision pixel frame,
   without the LCD's back-button overlay? The default LCD buffer works when
   AI Vision is selected manually, but automatic preview calls did not reproduce it.
   Please provide command/argument definitions, format, dimensions and any
   required camera/program mode. Raw pixels are sufficient; video is unnecessary.
2. Does `robot.screen.show_aivision()` require a VEXcode program-running/display
   mode beyond an executing raw-REPL program? Which screen-capture buffer/layer,
   if any, includes the full camera feed?
3. Are `vision.debug_get` or `screen.layer` intended for image access? If so,
   what are their supported signatures and meanings on this firmware?
4. Is the observed loss of TXUser responses after disabling TXData notifications
   expected, and should both CCCD subscriptions remain enabled until disconnect?

The investigation stopped after these established paths were exhausted, within
the four-hour engineering / 45-minute supervised-hardware ceiling. No newer
firmware was installed and no firmware limitation was declared proven.

## Instructor-only stationary feasibility probe

`dev/ble-feasibility.py` is a development diagnostic, not part of the student
installation. It uses temporary Python dependencies through `uv`; students do not
need these for the released USB tool. The probe:

1. Refuses to proceed on Windows while an AIM USB endpoint is present.
2. Requires exactly one discovered robot with the specified name and verifies
   that Device Information identifies it as an AIM.
3. Requests the four-digit code on the robot screen. Enter it in the local masked
   prompt, never in agent chat or a command argument. The protocol uses four
   numeric digit bytes, as in the upstream Bluetooth example.
4. Saves an accepted code in the OS credential store under service
   `vexaim.bluetooth`, scoped to the host's device identifier. An unavailable
   credential store is an error; no plaintext file fallback is used.
5. Subscribes to TXUser, tests the MicroPython raw-REPL handshake and, if it
   succeeds, reads stationary battery/state and Python vision capabilities.
6. Disconnects and writes a local report containing no code or raw authentication
   response. The default mode does not drive, kick, capture images, or upload a
   program. Optional framebuffer modes below retrieve LCD contents only.

For a local Windows pairing window, from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File dev/pair-bluetooth.ps1 -Name AIM6518
```

The window explicitly waits for acknowledgement before beginning. Unplug the
robot USB cable, leave it powered on nearby, then press Enter. Enter the code
displayed on the robot only when prompted. Pairing is different from Windows
Settings reporting a bonded device; verify the VEX authentication and REPL checks
independently. VEX's [wireless connection instructions](https://api.vex.com/aim/home/vexcode_tutorials/wireless-connect-web.html)
describe the displayed code and connected Bluetooth icon.

The equivalent development command, also usable from a local Linux/macOS terminal:

```sh
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --pair --report dist/ble-feasibility.json
```

On Linux/macOS, confirm physical USB disconnection yourself; the probe's automatic
USB endpoint check currently covers Windows only. Linux requires a working BlueZ
service, D-Bus access and an unlocked Secret Service credential store. macOS may
require Bluetooth permission for the hosting terminal/agent. Do not grant new
administrator permissions or change Bluetooth configuration automatically.

Omit `--pair` to test reconnection using an existing vault credential. Reports
stay in the ignored `dist/` directory. Review them before sharing. Camera images
and the local Showtail trail must remain local.

Add `--camera-check` to inspect the native Python vision API and test the existing
CDC screen-capture acknowledgement after authentication. This does not retrieve
an image and cannot pass the camera gate. The probe consumes the trailing raw-REPL
prompt before issuing another command; otherwise a delayed prompt notification
can corrupt the next response. Its protocol/credential-input regressions run with:

```sh
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python -m unittest discover -s dev -p test_ble_feasibility.py -v
```

For reproducing the unsuccessful camera investigation, `--framebuffer-check`
requests the camera preview and reads only LCD-buffer metadata plus the first
128 bytes. `--framebuffer-output dist/lcd.rgb565` instead reads the complete LCD
buffer with length, CRC and address checks and a 45-second operational deadline;
the snapshot performance target remains 30 seconds.
These modes temporarily request a screen change and try to hide the preview
afterward; check `preview_hidden`/`preview_cleanup_error` in the report. They are
not student camera commands. `--capture-layer 1` reproduced the empty-layer
result. Default sequential reads match the complete hardware transfer;
`--read-pipeline 2` failed a later live control with a missing reply after 560
bytes. Values `3` and `4` still have only simulated coverage. Use the default
sequential reader; automatic menu selection rejects other values.
Windows bulk captures request a temporary
[throughput-optimized connection](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.bluetoothledevice.requestpreferredconnectionparameters)
and dispose the connection on exit; this does not update firmware or permanent
Bluetooth settings. LCD screenshots can contain whatever is displayed; keep
them local and review before sharing. A report's `ok` means its diagnostic queries
finished, not that the camera or full feature passed acceptance.

### Reproduce the spike controls

Keep AIM6518 on, stationary and disconnected from USB. Obtain a separate readiness
acknowledgement for every physical reconnect; do not automate power cycles.
Run each experiment in a separate process. All use the existing OS vault entry;
if authentication needs a new code, use the masked local pairing procedure above.

```powershell
# Module availability only; no network connection or unknown API invocation.
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --native-image-check --report dist/ble-native.json

# Twenty-second preview-only control, then hide and read battery/state.
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --preview-only --report dist/ble-preview-control.json

# System-version control retaining both notification channels until teardown.
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --system-channel-check --report dist/ble-system-control.json

# Capture during a running preview program; still an LCD diagnostic, not a camera command.
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name AIM6518 --live-preview --framebuffer-output dist/ble-live.rgb565 --report dist/ble-live.json
powershell -NoProfile -ExecutionPolicy Bypass -File dev/convert-rgb565.ps1 -InputPath dist/ble-live.rgb565 -OutputPath dist/ble-live.jpg
```

The converter is Windows-only and validates exact dimensions before decoding the
known 240x240 RGB565 LCD layout. Do not apply that layout to unknown camera data.
The preview program has a 60-second upper bound; the capture operation is bounded
to 40 seconds and cleanup to 15 seconds. The overall diagnostic has a
150-second deadline (including discovery). Reports separate actual capture latency from cleanup and
include `console_recovered`; a failed live-preview recovery makes `ok` false.
`ok: true` still does not establish a genuine camera image. The controls do not
repeat the disruptive unsubscribe experiment automatically. If power disappears,
stop and get a fresh readiness acknowledgement before another attempt.

## Acceptance after the feasibility gate

Only after genuine whole-scene BLE snapshots meet the camera requirement, expose the planned public
transport/pairing commands and run these supervised tests without robot USB:

- Correct/incorrect code, vault reuse, 100 stationary Python round trips, Python
  error/timeout recovery, and three independently acknowledged reconnect cycles.
- Battery, timer, IMU baseline and human tilt/rotation, touchscreen press and
  coordinates, wheel odometry, and real AI Vision targets: ball, both barrel
  colors, and supplied AprilTags, plus an empty scene.
- Every wheel motor through bounded low-speed translation and turning; stopped
  state and position changes; interruption and disconnect behavior.
- Physically confirmed LEDs, screen/emoji, sound/stop, soft kick, place and push.
- Ten complete, fresh, locally saved JPEGs of changing scenes, each within 30 s.

Tell the student exactly what will happen, wait for readiness before each physical
step, and never advance a reconnect cycle without its own acknowledgement.
Use finite moves on a clear floor with a person at the power switch. A stop
command requires a working link; a disconnected command may already have run.
Record the observed physical result, not just a successful API return.

Build/test coverage must include Linux x86_64, Windows x86_64, macOS arm64 and
macOS x86_64, with isolated USB, isolated Bluetooth and combined features. Linux
Bluetooth builds need `libdbus-1-dev` and `pkg-config`. Preserve the Windows DTR
and installer regressions. CI success does not establish hardware functionality
on another OS; record those results separately before preparing version 0.2.0.

The actual Rust discovery backend was also exercised on Windows: the following
stationary command discovered AIM6518 once and returned after its eight-second
scan. It performs no pairing or characteristic writes:

```sh
cargo run --locked --manifest-path cli/Cargo.toml -p vex-v5-serial --example ble-discover --no-default-features --features bluetooth
```
