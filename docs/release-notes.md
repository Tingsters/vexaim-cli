Standalone vexaim CLI with a matching general-purpose vex-aim agent skill.

- USB and Bluetooth Python console access, native camera snapshots and reusable wireless sessions.
- Finite turn/move helpers, private local IPC, explicit stop and recovery without automatic movement replay.
- Complete Windows x86_64, Linux x86_64, macOS Apple Silicon and macOS Intel bundles.
- Checksummed installers; no Rust or Python packages required for normal use.
- Windows release links its C runtime statically; no Visual C++ redistributable installation is needed.
- Windows session owners do not inherit PowerShell capture pipes; captured startup JSON returns while the owner stays connected.
- Stop confirmation tolerates the firmware's asynchronous stopped flag with a bounded poll and no movement replay.

Download, extract and run install.ps1 (Windows) or install.sh (macOS/Linux), then
start a new agent session. See https://tingsters.github.io/vexaim-cli/.

All four platforms have software/build/installation checks. Existing hardware
evidence covers Windows USB/BLE and Linux USB, including a new Windows small-turn,
stop/session and camera smoke test. macOS hardware, broader physical accuracy and
in-motion interruption remain unverified. Turn default remains
30 DPS. Automatic visual correction is disabled. No robot firmware or saved
project changes are required. Supervise movement and keep camera images local.
