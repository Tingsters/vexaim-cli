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

Primary references: [Microsoft GATT lifecycle](https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/gatt-client),
[MaintainConnection](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.genericattributeprofile.gattsession.maintainconnection?view=winrt-26100),
[Windows pairing](https://support.microsoft.com/en-gb/windows/hardware/bluetooth/pair-a-bluetooth-device-in-windows),
[VEX wireless pairing](https://kb.vex.com/hc/en-us/articles/34948834972564-Connecting-VEX-AIM-to-VEXcode-AIM-Wireless).
