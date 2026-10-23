# Bluetooth pairing, persistent sessions and handoff

Select the exact AIM name, keep VEXcode closed and use matching CLI/basic skill
0.4.0 or newer. Windows application authentication is distinct from OS bonding.
No USB cable, firmware update or saved robot program is needed.

```sh
vexaim bluetooth scan
vexaim --name AIM1234 bluetooth pair
vexaim --json --name AIM1234 session start --persistent --takeover
```

Default pairing reads a masked local terminal. `bluetooth pair --code-stdin`
allows an agent to pair using one line of stdin; the workshop deliberately
permits the student to report that short-lived code in chat. Never put it in a
CLI argument, plaintext file or diagnostic output. Keep the same pairing process
waiting: the code appears only after its pairing request starts. A wrong/expired
code needs a fresh request. Credentials use the native OS vault and are reused
where valid; only explicit `bluetooth forget` deletes the CLI credential.

## Agent pairing on Windows without retained tool stdin

The matching skill ships `scripts/pair.ps1`. Start it through Windows PowerShell
5.1; it creates a hidden, detached broker and a current-user-only named pipe.
It does not inherit the agent's shell capture handles. Its temporary directory
contains only non-secret status. No student terminal is needed.

```powershell
$bridge = Join-Path $env:USERPROFILE '.agents/skills/vex-aim/scripts/pair.ps1'
& $bridge -Action Start -Name AIM1234
# Retain returned directory. Poll until state is waiting; ask for the LCD code.
& $bridge -Action Status -Directory DIRECTORY
# Submit the displayed code as one line of stdin, never a script parameter:
'CODE_FROM_STUDENT' | & $bridge -Action Submit -Directory DIRECTORY
& $bridge -Action Status -Directory DIRECTORY
```

For a CMD-only tool, explicitly launch `powershell.exe -NoProfile -File` with the
bridge path; submit with a stdin pipeline. Use the tool's actual shell syntax.
`Start` returns promptly; Status reports waiting/authenticating/paired/failed.
The broker has a two-minute input deadline and cleans up the pipe and child.
Delete its non-secret temporary directory after a terminal state. On macOS/Linux,
prefer a retained native tool process stdin; otherwise use a private named FIFO
with its read/write end kept open for the same pairing process and finite timeout.

## Keep ready across workshop breaks

Persistent sessions are detached background owners, independent of a single
prompt/chat or agent application. They maintain/recover the same selected robot
without an inactivity cutoff, never another robot/USB. Standard sessions retain
their 30-minute idle cutoff. Explicit `session close` stops reconnection and
retains credentials. Re-pairing is not ordinary reconnection.

Read `sessions-and-motion.md` for cached lifecycle state, stop/retry, time budgets
and retained results. A dropped link/closed Windows object is not proof of sleep.
Do not ask for power cycling until automatic repair and evidence warrant it.

Windows maintains its GATT session interest while owned. Closed objects are
recreated before reconnection, and both notifications are restored. Changed or
rejected authentication pauses retries instead of overwriting another pairing.
This is a conservative handoff mechanism, not proof that AIM accepts new pairing
while another computer remains connected. Until verified, explicitly release
from the previous computer if required. Pairing another device may invalidate
previous saved codes; do not promise otherwise.

Camera photographs use the native 640x480 JPEG path independently of LCD mode.
No menu navigation, reset, preview project or USB cable is required. Firmware
profiles and actual hardware evidence are in docs/hardware-notes.md. The finite
power lease is independent from System Alive link monitoring; its experimental
metadata must not be described as universal verified sleep prevention.
