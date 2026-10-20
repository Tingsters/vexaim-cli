# Notices

This project's own code and documentation are licensed under the Apache License 2.0 (see `LICENSE`).

## Third-party code included in this repository

- **vex-v5-serial** and **vex-cdc** (vexide and contributors), MIT License. Vendored under `cli/vendor/` with
  AIM USB/Bluetooth transport patches (see `cli/vendor/README.md`). License text: `cli/vendor/LICENSE-vex-v5-serial-MIT`.
  Source: https://github.com/vexide/vex-v5-serial

- **btleplug** (deviceplug and contributors), vendored with AIM notification and Windows
  throughput fixes under `cli/vendor/btleplug/`. Its MIT/Apache-2.0/BSD-3-Clause
  notices are retained in `cli/vendor/btleplug/LICENSE.md`.
  Source: https://github.com/deviceplug/btleplug

This project's source was extracted from Tingsters/vex-aim-agent-workshop at
commit bec539dd9a7f9bc934c6443877cff51267ac5698, retaining original attribution.

## Third-party code compiled into the `vexaim` binary (from crates.io, not vendored here)

Pulled in by `cli/Cargo.lock`, each under its own permissive license (MIT/Apache-2.0 and similar), including
`clap`, `serde_json`, `smol`, `serialport`, `async-serial`, and `nokhwa` (camera access). Run `cargo tree` in `cli/`
for the full list.

## Trademarks

VEX, VEX Robotics and VEX AIM are trademarks of their respective owners. This project is independent and is not
affiliated with or endorsed by VEX Robotics.
