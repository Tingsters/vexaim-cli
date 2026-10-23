# Sessions, recovery and movement

Translate prompts into robot behavior through the installed, matching binary.
Use its full path. A source checkout alone does not update installed tools.

## One background connection

For Bluetooth select the exact name and use:

```powershell
$vexaim = Join-Path $env:USERPROFILE '.agents/skills/vex-aim/bin/vexaim.exe'
& $vexaim --json --name NAME session start --persistent --takeover
```

For Claude use `.claude`; macOS/Linux use their executable path with the same
flags. Retain the returned session ID. Persistent mode is explicit, survives
chat/app exit and idle breaks, and keeps the same robot selected. A computer
restart needs a new owner, using saved credentials. No startup service, project
upload, agent settings or compiler installation is required.

Without `--persistent`, ordinary owners close after 30 minutes without client
work. Explicit `session close` always releases the owner and stops reconnecting;
it does not forget credentials. Don't close a persistent session just because
an activity or conversation finished. A request to disconnect/hand over does close it.

`--takeover` authorizes the native stop of a running student program when needed.
A healthy idle owner is reused. To replace an active routine use `stop`, live
`info` and one fresh execution. If native ownership blocks initialization, use
`session start --persistent --takeover`. Do not use `exec robot.stop_program()`:
that can terminate the interpreter before the expected response frame returns.

`session status` reads cached state without radio traffic. `ready` indicates the
last monitored usable connection; it is not a new sensor or power measurement.
`reconnecting` rejects new activity as `delivery:not_sent` while the owner
recreates/authenticates the same device and restores notifications/console.
Background retry delays are 1, 2, 5, 10, then 30 seconds. Never queue a stale
movement to run minutes later. After recovery, read live `info` and issue fresh work.

`auth_required` pauses background reconnect after missing/rejected/changed
credentials or foreign program ownership. Do not fight another student by
re-pairing automatically. Explicit handoff releases the old connection. Native
pairing while another computer is connected and credential validity after
handoff need hardware verification; do not present them as guaranteed behavior.

A transport failure alone does not prove sleep. Windows closed-object errors
need a fresh connection, not an automatic physical power-cycle request. Only
request physical help after evidence of unavailability when later attendance
was allowed. For setup-only unattended work, checkpoint and stop instead; see
`unattended-work.md` for the applicable attendance policy.

System Alive monitors link health. The firmware-gated robot-side power lease is
separate; persistent owners renew it every five minutes while keeping its finite
30-minute robot watchdog. If the host disappears, that finite lease can expire.
Unknown firmware is not given private SDK power writes.

## Timeouts and retained evidence

Default composed activities: 30 seconds of bounded robot behavior, CLI
`exec --timeout 60`, outer tool timeout 120 seconds. Execution timeout starts
after source submission; setup/upload and cleanup have additional bounded time.
The session limit remains 48 KiB and 1..120 execution seconds. For larger budgets,
allow at least execution timeout +60 seconds in the outer tool.

JSON output is a stream: preparing/running progress events, optional robot
`__VEXAIM_EVENT__` progress lines, then a final result. Parse the final event rather
than assuming stdout is one JSON document. Results separate preparation, upload
and execution timing. `last_result`/`last_progress` remain in cached status after
caller cancellation. `ok:true` proves Python completed, not that a custom
activity physically achieved its goal; check its measurement/outcome too.

## Translate ideas into actions

`program_running` is different from changed authentication: the background owner
leaves that program alone until a fresh `session start --takeover` replaces it.
No pairing code or student confirmation is needed for an authorized new workshop
activity on the selected robot. `auth_required` yields the Bluetooth connection;
even closing that former owner must not stop another computer's program.

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

After interruption/error, verify live stopped state before fresh action. Explicit
student retry permits a new revised routine; uncertainty alone never triggers
movement replay. Let automatic connection recovery complete first and consult
cached outcome/progress. A `delivery:not_sent` request can be resubmitted after
readiness. Don't demand a power cycle while the robot is visibly awake.

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
