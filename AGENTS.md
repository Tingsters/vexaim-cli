# Working on vexaim-cli

This is the standalone CLI, generic vex-aim agent skill and distribution project.
Workshop teaching material belongs in Tingsters/vex-aim-agent-workshop.

Read README.md and skill/vex-aim/SKILL.md. Keep command documentation, executable
and bundled skill in the same release. Run the shared CI checks and installer
tests when changing distribution. Use explicit --from-source only for developer
builds; do not add automatic compiler installation or fallback.

Preserve vendored patches and their license/provenance notes. Do not change the
credential-store service or stable session identity merely because this is a
new repository. Tests use simulated radios; never claim CI verifies real hardware.

Do not move a robot during setup. Read the robot skill and obtain physical
readiness before supervised movement. Do not upload local photos, credentials,
logs, build output or .showtail records. No robot firmware or saved projects are
needed. Ask before administrator actions or installing Rust.
