# Mac hardware verification: 0.3.0-rc.6

Both Apple Silicon and Intel Mac bundles are built and installation-tested in
CI. Robot checks on macOS are still pending. This experimental release adds
Bluetooth link monitoring; it has not solved the AIM's observed inactivity
shutdown on Windows. A healthy poll count is not proof of sleep prevention.

Install the pinned binary and matching skill without compiling:

```sh
curl -fsSL https://raw.githubusercontent.com/Tingsters/vexaim-cli/v0.3.0-rc.6/install.sh | sh -s -- --version 0.3.0-rc.6
```

Close existing robot sessions before updating, then start a new agent session.
The installer selects the native Mac architecture. No Rust, Python packages,
VEXcode, saved project or robot firmware update is required.

For a stationary Bluetooth check, charge and switch on the AIM, unplug USB,
close VEXcode, and put a recognizable object in front of its camera. Enable
Bluetooth on the Mac. If macOS requests Bluetooth or Keychain access, handle
those prompts locally. Pairing codes belong only in the masked terminal prompt.

Ask the agent:

> Use the vex-aim skill with Bluetooth and my robot's exact name. Check the
> installed version is 0.3.0-rc.6. Pair if needed, start one reusable session,
> report live battery and stopped state, read the inertial heading and timer,
> capture a native camera observation and open its returned image in this turn,
> then show HAPPY for five seconds. Stop and close the session when finished.
> Do not move the wheels or operate the kicker. Keep all captures and logs local.

For manual checks, use `~/.agents/skills/vex-aim/bin/vexaim` (Codex/Goose) or
`~/.claude/skills/vex-aim/bin/vexaim` (Claude Code):

```sh
vexaim="$HOME/.agents/skills/vex-aim/bin/vexaim"
"$vexaim" --version
"$vexaim" bluetooth scan
"$vexaim" --name AIM6518 bluetooth pair
"$vexaim" --json --name AIM6518 session start
```

Replace `AIM6518` with your robot's exact name. Copy the returned `session` ID
into `robot_session` below; do not start another owner for each operation.

```sh
robot_session='RETURNED_SESSION_ID'
"$vexaim" --json --session "$robot_session" info
"$vexaim" --json --session "$robot_session" inertial get-heading
"$vexaim" --json --session "$robot_session" timer system
"$vexaim" --json --session "$robot_session" camera observe --output-dir .vexaim/captures
"$vexaim" --session "$robot_session" screen show-emoji HAPPY
# Observe the physical display for five seconds, then clean up.
"$vexaim" --session "$robot_session" stop
"$vexaim" --session "$robot_session" session close
```

Check each command's exit status before continuing. A camera result should have
`ok:true`, a new absolute `path`, 640x480 dimensions and `control_ready:true`.
Open that actual image and compare it with the object in front of the robot;
metadata alone does not verify image contents. On failure, retain the error
locally and recover the connection before issuing another robot command.

Record Mac model/architecture, macOS version, CLI version, robot firmware,
transport, each observed result, and elapsed time before any disconnect. Mark
untested or failed steps explicitly. A short functional pass does not establish
endurance. After shutdown, a person must switch the AIM back on. Motor/kicker
acceptance requires a separate supervised test with physical clearance.
