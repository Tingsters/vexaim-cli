# Troubleshooting `vexaim`

Use the selected transport: USB `vexaim doctor`, or the Bluetooth name/transport
options or existing session. The USB rows below do not diagnose a wireless link.

| Symptom | Likely cause | Fix |
|---|---|---|
| `robot-detected: 0 device(s)` | Charge-only cable, robot off, or not plugged in | Use the cable that came with the AIM, plug directly into the laptop (not a dock), turn the robot on. Linux: `lsusb \| grep 2888:0700`. |
| `open-ports` fails, "Device or resource busy" | Another program has the port: VEXcode, a serial monitor, another `vexaim`. **Linux:** ModemManager probes new serial ports for ~25 s | Close the other program. Linux: install the udev rule (below) or wait 30 s. |
| `open-ports` fails, "Permission denied" (Linux) | User not allowed to open `/dev/ttyACM*` | Install the udev rule (below), then re-plug. Or `sudo usermod -aG dialout $USER` and log out/in. |
| Windows opens both COM ports but `repl` gets `""` | Version 0.1.0 does not assert DTR | Check `& $vexaim --version`; install 0.1.1 or newer. See Windows notes below. |
| `repl` fails or times out with a current executable | Robot busy, booting, or another serial tool interfering | Close other serial tools, re-plug and retry at most three times; if still stuck, power-cycle. `vexaim stop` cannot repair a connection it cannot initialize. |
| Over USB, `move`/`move_for`/`kicker.kick` return without error but nothing moves (a move returns in ~10 ms, error-like sound) | Believed to be firmware locking out wheels and kicker while USB is connected (seen on one AIM; cause unconfirmed) | Do not repeat the movement. Switch to Bluetooth (`bluetooth.md`). Lights, sound, sensors and `snap` work over USB. |
| A call hangs then "timed out" after printing ~2 KB | Robot USB output buffer overflowed | Print less per burst or chunk with `wait(60, MSEC)`. |
| `snap`: "no camera with 'AIM' in its name" | Robot not plugged in, or the OS blocked camera access | macOS: System Settings > Privacy > Camera, allow your terminal/Goose. Windows: Settings > Privacy > Camera. |
| `snap` image upside-down / odd | Robot pose, not a bug | Rotate the image when analysing. |
| Unexpected `SyntaxError` on your first command | Something else (ModemManager `AT` probe) wrote to the port | Install the udev rule; re-run. |

## Linux: stop ModemManager and fix permissions (once per computer, needs sudo)

ModemManager sends `AT` commands to every new serial port. It holds the AIM busy for ~25 s after each
plug-in and can inject junk into the robot's REPL. The rule below makes it ignore the AIM and gives the
logged-in user access without the `dialout` group:

```
sh ~/.agents/skills/vex-aim/linux/install-udev.sh     # asks for sudo; installs /etc/udev/rules.d/99-vex-aim.rules
```

Then unplug and replug the robot. The rule only matches USB `2888:0700` (the AIM), nothing else.
On immutable distros (Bazzite, Silverblue) `/etc/udev/rules.d` is writable, so the same command works.

## Windows / macOS

No ModemManager or Linux udev rule is needed. Windows uses the built-in USB serial driver.
The AIM needs DTR asserted on its user interface (USB `2888:0700`, `MI_04`); system is `MI_00`. COM numbers
are assigned by Windows and can change. Version 0.1.1 asserts DTR automatically on every user-port open and
reports a COM-specific error if setup fails. Do not install a different driver or repeatedly reboot to fix 0.1.0.

Re-run the repository's `install.ps1` to update the skill and executable together, then start a new agent
session. If the installer rejects an older release, ask the instructor for the corrected package; students
do not need Rust. The instructor can build from source using an existing Rust/MSVC toolchain.
If a current executable fails, retain `doctor --json` and `--version` output when reporting it.

Allow camera access when prompted for `vexaim snap`.
Windows SmartScreen or macOS Gatekeeper may warn about an unsigned binary: on macOS run
`xattr -d com.apple.quarantine vexaim` or right-click > Open once; on Windows choose "More info > Run anyway".
Windows 0.1.1 serial execution, error/timeout recovery, and packaged installation were exercised on hardware;
Windows native BLE camera capture has separate evidence; macOS hardware and
new session/movement-helper hardware checks remain unverified.
Managed/school laptops may block unsigned
executables; ask the instructor for the loaner laptop.

## Linux binary requirements

Needs `libudev.so.1` (present on practically all systemd distributions). Combined Bluetooth builds also require the system D-Bus library/service.
Both are normally present on desktop Linux; report missing libraries clearly.
