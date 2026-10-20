# vexaim CLI

Control a VEX AIM robot over USB or Bluetooth. Run MicroPython, read sensors,
move, stop, and save native camera photographs. The command is **`vexaim`**.

**[Downloads and installation](https://tingsters.github.io/vexaim-cli/)** ·
[Latest release](https://github.com/Tingsters/vexaim-cli/releases/latest) ·
[Command and agent guidance](skill/vex-aim/SKILL.md)

## Install

Download the Windows x86_64, Linux x86_64, macOS Apple Silicon or macOS Intel
bundle from Releases. Extract it and run its installer:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

```sh
sh install.sh
```

The extracted bundle installs offline. Alternatively download this repository
and run its installer to fetch the latest stable release. Archives are checked
against `SHA256SUMS`; verify a manually downloaded archive before executing files
from it. Normal installation does not require Rust, Python packages or VEXcode.

Each bundle contains a matching executable and general-purpose **`vex-aim`**
agent skill. The default locations are:

- Goose/Codex: `~/.agents/skills/vex-aim/`
- Claude Code: `~/.claude/skills/vex-aim/`

Use `--agents claude` / `-Agents claude` to select an agent, `--dry-run` /
`-DryRun` to preview, or `--from-dir DIR` / `-FromDir DIR` to use local release
archives plus checksums. `--version 0.2.0` / `-Version 0.2.0` selects a release.
No shell profile or agent settings are changed. Rerun the installer to update;
close active robot sessions first. The robot may be off during installation.

Start a **new agent session** so it discovers the skill, then try:

> Use the vex-aim skill. Connect to my VEX AIM over USB, report its battery,
> and set its lights blue for two seconds. Do not move it.

For wireless use, ask for Bluetooth and provide the robot's exact name. The agent
handles pairing and reusable sessions; Bluetooth needs a working adapter and
platform permissions. [Bluetooth guide](docs/bluetooth.md).

## Direct CLI use

The executable can also run directly from the extracted bundle. For installed
copies, invoke its full path under the selected skill's `bin/` directory.

```sh
./vexaim doctor
./vexaim info
./vexaim exec 'print(robot.get_battery_level())'
./vexaim snap -o photo.jpg
./vexaim --name AIM1234 session start
./vexaim --session SESSION_ID info
./vexaim --session SESSION_ID session close
```

On Windows PowerShell use `.\vexaim.exe` instead of `./vexaim`.
No saved robot project or firmware modification is needed. Helpers execute in
the transient REPL. Keep photographs local unless you choose to share them.
For movement, clear the floor and have someone near the power switch.

## Support and development

[Troubleshooting](docs/troubleshooting.md) · [Architecture](docs/how-it-works.md) ·
[Hardware evidence](docs/hardware-notes.md) · [Movement limits](docs/motion.md)

All four platforms are built and installation-tested in CI. Windows USB and BLE
have real-robot evidence, and Linux USB has earlier evidence. macOS hardware and
new session/movement-helper hardware acceptance remain explicitly unverified
until recorded; CI alone is not a robot test. The current conservative turn
default remains 30 DPS, without automatic camera-based correction.

Developers with Rust and platform build prerequisites can use
`cargo build --locked --release --manifest-path cli/Cargo.toml` or explicitly
install with `--from-source` / `-FromSource`. Student installs never fall back
to compilation. Developer Python tools are optional and not runtime dependencies.
Tagging a matching `vX.Y.Z` builds complete bundles and publishes them only when
all shared checks pass. Update `VERSION`, the crate version and lockfile together.

This independent Apache-2.0 project was extracted from
[vex-aim-agent-workshop](https://github.com/Tingsters/vex-aim-agent-workshop),
source commit `bec539dd9a7f9bc934c6443877cff51267ac5698`. Original contributors'
attribution and third-party licenses are retained. See [NOTICE.md](NOTICE.md).
The workshop has its own teaching skill and consumes this project's releases.
