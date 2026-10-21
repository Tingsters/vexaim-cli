# Native VEX AIM commands

Requires the matching 0.3 command release. Use `--json` and `--session ID` before
the command. `catalog [GROUP]` works offline and lists exact positional parameters,
native VEX method names, constants and operation kinds. `capabilities --live`
reports API presence on this firmware; presence is not a hardware test.

```sh
vexaim --session ID forward 20 --units cm
vexaim --session ID back 0.2 --units m
vexaim --session ID strafe left 200 --units mm
vexaim --session ID motion turn-for left 360
vexaim --session ID motion turn-to 90 --velocity 30 --velocity-units dps
vexaim --session ID motion move-for 200 45 --velocity 80 --velocity-units mmps
vexaim --session ID motion move-with-vectors 0 25 20 --duration 2s --no-wait
```

Motion calls the native three-wheel drivetrain API. Robot-relative angles are
0 forward, 90 right, 180 back, 270 left. Vector arguments are forward, rightward,
rotation, each signed percentages −100..100; no host wheel mixer is substituted.
Relative 360° stays a full rotation; `turn-to` is native absolute-heading behavior.
Defaults remain 80 mm/s and 30 degrees/s. Explicit velocity needs explicit units;
native ranges are up to 200 mm/s, 150 degrees/s or 100 percent. Those ranges are
API limits, not evidence of physical accuracy on every surface. Session velocity
setters apply to subsequent operations unless explicitly overridden.

`motion spin-wheels W1 W2 W3 --duration 1s --experimental` is for developer
verification of wheel order, signs and units. Prefer native vector/move methods
for student requests. Motion/reference/calibration conflicts fail without queueing.
Distance has no 500 mm cap; deadlines still bound travel. Native action timeout
defaults to 30 seconds, configurable 1..120. Continuous actions require duration.

Finite motion waits by default. `--no-wait` needs an owned session and returns
an action ID while the transient robot helper continues. Use `actions list`,
`actions status ID`, `actions wait ID`, or `actions cancel ID`. Read status until
terminal completion after cancellation. Sensors, lights and sound can run during
background motion. `stop` cancels helpers, stops wheels/sound and confirms stopped
state for at most one second. Helpers have private robot timers, independent of
`timer reset`. Closing the session stops movement. If a foreground client loses
its connection during a status-poll gap, the robot-side deadline remains the
bound; do not claim a guaranteed immediate stop. Never replay uncertain movement.

Other command groups:

| Group | Examples and conventions |
| --- | --- |
| robot / battery | name, battery, stopped, pose, set-xy-position; battery voltage/current/status are firmware-gated extensions |
| inertial | heading/rotation/roll/pitch/yaw, orientation, acceleration, turn rate, calibration, reference resets, crash sensitivity/data |
| vision | get-data TARGET COUNT, snapshots, count/largest object, tag/model/color toggles, AWB/overlays, color/code descriptions |
| cargo | has-any-barrel, has-orange-barrel, has-blue-barrel, has-sports-ball |
| kicker | kick soft/medium/hard, place; physical clearance and advance announcement required |
| led | on/off/set-light-color; LED1..LED6, comma lists, ALL_LEDS; named VEX colors, `#RRGGBB`, `R,G,B`; readback where supported |
| screen | text/cursor/font/origin/pen/fill/clipping, drawing, IMAGE1..10, touch, emoji, AI Vision display |
| sound | builtin effect + volume, SOUND1..10, note + duration + volume, active/stop |
| controller | `Onestick`, axes position/value, buttons, connection/battery; never construct a V5 Controller |
| link | connection, message-available, send-message TEXT '[1,2]', get-message/get-message-and-data; two AIMs prelinked in Settings required |
| timer | time/value/reset/clear/system/system-high-res |
| events | watch source --duration 2s; bounded callback buffer with dropped count |
| macro | all 20 named toolbox behaviors, adapted with finite deadlines; these may move, emotions included |

`screen screenshot lcd.png` is a separate host operation that downloads the
240×240 RGB565 LCD buffer and atomically saves a PNG, with `source` labeling it
as LCD content and a postcapture `control_ready` check. It requires a session and
stopped wheels. It is not a camera observation, and never changes display modes.

Read sources can be sampled with `--duration 2s --sample-ms 100` (50..60000 ms,
at most 256 samples). Use global `--jsonl` to emit one sample/callback per line
and a final result with counts instead of repeating arrays.
`events watch screen.pressed --duration 5s --no-wait`
retains its own action and bounded event buffer; callbacks are disabled after
the watch. Inspect action output for events and dropped count. `events watch
timer.event --duration 2s` schedules one midpoint timer callback. Use Python for
custom event composition, loops, functions, VEX `Thread`, and `Timer.event`.

Vision targets include SPORTS_BALL, ORANGE_BARREL, BLUE_BARREL, AIM_ROBOT,
ALL_AIOBJS, ALL_TAGS, `tag:N`, `color:1..7`, `code:1..8`. Define color signatures
before codes. Counts are 1..24; empty results are valid. All 12 native object
properties are serialized, including `exists`; do not index an empty list.

Asset commands use `assets image|sound list|upload|download|delete SLOT`.
Use `--file ABSOLUTE_PATH` for upload and `--output ABSOLUTE_PATH` for download.
Images must decode as PNG and be at most 10 MiB; MP3s at most 50 KiB and 10 seconds.
Existing uploads need `--replace`. Only AIM image/sound vendors are addressable;
program/firmware vendors, format and run-after-upload are excluded. Filenames
must come from native slot constants. Numeric/absent mappings are unsupported.
Upload encoding remains gated until verified against official output; use the
official uploader for those firmware versions. Never describe a rejected upload
as success. Directory reads, playback and display are separate capabilities.

`--emit-python` prints standalone VEX Python for catalogue operations without
connecting. Camera/IPC/assets are host operations and have no equivalent VEX
method. `exec -f file.py --input ANSWER` (repeat for multiple prompts) supplies
explicit answers to Python `input()`; insufficient answers fail and the original
input function is restored. Do not put credentials in command arguments.
