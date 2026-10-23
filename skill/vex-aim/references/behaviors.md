# Compose native vision behaviors

Requires vexaim **0.5.2** and its matching skill. These CLI helpers use native
VEX APIs; they are not additional firmware methods on `robot`.

```sh
vexaim --json --session ID exec --behaviors --timeout 60 -f activity.py
```

Allow the outer agent tool at least execution timeout plus 60 seconds (150
seconds is suitable here). Reuse the persistent session and supplied Robot.

```python
behaviors.configure(move_mmps=150, turn_dps=45, contact_mmps=200,
                    timeout_ms=30000, tag_turn_dps=90, verification="contact")
behaviors.collect(ORANGE_BARREL)
behaviors.deliver(ORANGE_BARREL, TAG0)
robot.screen.show_emoji(HAPPY)
```

The implementation is cached once per transient interpreter, including after
display/stop recovery. Each call gets a fresh activity, shared helper deadline
and final wheel stop. No source concatenation, host Python installation, saved
project or second Robot is needed. Do not import or construct `behaviors`.
Ordinary `exec` is unchanged.

## Interface

- `configure(move_mmps=80, turn_dps=30, contact_mmps=None, timeout_ms=30000,
  verification="vision", tag_turn_dps=None)`:
  call before the first behavior. Contact defaults to move speed. Native limits
  are 200 MMPS and 150 DPS. Tag-turn speed defaults to `turn_dps`; use 90 for
  brisk travel between stationary views. The shared timeout cannot exceed CLI
  execution time. `vision` retains diagnostic possession/retention/release
  checks. `contact` opts into assume-and-continue play as described below.
- `find(target, direction=RIGHT)`: locate a kit object or tag, then face its
  bearing. Cargo uses one sweep bounded by 15 seconds and the shared deadline.
  Tags use up to eight stationary views, 45 degrees apart, with brief settling
  and native reads. The shared deadline still applies. No host images are used.
- `collect(cargo)`: find, align, approach and make magnetic contact; vision
  mode also verifies retention. Supports `BLUE_BARREL`, `ORANGE_BARREL`, `SPORTS_BALL`. Already-held
  requested cargo is accepted; other cargo fails explicitly. One local contact
  retry is allowed, without restarting a full-circle search.
- `approach(target)`: find and approach an AprilTag or `AIM_ROBOT`. Visual
  stand-offs follow VEX: width 60 for tags, 140 for AIM, in native 320x240
  coordinates. Arrival uses the acquisition observation immediately when it
  already meets that stand-off; no duplicate detection is required. These are
  not calibrated millimeter distances.
- `deliver(cargo, tag)`: require held cargo or the same contact-mode activity's
  preceding pickup, approach an individual `TAG0`–`TAG37`, place and back away.
  Vision mode verifies release. No automatic
  collection of missing cargo and no added celebration.

Each helper returns a small evidence dictionary. Failure raises an exception,
stops wheels and prevents later lines from claiming success. Include native
effects freely. Custom motion loops still need their own finite bounds: the
watchdog does not rewrite arbitrary Python or prevent a later raw native command.

## Contact-based play

Set `verification="contact"` when the task favors a brisk attempt over diagnostic
confirmation. After selecting and aligning with actual nearby cargo, the helper
finishes one bounded contact stroke and continues without the retention reverse,
repeat-contact cycle or possession-loss gates during delivery. A contact stroke
may finish at its local time limit against a pen wall, with stop confirmed.
Cancellation, SDK errors, unconfirmed stop and the whole-activity deadline still
fail. Missing cargo/markers are never invented.

This policy remembers attempted cargo within the same activity. A standalone
`deliver` still requires native possession if no preceding `collect` selected
that cargo. Placement uses `robot.kicker.place()` and backs away to separate the
magnet. It does not launch the object with `kick`.

`completed: true` means the requested helper sequence finished. `collected` or
`delivered` is true only with native evidence, and null when completion was
assumed (`evidence: contact_assumed` or `place_assumed`). Those nulls are expected
play outcomes, not errors requiring a camera check or another agent turn. Effects
can follow directly. Report routine completion without claiming independent
physical verification. For explicit tests use the default `verification="vision"`.

Version 0.5.2 also accepts `near_marker_assumed` as a completed play outcome.
After a tag was read within two seconds, faced within 12 degrees and seen at
least 45 pixels wide (75% of the 60-pixel stand-off), its loss during final
approach can mean close-range occlusion. The helper stops the existing approach
and continues to placement instead of turning away or requiring an agent turn.
It adds no further forward movement after accepting that arrival. A distant,
unaligned or stale marker still follows ordinary bounded recovery.

Delivery includes `arrival_evidence` and `release_confirmed`; `delivered` is null
when destination arrival was assumed even if native release was confirmed.
`completed: true` remains the normal play completion signal. Diagnostic vision
mode still requires the observed marker-size stand-off.

Use native constants rather than numeric class IDs. For unexported tag aliases,
use `Tagdesc(12)`. `ALL_TAGS` can find any marker but is not a delivery address.
The trained model does not recognize arbitrary objects or people; use the agent
image workflow for those.

## Results and recovery

The existing JSONL progress stream includes behavior phase and robot elapsed
time. The session retains last progress/result. Deadline errors identify the
phase and last native call. Read live `info` when recovery requests it, then
perform fresh authorized work; never replay uncertain motion automatically.

Named search, `macro get-blue-barrel`, `macro get-orange-barrel`,
`macro get-sports-ball` and approach commands use the same controller. Existing
command names, action IDs, cancellation and session velocity settings remain.
Their progress is in action status, preserving native result JSON framing.

Possession is vision evidence, not measured magnetic force. Brief misses are
tolerated; each contact is bounded to 200 mm. Lighting, occlusion and traction
can still prevent completion. Sources: [VEX macros](https://api.vex.com/aim/home/python/Macro.html),
[timer callbacks](https://api.vex.com/aim/home/python/Logic/Timer.html),
[published implementation](https://github.com/VEX-Robotics/AIM_Websocket_Library/blob/main/vex/aim.py),
[lighting discussion](https://github.com/VEX-Robotics/AIM_Websocket_Library/issues/19).
The published client informs the algorithm; this CLI executes on-robot Python
over the selected transport. Hardware evidence is in docs/hardware-notes.md.
