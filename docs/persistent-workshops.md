# Persistent workshops and recovery

## Contract

A Bluetooth bond (saved credential), a live GATT connection, the Python program,
the displayed picture and the power lease are independent. A face remaining on
screen proves none of the others. `session status` is cached and reports owner
health; `info` is a fresh robot check. A persistent owner remains alive across
prompts, chat changes and agent application closure, but cannot keep a powered-off
computer, disabled radio or flat robot battery connected.

Use `vexaim --name AIM1234 session start --persistent --takeover` once. Reuse the
returned session ID. The ordinary session still has its 30-minute client idle
limit; only explicit persistent mode removes that limit. Power protection remains
a finite 30-minute robot lease renewed by the living owner, never a permanent
robot setting. `session close` stops owned activity, restores power policy and
releases the link. It does not erase pairing. Closing a conversation does not
mean closing the robot session.

## Reconnect and handoff

The owner detects failed link/status/authentication checks and becomes
`reconnecting`. New ordinary actions are rejected with `delivery: not_sent`, not
queued for later movement. It discards the old transport, first reconnects to the
known peripheral, then uses exact-name discovery after repeated failures. Robot
identity, firmware and stored authentication must match before Python/native
writes. A fresh stopped check, runtime and lease repair precede `ready`.

Changed or missing credentials produce `auth_required`: reconnect attempts cease,
and even closing the former owner must not stop a new owner's program. To use a
second computer, explicitly close the old session, then pair/connect on the new
one if needed. New pairing does not imply guaranteed eviction: only one Windows
computer was available for acceptance. Do not forget/re-pair for ordinary outages.
Persistent connection is an application's policy, not a guarantee made by the
Bluetooth standard.

## Timeouts and retries

JSON output is a stream: read all events through `event: result`. The session
reports preparing/running and preserves `last_progress` and `last_result` after
a caller disappears. `preparation_ms`, `upload_ms`, `execution_ms` and `total_ms`
are distinct. An exec deadline begins after submitting source. Cleanup has its
own finite budget. Suggested workshop budgets: 30 seconds in robot code, 60 for
CLI execution, at least 120 in the outer tool. Every robot wait must be checked.

Unknown delivery requires a live stop/readiness check, never automatic replay.
A student's explicit new activity or retry authorizes `--takeover` on that chosen
robot, followed by one freshly generated bounded script. This native program
replacement does not seize Bluetooth ownership from another computer.

## Reproducible stationary acceptance

Run `uv run --no-project python dev/workshop_endurance.py --tool PATH --name NAME
--output dist/acceptance` only after charging the robot, unplugging USB, closing
VEXcode and receiving readiness. It uses no wheels or kicker. It records binary
hash, owner health, reconnects and local camera artifacts. It waits 35 minutes
without live student commands (cached status does not extend ordinary idle), then
checks camera/display/stop and finishes at one hour. Leave the owner open.

An ignored Rust test, `stationary_closed_link_recovers_without_pairing_or_movement`,
requires `VEXAIM_STATIONARY_READY=yes`, explicit `VEXAIM_STATIONARY_NAME`, and no
existing owner. It deliberately closes its own transport, recovers automatically
and verifies stopped state and active power management. On Windows/AIM6518,
firmware 1.0.4, this passed in 7.339 seconds on 22 October 2026.

The earlier candidate recovered four spontaneous link failures without a human
restart. Windows BTHUSB adapter-initialization events occurred around these
outages; adapter reinitialization is a plausible contributor, not established
proof of its exact driver cause. Recovery alone must not be described as an
uninterrupted physical radio link. No student cargo movement was tested here.

### One-hour Windows result, 22 October 2026

The locally built core candidate, SHA-256
`ab55df5e2d3fec493a2d9b68e76862035f643f1def7760a244ff0e5aebfd482c`,
passed the complete stationary harness in 3654.92 seconds including setup and
final capture. The quiet interval was 35 minutes without live client commands;
the owner then completed camera, drawing, stop and live-info checks, followed
by the remaining quiet period and a final camera capture. Battery went from
61% before this run to 38% at the middle check and 23% at the end. It reported
stopped with no owned action. No wheels or kicker ran, and no further human
action was requested. Local photographs showed the controller, not LCD content.

The owner recorded 33 automatic recoveries. Five-second cached sampling observed
32 outages, totaling about 692 seconds, with a longest observed gap of 65.69
seconds. This is a pass for owner persistence, power retention and recovery,
and a failure to establish an uninterrupted physical connection on this host.
It does not certify motion accuracy or constant low latency.

Windows additionally changed the USB radio's `DEVPKEY_Device_LastArrivalDate`
from 18:06:41 to 18:07:11 local time during these failures. The active radio was
the Generic Bluetooth Radio (`0a12:0001`); the built-in MediaTek adapter was
already disabled. Neither drivers, adapter settings nor OS power settings were
changed. USB-radio re-enumeration is observed evidence; why it is happening,
including any driver/controller interaction, remains unresolved. Do not tell a
student to power-cycle an awake robot as the first response to this condition.

The core endurance build preceded the final program-replacement metadata fixes.
Those have separate unit and shipping-candidate checks; do not relabel this
hour as a test of an identical shipping executable. Raw results and images stay
locally under `dist/persistent-workshop-final/`, outside Git.

### CI-built Windows retry result

The Windows package from CI run `39881212223`, commit `99538d9`, executable
SHA-256 `9e03ebdbba35a3580e23fb477e3889ee8b6ff849d59265477859354020f1e7b2`,
passed `dev/workshop_retry_acceptance.py`: start a persistent owner, begin a
20-second HAPPY display routine, replace it while still running, retain its
confirmed cancellation and the new live readiness, show a fresh HAPPY, and take
a native camera frame. Native takeover and readiness restoration took 17.235
seconds; the 640x480 image took 7.874 seconds and returned `control_ready:true`.
It stayed stopped and retained the owner, at 22% battery. No physical action or
further pairing code was needed. The first startup found no robot during another
adapter gap; one rescan and fresh stationary attempt succeeded. That failed
startup remains a failed attempt, not an interrupted activity replay.

This is still single-computer Windows evidence. Actual second-computer pairing
and handoff, uninterrupted radio reliability, and physical cargo collection
remain outside this acceptance.

The later Windows comparison isolated a retained throughput request as an
avoidable reset trigger on the tested radio. OS-default mode completed a
60-minute uninterrupted interval; the original full report failed its final
LCD deadline, followed by a passing capture-deadline recheck. See
[Windows investigation](windows-bluetooth-investigation.md) for the separate
controls, remaining limits and image-transfer performance.

Primary references: [Microsoft GATT lifecycle](https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/gatt-client),
[MaintainConnection](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.genericattributeprofile.gattsession.maintainconnection?view=winrt-26100),
[Windows pairing](https://support.microsoft.com/en-gb/windows/hardware/bluetooth/pair-a-bluetooth-device-in-windows),
[VEX wireless pairing](https://kb.vex.com/hc/en-us/articles/34948834972564-Connecting-VEX-AIM-to-VEXcode-AIM-Wireless).
