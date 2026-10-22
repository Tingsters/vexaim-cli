# Bluetooth session keepalive

For the firmware upgrade, Windows source evidence and trained computer cue,
follow the [1.0.4 investigation](firmware-1.0.4-investigation.md). Its hardware
acceptance is separate from the failed earlier controls below.

## Cause and scope

An rc.5 controller-search session lost AIM6518 after recent motor and camera
activity. The operator confirmed power-off; battery had been 97%. No shutdown
command was sent. VEX describes five-minute inactivity sleep in its
[power guide](https://kb.vex.com/hc/en-us/articles/34911195338772-Charging-and-Powering-On-VEX-AIM),
but does not define whether transient REPL operations reset that timer.
The exact firmware reason for that particular shutdown was not reported.

rc.5 serviced remote status (`0x57/0x7e`) only while its program display was
active. That heartbeat keeps drawing visible, but does not replace system
liveness. A stationary display-only control lost its connection around 333
seconds of robot uptime despite recent acknowledged reads. The last successful
sample was uptime 316650 ms, 91% battery, stopped. Subsequent discovery found no
AIM6518. That control failed and must not be described as passing endurance.

The public official VEXcom 1.0.2b2 host tool (SHA-256
`cc15efc812e19a08ca5f2f864305720c8fa513b390e9004f8b806b6f40e4d40e`)
contains `_v5_SystemAlive`, which builds a simple command `0x21`. The exact wire
request is `c9 36 b8 47 21`. The existing upstream `SystemAlivePacket` and
`SystemAliveReplyPacket` implement this request/reply already; no new vendor
patch, program upload or guessed power-setting command is needed.

## Implementation

For AIM REV1 / BLE 1.0.0.b0, rc.6 starts acknowledged System Alive polling after
authentication and REPL preparation. The same connection owner sends one request
every two seconds, with a matching typed reply and a 3-second total deadline.
Only this fixed read-only request retries, for at most three consecutive
failures; there is no student-command replay or competing radio task. Ordinary
camera, sensor and Python requests do not activate the display. Pending camera reads are sliced
so the owner services liveness while waiting, preserving other replies.

Display status still has its separate 100 ms period and 60-second idle lease.
Stop releases that display but preserves session liveness. Close ends liveness;
background heartbeats do not renew the existing 30-minute client idle deadline.
They never extend robot motion deadlines. A failed probe invalidates the REPL
and marks `needs_check`, while bounded read-only retries may recover the heartbeat.
Three consecutive failures disable polling; explicit live info may establish
read-only liveness again. Uncertain student actions are never replayed.
Unknown firmware reports `keepalive.active:false` instead of claiming coverage.

The first local candidate acknowledged startup but hit its 500 ms total deadline
during a later background poll and stopped polling indefinitely. The quiet test
failed at 370 seconds, and subsequent discovery found no robot. This is failed
evidence, not proof that System Alive prevents sleep. The hardened candidate
allows a 3-second total / 2-second reply deadline, retries only the fixed read,
and publishes confirmed poll counts, consecutive failures and acknowledgment
age into cached session health. Three failures stop polling and require explicit
live recovery. The acceptance harness observes cached IPC health every five
seconds without touching the radio, so a broken heartbeat is detected promptly.

## Autonomous acceptance

The hardened CI Windows candidate also failed hardware acceptance: it received
92 acknowledged System Alive replies before the connection disappeared around
333 seconds of uptime (startup battery 86%). All polls had succeeded until the
link loss. The harness detected three subsequent failures and stopped after 187
seconds; live info could not reach the robot and the next scan found no match.
The two quiet intervals and camera/display phase therefore did not complete.
System Alive is a confirmed link probe, but is not a proven AIM inactivity reset.
The candidate must not be presented as a sleep fix. The experimental rc.6 release
supports cross-platform investigation, including Mac hardware verification.
A passing fake radio test cannot override this failed endurance result.

Stationary developer probes compared the already sourced AIM native
flags/status requests, `0x56/0x20` and `0x56/0x22`, through one BLE connection:

```sh
uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/probe-aim-idle.py --name AIM6518 --probe both --duration 420 --output .vexaim/keepalive/aim-status-probe.json
```

This probe is investigation tooling, not a student dependency or an established
fix. It changes no menu, program, firmware or actuator state. It validates CDC
framing/CRC/ACK, samples stopped state and uptime before/after, and reports failure
rather than claiming completion after a disconnect. Query names come from
`_v5_SystemStatus` and `_v5_BrainStatus` in the same cached official VEXcom.

The combined probe experienced read timeouts and brief disconnections. A CLI
reconnection succeeded without a new power-on, so those short failures do not
establish shutdown. The final flags-only probe began at uptime 318833 ms and
lost the link about 14 seconds later. None completed endurance. A first diagnostic
run also had a cleanup-method bug which masked its original exception; that run
is excluded and the cleanup was corrected before subsequent probes.

The next control adds `--probe flags --home-back`. Once per minute it sends the
official Back input (`0x56/0x65`, payload `0x54`) only after a live flags reply
confirms home screen zero. It never selects a menu tile or sends input on an
unknown/program screen. Input ACK loss aborts instead of replaying it. This is
an opt-in diagnostic control, not a student workaround or runtime behavior.
Tests cover the nonhome-screen guard and refusal to replay a lost input.

### Follow-up controls, same power-on

The operator powered AIM6518 on once for the home-Back control. Python attempts
acknowledged a Back input at system times about 42, 104 and 209 seconds, but their
status-only links failed within seconds. Adding the ordinary GATT authentication
read and retaining a Windows throughput request did not make those links stable.
The Rust CLI could reconnect each time without another physical power-on.

A separate ignored Rust hardware control, using the CLI's transport and native
vault, read stopped state at system time 372988 ms, battery 77%, position (0,0).
It acknowledged Back on confirmed home screen zero; its last successful flags
poll was at 2.28 seconds and a later request failed. This is a failed control, not seven-minute
acceptance. The early failures do not establish robot power-off or prove that
Back caused disconnection; status-only polling also failed in earlier controls.

A passive-notification control subscribed only to the previously enumerated AIM
status characteristics `6c7851a0-adf7-4de6-881d-1ce2cd0fecc9` and
`6c7851a0-adf7-4de6-881d-1ce2cd0fecf9`, then sent acknowledged System Alive reads
every two seconds. It sent no Back, menu input or actuator command. It began at
system time 523308 ms, stopped at (0,0), battery 76%, and recorded 87 successful
polls through 178.52 seconds before losing the link. A subsequent named discovery
found no robot. Passive status subscriptions are therefore not a verified fix.
The raw timing is consistent with Back refreshing an inactivity timer, but that
is an inference, not an isolated causal result.

The next Rust control combines System Alive with home-only Back. Earlier Back
controls omitted System Alive, so their brief link failures do not isolate the
input's effect. The tool requires an explicit stationary readiness string,
uses fixed source-derived packets, validates ACK framing/CRC, refuses to replay
input, and requires seven acknowledged home-Back inputs plus a full 420 seconds
and final stopped/system-time checks before passing. It has no production CLI
entry point. No diagnostic menu input or extra status subscription was added to
the runtime. A read-only MicroPython name inspection is also prepared; it calls
no possible power-management method.

From PowerShell in the CLI checkout, with all ordinary owners closed:

```powershell
$env:VEXAIM_HARDWARE_READY='stationary-bluetooth-no-actuators'
$env:VEXAIM_HARDWARE_NAME='AIM6518'
$env:VEXAIM_IDLE_MODE='back+alive'
$env:VEXAIM_IDLE_OUTPUT="$PWD/.vexaim/keepalive/aim-back-alive-rust.json"
cargo test --locked --manifest-path cli/Cargo.toml -p vexaim stationary_idle_control -- --ignored --nocapture
```

Developer modes `flags-back` and `telemetry` reproduce the failed controls;
do not repeat them when someone is unavailable to recover power. No student
needs Rust, Python packages, environment variables or these diagnostic commands.

The official VEXcode web page/download endpoints returned a Cloudflare challenge
to both normal HTTP and a fresh browser; no challenge automation was attempted.

Collect charging, power-on, USB disconnection and VEXcode closure up front.
Do not require ongoing supervision for a stationary test, or deliberately run
a power-off control when no one can recover it. A powered-off AIM cannot be
woken over this Bluetooth connection. Never use movement to fake activity.

After starting one named session, run with the matching installed candidate:

```sh
python dev/accept-keepalive.py /absolute/path/to/vexaim --session ID --duration 840 --quiet-seconds 370 --after-stop-quiet 370
```

The first quiet interval sends no foreground device requests. Only the owner may
send its background System Alive packets. Cached IPC observes acknowledgment
counts without renewing the owner lease. The next phase captures a camera image,
shows HAPPY, sends stop and repeats the quiet interval; final camera/control
checks follow. The process records failure,
rebooted uptime or insufficient duration; an early handoff is distinct from a
pass. It has no motor or kicker commands. Reports and photographs remain local
under ignored `.vexaim/keepalive`, and do not belong in releases or issues.

Software regressions cover display independence, failed/malformed alive replies,
no replay, image-read interleaving, stop/display expiry, explicit recovery and
the owner idle deadline. Harness tests verify the silent interval and reject
unsafe state, reboot, failed camera recovery and premature completion. CI does
not establish real robot power behavior; measured evidence is in
[hardware notes](hardware-notes.md).
