# Compose native vision behaviors

Requires vexaim **0.5.0** and its matching skill. These CLI helpers use native
VEX APIs; they are not additional firmware methods on `robot`.

```sh
vexaim --json --session ID exec --behaviors --timeout 60 -f activity.py
```

Allow the outer agent tool at least execution timeout plus 60 seconds (150
seconds is suitable here). Reuse the persistent session and supplied Robot.

```python
behaviors.configure(move_mmps=150, turn_dps=45, contact_mmps=200,
                    timeout_ms=30000)
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

- `configure(move_mmps=80, turn_dps=30, contact_mmps=None, timeout_ms=30000)`:
  call before the first behavior. Contact defaults to move speed. Native limits
  are 200 MMPS and 150 DPS. The shared timeout cannot exceed CLI execution time.
- `find(target, direction=RIGHT)`: locate a kit object or tag, then face its
  bearing. At most one 360-degree sweep or 15 seconds, plus the shared deadline.
- `collect(cargo)`: find, align, approach, make magnetic contact and verify
  retention. Supports `BLUE_BARREL`, `ORANGE_BARREL`, `SPORTS_BALL`. Already-held
  requested cargo is accepted; other cargo fails explicitly. One local contact
  retry is allowed, without restarting a full-circle search.
- `approach(target)`: find and approach an AprilTag or `AIM_ROBOT`. Visual
  stand-offs follow VEX: width 60 for tags, 140 for AIM, in native 320x240
  coordinates. These are not calibrated millimeter distances.
- `deliver(cargo, tag)`: require the specified cargo already held, approach an
  individual `TAG0`–`TAG37`, place, back away and verify release. No automatic
  collection of missing cargo and no added celebration.

Each helper returns a small evidence dictionary. Failure raises an exception,
stops wheels and prevents later lines from claiming success. Include native
effects freely. Custom motion loops still need their own finite bounds: the
watchdog does not rewrite arbitrary Python or prevent a later raw native command.

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
