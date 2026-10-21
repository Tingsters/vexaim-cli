# vexaim CLI

Control a VEX AIM robot over USB or Bluetooth. Run MicroPython, read sensors,
move, stop, and save native camera photographs. The command is **`vexaim`**.

The next command release adds the [VEX AIM device catalogue](docs/device-commands.md)
and [agent image workflow](skill/vex-aim/references/agent-vision.md): strafing and
vector motion, sensors, vision, LEDs, screen, sound and bounded actions. Use a
matching candidate binary/skill to try it. Firmware-gated features report their
limits; stable installers continue to select the latest stable release.

**[Downloads and installation](https://tingsters.github.io/vexaim-cli/)** ·
[Latest release](https://github.com/Tingsters/vexaim-cli/releases/latest) ·
[Command and agent guidance](skill/vex-aim/SKILL.md)

## Install

Paste one command into a terminal. No download, extraction or Git clone is
needed first. The installer selects the right prebuilt binary for your computer.

**Windows x86_64 — PowerShell 5.1 or newer:**

```powershell
irm https://raw.githubusercontent.com/Tingsters/vexaim-cli/main/install.ps1 | iex
```

**macOS — Apple Silicon or Intel (Terminal):**

```sh
curl -fsSL https://raw.githubusercontent.com/Tingsters/vexaim-cli/main/install.sh | sh
```

**Linux x86_64 — terminal:**

```sh
curl -fsSL https://raw.githubusercontent.com/Tingsters/vexaim-cli/main/install.sh | sh
```

These commands download the installer, resolve the latest stable release and
verify its archive against `SHA256SUMS` before installing. No administrator
access, Rust, Python packages or VEXcode is needed for installation. The robot
can be off. Linux USB setup may later need an approved udev rule.

Prefer a manual or offline install? Download your platform's bundle from
[Releases](https://github.com/Tingsters/vexaim-cli/releases/latest), verify it
against `SHA256SUMS`, then extract it. In its folder, run
`powershell -ExecutionPolicy Bypass -File install.ps1` on Windows or
`sh install.sh` on macOS/Linux. The extracted bundle installs offline.

Each bundle contains a matching executable and general-purpose **`vex-aim`**
agent skill. The default locations are:

- Goose/Codex: `~/.agents/skills/vex-aim/`
- Claude Code: `~/.claude/skills/vex-aim/`

Use `--agents claude` / `-Agents claude` to select an agent, `--dry-run` /
`-DryRun` to preview, or `--from-dir DIR` / `-FromDir DIR` to use local release
archives plus checksums. `--version 0.2.1` / `-Version 0.2.1` selects a release.
No shell profile or agent settings are changed. To update, rerun the one-line
command for your computer. An extracted bundle installs its own version offline;
download a fresh bundle when updating offline. Close active sessions first.

To pass options without a checkout, use `curl -fsSL <installer-URL> | sh -s --
--agents claude` on macOS/Linux, or `& ([scriptblock]::Create((irm
<installer-URL>))) -Agents claude` in PowerShell, using the URL for your platform
above. To review the installer first, open that URL or download it without
executing it.

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
have real-robot evidence, including a captured-session startup, a small right
turn, repeated stop confirmation and camera/Python recovery. Linux USB has earlier
evidence. macOS hardware, broader movement accuracy and in-motion interruption
remain unverified; CI alone is not a robot test. The current conservative turn
default remains 30 DPS, without automatic camera-based correction.

Developers with Rust and platform build prerequisites can use
`cargo build --locked --release --manifest-path cli/Cargo.toml` or explicitly
install with `--from-source` / `-FromSource`. Student installs never fall back
to compilation. Developer Python tools are optional and not runtime dependencies.
Tagging a matching `vX.Y.Z` builds complete bundles and publishes them only when
all shared checks pass. Update `VERSION`, the crate version and lockfile together.
Windows releases statically link the C runtime; CI checks the executable's actual
DLL imports so student installs do not need the Visual C++ redistributable.

This independent Apache-2.0 project was extracted from
[vex-aim-agent-workshop](https://github.com/Tingsters/vex-aim-agent-workshop),
source commit `bec539dd9a7f9bc934c6443877cff51267ac5698`. Original contributors'
attribution and third-party licenses are retained. See [NOTICE.md](NOTICE.md).
The workshop has its own teaching skill and consumes this project's releases.
