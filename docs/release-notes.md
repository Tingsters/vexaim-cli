vexaim 0.3.0-rc.6 — experimental cross-platform verification prerelease.

Prebuilt Apple Silicon Mac, Intel Mac, Windows x86_64 and Linux x86_64 bundles
include the matching agent skill. macOS robot verification is still pending;
follow the [Mac checklist](https://github.com/Tingsters/vexaim-cli/blob/v0.3.0-rc.6/docs/macos-verification.md).
**Sleep prevention remains unresolved.** This is an investigation release,
not a verified sleep fix. Unversioned installers still select the stable release.

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/Tingsters/vexaim-cli/v0.3.0-rc.6/install.sh | sh -s -- --version 0.3.0-rc.6
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Tingsters/vexaim-cli/v0.3.0-rc.6/install.ps1))) -Version 0.3.0-rc.6
```

- 0.3.0-rc.6 investigates session liveness separately from display
  ownership. Hardware acceptance failed: 92 acknowledged System Alive polls
  did not prevent the observed shutdown. Do not publish as a sleep fix.
  The candidate sends the
  existing System Alive request every two seconds and validates its reply through
  the single Bluetooth owner, including while idle and during camera transfers.
  No LCD activation, motor movement, saved project or student setup is needed.
  Stop/display expiry preserve liveness; close and the unchanged 30-minute client
  idle deadline end it. Failures require live recovery and never replay actions.
  A stationary endurance harness and simulated recovery/deadline regressions are
  included. See hardware notes for measured Windows coverage.

- Shared VEX-style catalogue and argument validation across USB and Bluetooth.
- USB sessions, holonomic strafing/vector operations, bounded asynchronous actions,
  sensors, AI Vision, cargo, LEDs, kicker, screen, sound, One Stick, link and timer.
- Bounded events/sampling and adaptations of the 20 official toolbox macros.
- `camera observe`: fresh validated native JPEG, immutable absolute artifact path,
  checksum, timing/state metadata and separate postcapture control readiness.
- Matching Codex/Claude instructions open the actual image within an agent turn;
  no additional paid image API account, SDK or key is needed.
- Explicit Python input answers and standalone VEX Python emission.
- Separate LCD PNG screenshot, bounded JSON Lines samples and timer events.
- Hardware fixes: AIM MicroPython-compatible vision dispatch; paced large JSON
  reports with a 16 KiB limit and separate delivery allowance; wait for a closing
  session to release its endpoint before starting another owner.
- Resolve firmware emoji aliases and refresh Python API imports when a robot
  already exists. Acceptance checks clean up effects after failures and separate
  unsupported firmware from failed checks.
- 0.3.0-rc.5 fixes hidden Bluetooth screen output: activate the AIM program display,
  verify its screen ID and maintain its status keepalive through the existing
  connection owner. HAPPY, text and shapes were physically confirmed on Windows
  with AIM REV1 / BLE 1.0.0.b0, including takeover from AI Vision. No stored project
  or USB cable is required. Stop/close and a 60-second idle lease release the
  display; manual menu exit can be recovered by a fresh drawing request.
- Preserve native camera capture during display use. Fixed read-only keepalive
  polling avoids repeated pairing reads; LCD transfers have a separate 55-second
  budget. Unknown firmware is rejected clearly. Use named emojis and contrasting
  text/fill colors. Detailed protocol provenance and a bounded developer probe
  are included; students need no new packages or setup.
- Preserved installers, native credentials, Windows process ownership and original
  command forms. Close old sessions with their matching binary before updating
  because this candidate uses session protocol 2.

This is a hardware-validation candidate. New runtime commands have simulated
tests; API presence is firmware-dependent. Independent wheel units/signs remain
experimental. Custom asset uploads are disabled until firmware storage encoding
is verified; the official uploader remains supported. macOS hardware, two-robot
link acceptance and broader motion accuracy are not certified by CI.

All four bundles contain a matching binary and generic skill. Developer probes
remain source-only investigation tools, not student dependencies or verified
workarounds. Start a new agent session after installation. Keep images local and
supervise movement. No robot firmware or saved project changes are required.
