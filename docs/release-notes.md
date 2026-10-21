VEX AIM device commands and agent camera observations — prerelease.

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
- Preserved installers, native credentials, Windows process ownership and original
  command forms. Close old sessions with their matching binary before updating
  because this candidate uses session protocol 2.

This is a hardware-validation candidate. New runtime commands have simulated
tests; API presence is firmware-dependent. Independent wheel units/signs remain
experimental. Custom asset uploads are disabled until firmware storage encoding
is verified; the official uploader remains supported. macOS hardware, two-robot
link acceptance and broader motion accuracy are not certified by CI.

All four bundles contain a matching binary and generic skill. Stable one-line
installers keep selecting the latest stable release. Select this prerelease
explicitly with `--version 0.3.0-rc.3` / `-Version 0.3.0-rc.3` or its extracted
bundle. Start a new agent session after installation. Keep images local and
supervise movement. No robot firmware or saved project changes are required.
