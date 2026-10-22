# vexaim 0.3.0

This stable release makes agent-assisted Bluetooth pairing available through the
normal installers. It replaces stable 0.2.1, which did not include
`bluetooth pair --code-stdin`.

## Pairing for the workshop

Agents can start pairing, ask the student for the four-digit code displayed on
AIM and pass it through standard input. The option is **`--code-stdin`**, with two
leading hyphens. Without it, pairing still uses the masked local prompt.
Codes are never supplied as command arguments; saved credentials use the native
OS vault. The workshop skill explains its deliberate chat-code trade-off.

Rerun the workshop's one-line installer to get the current CLI and both skills:
[workshop installation](https://github.com/Tingsters/vex-aim-agent-workshop#start-here).
The default installers now select this stable release; no prerelease selection,
Rust compiler, VEXcode or saved robot project is required.

## Included changes

- VEX-style device catalogue, native holonomic movement and strafing, finite
  actions, sensors, AI Vision, cargo, kicker, LEDs, screen, sound and events.
- `camera observe` returns a validated photograph and absolute local artifact
  path for the agent's image reader. No additional image API account is needed.
- Bluetooth emoji/drawing display ownership and independent native camera capture.
- Windows and Mac fixes for raw-console parsing, refreshed imports and
  interpreter changes during AIM 1.0.4 display/power transitions.
- Mac raw camera-frame conversion when a camera driver ignores MJPEG.
- Cargo collection verifies the requested class, so a held blue barrel cannot
  be reported as an orange barrel or sports ball.
- Matched generic skill, checksum-verified installers and prebuilt bundles for
  Windows x86_64, Linux x86_64, Apple Silicon Mac and Intel Mac.

## Compatibility and measured limits

Close an existing session using its matching old binary before updating.
This release uses session protocol 2; old and new process owners are not shared.
Start a new agent session after installation so it discovers the matching skill.

The firmware-gated AIM 1.0.4 power lease remains experimental. An earlier Windows
candidate passed a clean-boot 20-minute run, but the newly integrated build has
not completed its own hardware acceptance. System Alive acknowledgments alone
do not prove sleep prevention. See the
[hardware notes](https://github.com/Tingsters/vexaim-cli/blob/v0.3.0/docs/hardware-notes.md)
for the exact tested versions and remaining gates. This release does not certify
physical accuracy on every floor or hardware parity across operating systems.

Custom PNG/MP3 uploads remain disabled where firmware storage encoding is
unverified. Existing supported image/sound slots and generated LCD drawing
primitives are independent capabilities. Individual wheel commands remain
experimental; prefer native drivetrain operations.

All four platform builds run CI tests and installer/package checks before the
complete release is published. Images, credentials, device logs and developer
probes are not release assets. No firmware or saved-program update is performed.
