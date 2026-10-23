# vexaim 0.4.2

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
