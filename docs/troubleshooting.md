# Troubleshooting

Use the installed executable, not a stale development checkout. Check --version
and update executable and basic skill together through the installer. The
[generic skill troubleshooting reference](../skill/vex-aim/references/troubleshooting.md)
contains USB details and platform guidance.

## Installation

Download the bundle matching your platform, check SHA256SUMS, extract, and run
its installer. It installs offline without Rust or Python packages. Repository
installers fetch the latest stable release. -FromDir / --from-dir accepts local
release archives and SHA256SUMS; the workshop wrapper also needs the release's
standalone installers and VERSION. A failed download does not start a build.

If another installation occupies an unmarked skill folder, move it aside or
explicitly select force after inspecting it. Close active robot sessions before
updating. Managed devices may block downloaded executables; follow your device
administrator's policy rather than changing system settings automatically.

Linux combined binaries need libudev and the system D-Bus library/service.
Bluetooth needs a working adapter and OS permissions. macOS/Windows USB camera
capture may require camera access permission. Only Linux USB uses the supplied
udev helper; ask before sudo and reconnect USB afterward.

## USB

Run doctor with USB connected and the AIM switched on. Use a data cable and close
VEXcode/serial monitors. Windows 0.1.0 left DTR low, producing silent REPL output;
all current standalone bundles retain the 0.1.1 correction. Do not replace the
driver or repeatedly reboot to repair an obsolete binary.

## Bluetooth

Read the [Bluetooth skill reference](../skill/vex-aim/references/bluetooth.md).
Use the exact robot name and Bluetooth explicitly, or reuse its session ID.
A USB doctor failure does not diagnose a wireless link. Check power when scans
find nothing; the AIM can sleep while idle. A cached session status is not a
fresh live check. Pairing codes belong in a masked local terminal, not chat.

After a failed/interrupted operation, obtain live status and confirm stopped
state before a new movement. Never replay uncertain movement. Close/start after
link failure, and before another snapshot if a camera transfer was cancelled.
Stop requires a working connection; supervise movement near the physical switch.

Native camera JPEGs work independently of LCD mode; do not reset or navigate
menus to take a photo. Software CI covers four platform builds/installers;
hardware results and remaining checks are documented separately in
[hardware evidence](hardware-notes.md) and [movement acceptance](motion.md).
