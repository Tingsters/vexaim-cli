# VEX AIM command expansion

Use `vexaim catalog [GROUP]` offline to discover commands and parameters. Native
commands map to AIM Python APIs rather than WebSocket-library defaults. The
shared catalogue in `cli/vexaim/src/catalog.tsv` drives Rust validation and
transient robot dispatch over USB and Bluetooth. No saved robot project,
firmware modification or student Python installation is needed.
[Command guide](../skill/vex-aim/references/device-commands.md).

The candidate adds motion, inertial sensing, AI Vision and cargo, kicker, LEDs,
screen, sound, One Stick, robot links, timer, events and bounded adaptations of
the 20 official toolbox macros. Firmware support varies. Independent wheels
require `--experimental`; asset upload stays disabled until slot mapping and
storage encoding are verified. The user-supplied capability reference has an
explicit [coverage matrix](capability-matrix.json), including host operations and
remote-only exclusions. Implementation coverage is not hardware coverage.

`screen screenshot lcd.png` is a separate 240×240 display PNG with explicit LCD
source labeling. Camera observations remain native 640×480 JPEGs. The source
protocol checks the exact LCD buffer size before RGB565 decoding and never
switches menus or firmware modes to obtain an image.

The 0.3.0-rc.5 candidate fixes hidden Bluetooth display output on AIM REV1 / BLE
1.0.0.b0. Screen writes activate the program display and maintain its required
keepalive through the existing owner. Reuse a session; no stored project or USB
is needed. Stop/close or 60 seconds without traffic ends the drawing. The rc.7
power candidate may then show REPL Mode until session close. Native
camera capture does not activate this display mode. See the
[investigation and protocol evidence](display-investigation.md).

For a visual task, call `--json --session ID camera observe`, then open its
absolute `path` with Codex `view_image` or Claude Code `Read`. Decide on a small
finite action, announce it, wait for completion, then capture and inspect another
image. Each complete native JPEG has decoder validation, an immutable local path,
checksum, host timing, pose metadata and separate control readiness. There is no
extra image API client/account. [Image workflow](../skill/vex-aim/references/agent-vision.md).

Tests cover typed validation, metric units, native signatures, background actions,
resource conflicts, private watchdogs, delayed stop confirmation, empty vision,
buffer pacing, image decoding/atomic persistence, IPC and Windows process
ownership. CI builds four OS targets and USB-only configurations using fake
devices; it cannot certify physical precision or unsupported firmware.

Live Windows BLE testing caught AIM MicroPython rejecting tuple arguments to
`str.endswith`, which desktop Python accepts, and truncating larger reports at
the original print rate. Vision dispatch uses single-string suffixes. Results
now use 128-byte chunks at 100 ms intervals, with no delay for small replies,
a 16 KiB result bound and a separate host allowance for delivery. Robot action
deadlines stay unchanged. See [hardware evidence](hardware-notes.md).

Hardware acceptance requires supervised USB/Bluetooth checks across command
groups, a second prelinked AIM for messages, and independent measurements for
motion across surfaces. Defaults remain 80 mm/s and 30 degrees/s. Students need
no calibration routine. Sparse camera observations inform decisions; they do not
establish real-time servo control or uncalibrated metric geometry.

Asset code restricts transfers to AIM image/sound vendor IDs. Input validation,
explicit replacement, CRC/readback and partial-failure reporting are implemented.
The public upload path is gated for unverified storage encodings; the official
asset uploader remains the supported route for those versions. No run-after-upload,
firmware/user program, erase-all or format command is exposed.
