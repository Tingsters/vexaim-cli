# Troubleshooting

First run the robot check. Every failed step prints a `fix:` line.

```
~/.agents/skills/vex-aim/bin/vexaim doctor           # macOS / Linux
```

Windows PowerShell:

```powershell
$vexaim = Join-Path $env:USERPROFILE '.agents\skills\vex-aim\bin\vexaim.exe'
& $vexaim --version
& $vexaim doctor
```

## Installing

| Symptom | Cause | Fix |
|---|---|---|
| `download failed (offline, or no release published yet?)` | No internet, a proxy, or the repository has no release yet | Check the connection and retry. Instructors: publish the release (see `docs/instructors.md`). Or build locally: install Rust from https://rustup.rs, then `sh install.sh --from-source`. |
| `checksum mismatch ... refusing to install` | Corrupted or tampered download | Retry. If it repeats, do not install; tell the instructor. |
| `0.1.1 or newer is required on Windows` | The release contains 0.1.0, whose DTR bug prevents REPL communication | Ask the instructor for the corrected release/package. The installer preserves existing skill folders. Maintainers with Rust/MSVC can use `-FromSource`; students need no compiler. |
| `no prebuilt binary for <os/arch>` | A platform we do not build (for example Linux ARM) | `sh install.sh --from-source` (needs Rust). |
| `<dir> already exists and was not installed by this script` | You already have a skill folder with that name | Move it away, or re-run with `--force`. |
| `the vexaim binary does not run on this machine` | Blocked by the OS or antivirus, or wrong architecture | macOS: `xattr -d com.apple.quarantine ~/.agents/skills/vex-aim/bin/vexaim`, or right-click > Open once. Windows: SmartScreen "More info > Run anyway"; school laptops may forbid unsigned programs: use the instructor's loaner laptop. |
| Build from source fails on Linux (`libudev`) | Missing development headers | `sudo apt install libudev-dev pkg-config` (Fedora: `sudo dnf install systemd-devel`). |
| The agent does not know the `vex-aim` skill | It was started before the install | Start a **new** session (quit and reopen Goose; new `claude` / `codex` session). Goose/Codex read `~/.agents/skills`, Claude Code reads `~/.claude/skills`. |

## Talking to the robot

| Symptom | Likely cause | Fix |
|---|---|---|
| `robot-detected: 0 device(s)` / "no VEX device found" | Charge-only cable, robot off, or not plugged in | Use the cable that came with the robot, plug directly into the laptop (not a hub or dock), switch the robot on. Linux: `lsusb \| grep 2888:0700`. |
| `open-ports` fails, "Device or resource busy" | Another program has the port (VEXcode, a serial monitor, a second agent). **Linux:** ModemManager probes new serial ports for ~25 s | Close the other program. Linux: install the udev rule (below) or wait 30 s. |
| `open-ports` fails, "Permission denied" (Linux) | Not allowed to open `/dev/ttyACM*` | Install the udev rule (below) and re-plug. Or `sudo usermod -aG dialout $USER` and log out and in. |
| Windows opens both ports but `repl` reports `got ""` | Version 0.1.0 leaves DTR low | Install 0.1.1 or newer; the new executable asserts DTR automatically on each connection. |
| `repl` fails or times out with a current executable | Robot busy, booting, or serial interference | Close other serial tools, re-plug and retry at most three times. Power-cycle if still stuck. `vexaim stop` needs the same REPL connection and cannot repair failed initialization. |
| A command hangs and then "timed out" after printing about 2 KB | The robot's USB output buffer overflows on large bursts | Print less per burst, or chunk with `wait(60, MSEC)` between pieces. |
| "the robot disconnected during the command" | Cable pulled or robot lost power mid-command | Check the robot (a move may or may not have run) before re-running. Re-plug and run `doctor`. |
| `snap`: "no camera with 'AIM' in its name" | Robot not plugged in, or the OS blocked camera access | macOS: System Settings > Privacy & Security > Camera, allow your terminal / Goose. Windows: Settings > Privacy > Camera. |
| Photo is upside down | The robot is sitting or mounted upside down | `snap` never rotates the image; rotate 180 degrees before analysing. |
| Goose (Flatpak) cannot see the robot | The Flatpak sandbox has no access to `/dev/ttyACM*` or `/dev/video*` | Use the standard Goose build or the Goose CLI. (Advanced: `flatpak override --user --device=all io.github.block.Goose`.) |
| Unexpected `SyntaxError` on the first command (Linux) | ModemManager wrote an `AT` command to the robot's console | Install the udev rule; re-run. |

## Linux: stop ModemManager and fix permissions (once per computer, needs sudo)

ModemManager sends `AT` commands to every new USB serial port. It holds the robot's ports busy for about 25 seconds
after each plug-in and can inject junk into the robot's console. The rule makes ModemManager ignore the AIM
(USB `2888:0700`, nothing else) and gives the logged-in user access without the `dialout` group:

```
sh ~/.agents/skills/vex-aim/linux/install-udev.sh        # or: sh install.sh --udev   (asks for sudo)
```

Then unplug and replug the robot. Check it took effect: `udevadm info -q property -n /dev/ttyACM1 | grep MM_DEVICE_IGNORE`
should print `ID_MM_DEVICE_IGNORE=1`. Remove it with `sudo rm /etc/udev/rules.d/99-vex-aim.rules`.
Immutable distros (Bazzite, Silverblue) keep `/etc/udev/rules.d` writable, so the same command works.

## Windows serial communication

Windows uses its built-in `usbser` driver; no VEXcode, custom driver, or udev rule is needed.
The AIM exposes system serial interface `MI_00` and Python serial interface `MI_04`. Inspect them without
opening the ports:

```powershell
Get-CimInstance Win32_SerialPort |
  Where-Object { $_.PNPDeviceID -like '*VID_2888&PID_0700*' } |
  Select-Object DeviceID, Name, PNPDeviceID
```

Do not infer interface roles from COM-number order. On the test machine system was COM4 and user was COM3.
Linux asserts DTR on open; Windows does not. The AIM stays silent when its user port's DTR is low, even
though discovery and opening the ports succeed. Version 0.1.1 explicitly asserts DTR, checks errors, and
retains separate read/write handles. Waiting for ModemManager is irrelevant on Windows.

Update with `powershell -ExecutionPolicy Bypass -File install.ps1`, then start a new agent session.
Until the corrected release is published, instructors can supply the rebuilt ZIP plus SHA256SUMS via
`install.ps1 -FromDir <folder>`, or use `-FromSource` with an existing Rust/MSVC toolchain. A source checkout
alone does not update the installed executable. If 0.1.1 or newer still fails, save `--version` and
`doctor --json` output, including the COM-specific Windows error.
