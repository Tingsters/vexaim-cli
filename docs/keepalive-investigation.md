# Bluetooth session keepalive

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
