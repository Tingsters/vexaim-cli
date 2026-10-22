# Sessions and movement (agent instructions)

Translate ordinary prompts into robot actions. These commands are agent tools;
users need no calibration mat, agent settings or Python dependencies.

## One connection

Bluetooth requires vexaim 0.2.0 or newer; USB sessions and native catalogue actions
require the matching 0.3 command release. For USB start with `vexaim --json session
start` (optionally `--device N`). For Bluetooth use the named start below.
Use this skill's installed executable after installing its matching release;
a repository checkout alone does not update it. Pair as described in `bluetooth.md`.
Use the exact robot name; do not fall back to another robot/USB.

PowerShell example (replace NAME with the selected name, not a secret):

```powershell
$vexaim = Join-Path $env:USERPROFILE '.agents/skills/vex-aim/bin/vexaim.exe'
$connection = & $vexaim --json --name NAME session start | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $connection.ok) { throw 'Robot connection failed' }
$robotSession = $connection.session
```

For Claude use `.claude`. On macOS/Linux use the same executable-relative flags.
Keep the returned ID in the current agent context; no student session management.
Startup discovers/authenticates, retains both notifications, initializes helpers
and returns battery/stopped/gyro state. It does not move or recalibrate the robot.
Repeated start for the same name reuses the owner. Normal standalone Bluetooth
commands refuse to take over an active session; use its ID instead.

```powershell
& $vexaim --json --session $robotSession session status  # cached, no radio I/O
& $vexaim --json --session $robotSession info            # live status
& $vexaim --json --session $robotSession exec "print(robot.get_battery_level())"
```

No separate doctor/info before each movement when the current session is healthy.
Never call session close at the end of every prompt. Close when robot work is
finished or before a fresh connection after sleep/failure. Idle owners close after
30 minutes without client work. The experimental 0.3.0-rc.6 release sends
acknowledged System Alive requests every two seconds, independently of
the LCD and without renewing this 30-minute deadline. Stop releases display and
movement but preserves session liveness. Close ends both. This does not extend a
robot-side movement deadline or replay an action after an interruption.

Hardware testing showed sleep/link loss despite successful replies. This
candidate is not a verified sleep fix: `prevents_sleep:false` distinguishes its
link health checks from power management. Do not infer sleep prevention from
`active` or `healthy`.

Startup/live info include `keepalive.active`, `method` and `period_ms`. Unknown
firmware reports inactive. A failed heartbeat marks `needs_check`; an explicit
live info can re-establish the read-only heartbeat, while lost links require a
fresh session. Power loss still needs a person to switch the AIM on.
After firmware changes, inspect `device_info` once. The rc.7 candidate recognizes
the observed `1.0.4.b0` profile alongside `1.0.0.b0`; earlier guards can report
inactive monitoring despite a working Python console. This compatibility change
does not establish sleep prevention. Keep the measured hardware coverage and
matching installed skill/binary version explicit.

The rc.7 integration candidate also owns the existing system REPL and a finite
SDK power lease on the exact complete `1.0.4.b0` profile. Its first mechanism
control passed 20 quiet minutes, but full CLI acceptance remains pending. See
the Bluetooth reference for `keepalive.power`, the REPL Mode screen and expiry.
No student project upload or additional student command is required. Preserve
the same session across prompts so the CLI can manage that context automatically.

## Translate ideas into actions

"Spin in a circle" -> announce one full turn in place, then:

```powershell
& $vexaim --json --session $robotSession turn left 360
```

Honor explicit direction/amount. Default 30 DPS is conservative until the
developer surface matrix validates a faster general default. A request to go
faster can select `--speed 60` or `90` only within the applicable hardware evidence
and physical readiness. Do not insert a preliminary 15-degree turn into every
ordinary request or silently double the requested movement.

"Move forward five centimetres" ->:

```powershell
& $vexaim --json --session $robotSession move 50
```

Angle is robot-relative: 0 forward, 90 right, 180 backward. Move speed defaults to
80 mm/s (native ceiling 200 mm/s); distance has no 500 mm cap. Turn angle is
0.1..360 degrees in the legacy helper, native speed ceiling 150 DPS. Defaults
remain conservative. Helpers reject nonfinite/out-of-range values before
motion. Compose finite actions for requests such as a short dance or a square;
these tools do not restrict students to the example prompts. Bound custom Python
loops, include `finally: robot.stop_all_movement()`, and choose reasonable small
defaults when the prompt permits, announcing what will happen. Ask about a missing
detail only when it materially changes the requested behavior or physical space.

`--json` emits a `started` event immediately when the robot acknowledges issuing
the command, then a final `result`. `dispatch_ms` includes delivery/acknowledgement,
not agent reasoning and not an independent measurement of wheel movement.
Results include actual elapsed motion, signed rotation, headings, position,
battery and stopped state. `physical_accuracy_verified:false` is intentional:
robot sensors cannot certify their own accuracy. Do not tell students a turn was
physically exact based on those numbers alone. Acknowledge completion immediately;
avoid unrelated reporting work after every small action.

## Stop, busy, sleep and uncertain outcomes

```powershell
& $vexaim --json --session $robotSession stop
& $vexaim --json --session $robotSession session close
```

Stop uses the owner connection and preempts an active operation. It is not a
guaranteed instant emergency stop; use the physical switch when necessary.
The firmware's stopped flag can lag a stop command. The CLI sends stop once and
polls for up to one second; it reports failure if confirmation never arrives.
Helpers have a robot-side maximum 20-second action deadline even if the owner
dies. Arbitrary `exec` does not inherit their bounds. A second movement is rejected
as busy, never silently queued. Caller disconnection interrupts its active action.

After interruption/error, run live `info` to verify stopped state before a fresh
action. Never retry a movement whose delivery is uncertain. If the link is down,
check power, close/start the session, then require live state before a *new*
movement. Give an explicit power-on cue when needed; never ask for a USB replug to
fix wireless use. Cached status is not a new power/battery measurement.

## Camera is optional

```powershell
& $vexaim --json --session $robotSession snap -o photo.jpg
```

This remains a native camera snapshot, independent of LCD menus. It shares the
same connection and is rejected while another operation is active. Stop cancels
an active transfer. After cancellation, live info restores movement availability,
but another snapshot needs close/start to discard the uncertain system transaction.
Do not begin camera downloads before normal movement just to calibrate it.
Do not require kit signs or ask anyone to identify their floor. Automatic visual
correction is disabled; target navigation is a separate future feature. Keep
photos local unless the user explicitly authorizes sending them.
