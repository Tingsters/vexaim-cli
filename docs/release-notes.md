# vexaim 0.5.1

Tag search now takes brief stationary native-camera readings at eight viewpoints
instead of relying on continuous rotation. This brings the successful Windows
blue-barrel-to-purple-Tag-0 test into `find`, `approach`, `deliver` and named
vision macros. Cargo acquisition remains a brisk continuous sweep.

`behaviors.configure(verification="contact", tag_turn_dps=90)` opts into fast
play: finish deliberate bounded contact, continue to the marker and operate the
kicker without diagnostic retention reverses, repeated possession gates or host
camera round trips. The default `verification="vision"` retains those checks.
Assumed completion is explicit in result evidence; it does not fabricate native
attachment/release confirmation. Missing targets, transport errors, cancellation
and whole-activity deadlines still stop the sequence.

Short native moves now allow acceleration/status-reporting margin while still
returning immediately on completion. Matching workshop instructions warm the
helpers during stationary setup and compose each game in one execution. The
workshop installer requires 0.5.1 so students receive matching APIs and guidance.

The earlier test's camera independently showed the barrel beside the marker.
The final 0.5.1 source follow-up could not reacquire blue in the current layout;
it stopped after a bounded search. Full new-mode hardware acceptance remains
pending. Automated tests cover stationary-only tag decoding, missing targets,
false-negative possession, assumed placement and cancellation/deadlines. See
[hardware evidence](https://github.com/Tingsters/vexaim-cli/blob/main/docs/hardware-notes.md).
This release does not claim to resolve all Bluetooth or lighting failures.

## Previous release: 0.5.0

Compose supported object search, magnetic pickup and tag delivery in one
`exec --behaviors` activity. The CLI supplies `behaviors.find`, `collect`,
`approach` and `deliver`; no saved robot program or student Python installation
is needed. Existing vision macros share the same controller.

Collection now checks possession independently of temporary detection loss,
continues bounded near-field contact, verifies retention and permits one local
retry. Searches stop after one sweep, marker stand-offs match VEX (60 pixels
for tags, 140 for AIM robots), and macros honor session velocity settings.
Activity deadlines use the robot system clock where available and a gated timer
callback; expired callbacks cannot stop a later activity. Progress identifies
the phase and deadline errors retain the last native call.

The vision controller loads on first use, preserving ordinary session startup.
Hardware testing confirmed bounded search and explicit pickup failures in an
obstructed layout; successful physical pickup/delivery remains unverified.
Later reconnection attempts failed and were checkpointed. Details and measured
timings are in docs/hardware-notes.md; simulation does not certify physical
pickup accuracy or resolve the earlier Goose timeout's root cause.

## Previous release: 0.4.2

Windows Bluetooth camera downloads now authorize a read-only transfer at its
boundaries instead of reading the pairing characteristic before every small
image block. Ordinary commands and keepalive retain their authentication checks;
the read authorization is bound to one connection and cannot authorize writes
or robot movement. Other operating systems retain per-packet checks pending
their own hardware comparisons.

On the tested Windows computer and AIM9E18 firmware 1.0.4, comparable ~27 KiB
images improved from 43–45 seconds to 26–29 seconds. A same-executable comparison
reduced authentication reads from 149 to 16. No USB radio re-enumerations were
observed. These results describe the tested adapter and scene; they do not
establish a universal camera speed or a 15-second arbitrary-object search.

Standalone Bluetooth snap now uses the same platform connection policy and
capture guard as persistent sessions. Interrupted camera/LCD transfers require
a fresh session before another capture, and transfer authentication fits inside
the existing finite deadline. Windows keeps the OS-default connection policy;
the balanced experiment provided no speed benefit.

The matching agent skill explains bounded searches, useful image checkpoints,
native feedback and short unattended testing. Developer-only diagnostics and
local perception prototypes are included with simulated regression checks.
Larger payload windows and alternate pacing remain diagnostic-only; no model
download, new paid image API or new student search command is introduced.

The short hardware comparison did not complete a five-minute candidate stability
screen or physical search/approach acceptance. The independent Python comparison
was incomplete because of a vault-lookup mismatch; the developer lookup is fixed
and unit tested, without changing stored credentials. See
[the investigation report](https://github.com/Tingsters/vexaim-cli/blob/main/docs/bluetooth-camera-responsiveness.md)
for the separate reports, executable hashes and remaining limits.
