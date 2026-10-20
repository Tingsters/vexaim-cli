# Vendored upstream: vexide/vex-v5-serial

`vex-v5-serial/` and `vex-cdc/` are copies of the crates in
[vexide/vex-v5-serial](https://github.com/vexide/vex-v5-serial) (MIT, see `LICENSE-vex-v5-serial-MIT`),
taken from upstream commit `b3a712a16c9c6819b69faacfee2284826a138070` (2026-09-22) with the patches
`0001-aim-user-port-and-write-all.patch`, `0002-serial-windows-capable-async-layer.patch`, and
`0003-windows-aim-dtr.patch`, `0004-aim-bluetooth-transport.patch` and
`0005-validated-camera-download.patch` applied. They are
vendored so the repository builds with no network access to anything but crates.io, and so students never depend
on an unreleased upstream branch.

## Patch 0002: the serial layer did not compile on Windows

`vex-v5-serial`'s `serial` feature uses `async-serial` 0.2.0, which imports `std::os::fd` unconditionally, so it
does not build on Windows at all (and `async-io` cannot poll COM ports). On Windows, or with the `blocking-io`
cargo feature (so the same code can be exercised on any OS), the port is instead driven on a thread pool through
`blocking::Unblock`, using **separate cloned handles for reading and writing**. (A single `Unblock` reads ahead in
the background and reports that read's timeout as the error of the next *write*; this was found by testing the
adapter against a real robot on Linux with `--features blocking-io`.) Unix keeps `async-serial` unchanged.
The adapter was hardware-tested on Linux via `blocking-io`. Windows diagnosis exposed a further DTR
requirement covered by patch 0003; see `docs/hardware-notes.md` for the platform-specific evidence.

## Patch 0003: Windows opened the ports but the AIM REPL stayed silent

On Windows 11, the 0.1.0 executable correctly found system COM4 (`MI_00`) and user COM3 (`MI_04`) and opened
both, but received zero bytes during REPL initialization. Power-cycling did not help. A direct serial
comparison with the same 115200/8N1 settings and RTS disabled produced no bytes with DTR low, then a raw
REPL prompt and successful execution as soon as DTR was asserted. Fresh-open comparisons reproduced it.

`serialport` 4.10.1 preserves OS DTR defaults: Linux asserts DTR on open, Windows does not. Its builder's
`dtr_on_open` is best-effort and ignores errors. The blocking adapter now makes a checked
`write_data_terminal_ready(true)` call on every Windows AIM user-port open, **before** cloning read/write
handles. Other ports and Unix behavior are unchanged. Configuration errors retain the port name and source
error; normal ownership cleanup closes a handle when setup fails. Tests cover the DTR requirement, failure
propagation, other-port behavior, and Windows interface metadata independent of COM numbering.

## What patch 0001 changes (all in `vex-v5-serial/src/serial.rs`)

1. **AIM user port.** `types_by_location()` only knew the V5 Brain layout (interface 0 = system, 2 = user). The
   AIM exposes a UVC camera on USB interfaces 2-3, so its serial ports are interfaces **0 and 4**. Interface 4
   used to be dropped as "Unknown location", leaving `SerialDevice::user_port()` empty. It is now recognised as
   the user port for USB PID `0x0700`.
2. **Fallbacks can run.** `types_by_location()` returned `Some(...)` even when it recognised nothing, so the
   name-based fallbacks were never tried. It now returns `None` when nothing was recognised.
3. **No partial writes.** `write_user()` on the user-port path used a single `write()`, which may accept only
   part of the buffer. It now uses `write_all()` + `flush()`.

Discovery and configuration tests: `cargo test -p vex-v5-serial --no-default-features --features serial`.

## Patch 0004: AIM Bluetooth transport groundwork

`0004-aim-bluetooth-transport.patch` additionally repairs the dormant BLE backend.
The AIM advertises `0x0670`, rather than the V5 service UUID; Windows discovery
now finds the actual robot. Scans deduplicate candidates, time out without new
events, and stop scanning on exit. Bluetooth-only builds include `async-io`.

User bytes arrive through notifications, since TXUser is not readable. Separate
bounded user/system buffers preserve partial reads, interleaving and fragmented
or coalesced CDC replies. Writes respect MTU and firmware limits with pacing;
authentication validates lengths and numeric digit bytes, avoids credential
dumps and uses acknowledged writes. Connection setup/authentication have
deadlines and explicit disconnect cleanup is available. `btleplug` is at least
0.13.5, matching the APIs in use; callers must supply a Tokio runtime.

Eight BLE regression tests pass locally on Windows, as do all six USB discovery/
configuration tests together with BLE. The `ble-discover` example found AIM6518
on Windows in an eight-second scan without pairing or writing GATT values.
Those initial discovery tests did not establish authenticated REPL access or
camera support. Subsequent instructor and development CLI checks did: native
640x480 JPEGs work from the home screen, with Python recovery. The 0.2.0-dev CLI
uses this backend; published 0.1.1 is still USB-only. See `docs/bluetooth.md`.

## Patch 0005: validated camera downloads and borrowed transports

The file-read reply decoder discarded its CRC and could subtract from a truncated
length. It now checks the declared frame length and CRC16 before decoding/copying
image bytes. Regression tests corrupt every byte and truncate at every boundary,
and check NACKs and extra bytes. `Connection` also forwards through `&mut C`, so
the generic REPL can borrow a BLE connection while its owner guarantees disconnect
on both success and failure. Neither change adds upload or firmware commands.

## Vendored btleplug 0.13.5: Windows notifications

`btleplug/` is the crates.io 0.13.5 source, upstream commit
`1af8299c291f24fca68dfb6b7ef1b5c0475892e1`. Its own `LICENSE.md` retains the
MIT/Apache-2.0/BSD-3-Clause terms. `btleplug-windows-notifications.patch` records
our changes relative to that source, selected by `[patch.crates-io]`:

- Prefer notifications when both modes are advertised. AIM accepted indications
  but sent zero REPL bytes; a forced-indication Bleak control reproduced it.
  Notify-only, indicate-only and unsupported characteristics retain their modes.
- Retain the Windows throughput request until connection teardown, and close it
  on replacement/teardown. The CLI records actual interval separately from request
  acceptance; its latest native capture took 7.908 s at a measured 15 ms interval.
- Propagate failed GATT service enumeration instead of presenting an empty service
  list as missing firmware characteristics.

The next live Rust doctor, info and native JPEG checks passed after the notification
fix. All 47 active btleplug Windows unit tests passed (three upstream tests remain
ignored), including the new subscription-mode regression. This establishes the
listed Windows behavior, not hardware support on macOS/Linux.

## Provenance and upstreaming

Reproduce the vendored tree: clone upstream, check out the commit above, `git am 0001-*.patch 0002-*.patch`,
then `git apply 0003-windows-aim-dtr.patch 0004-aim-bluetooth-transport.patch 0005-validated-camera-download.patch`,
and compare `packages/vex-v5-serial` and `packages/vex-cdc` with these directories. These changes are small and
self-contained. Submitted upstream:

- [vex-v5-serial #22](https://github.com/vexide/vex-v5-serial/pull/22): earlier AIM USB interface and complete-write fix.
- [vex-v5-serial #23](https://github.com/vexide/vex-v5-serial/pull/23): AIM BLE transport, borrowed connections and validated file-read replies (upstream commit `589cc01`).
- [btleplug #505](https://github.com/deviceplug/btleplug/pull/505): Windows notification preference, preferred-parameter request lifetime and GATT error propagation (upstream commit `ac01379`).

PR #23 ports the BLE/protocol changes without our separate Windows serial adapter
patches; its isolated Bluetooth-only tests pass against unmodified btleplug.
The observed Windows AIM REPL behavior also needs #505. These submissions are
not yet merged or released. When upstream releases equivalent fixes, replace
the corresponding vendored code with released crates.

Hardware evidence for the AIM findings (Linux and Windows x86_64): `docs/hardware-notes.md`.
