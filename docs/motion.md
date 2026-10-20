# Movement helpers and hardware acceptance

Ordinary requests such as "spin in a circle" use finite helpers and a reusable
connection. The helpers need no calibration targets, surface selection or extra
runtime dependencies. Target navigation is a separate future capability.

## Implementation and current limits

The CLI (`0.2.0`) adds persistent Bluetooth sessions and bounded
turn/move helpers. The earlier workshop release `0.1.1` was USB-only. Install the release
bundle's executable and matching skill together; source edits alone do not update
installed agents. The installer copies the complete skill, including
`references/sessions-and-motion.md`, into both supported skill locations.

One process discovers the explicitly named AIM, verifies identity, authenticates,
retains both notification streams and initializes the transient REPL helpers.
Later agent calls use private current-user Windows named pipes or Unix sockets;
there is no network listener, PIN file or agent configuration change. Another
standalone Bluetooth command cannot take over an existing named session.

Starting/reusing a session is an agent task, not a student command. Agent-facing
syntax and PowerShell examples live in the [session reference](../skill/vex-aim/references/sessions-and-motion.md).
The session remains open across prompts; close at actual wrap-up. An idle owner
exits after 30 minutes. Bluetooth does not promise to prevent the robot sleeping.
Cached session status is not a fresh battery or power measurement.

Helpers run finite native movements with polling and `finally` stopping, a maximum
20-second robot-side deadline, and limits of 360 degrees / 500 mm per action.
There is no preliminary 15-degree turn on every student request. Custom Python
remains available for creative compositions; it does not inherit helper limits.

The current default stays **30 DPS**, with explicit developer test options of
60/90 DPS, until independent surface tests support promoting a general default.
Move default is 80 mm/s, within a 40..100 mm/s helper range. These are software
bounds, not evidence that every permitted speed/surface has passed hardware tests.
Normal robot gyro startup initialization is used. No additional calibration or
automatic correction is enabled, and no floor-specific correction is assumed to
transfer to a new surface or robot.

Stop preempts an active operation on the existing connection. The caller receives
confirmation only if Python reports stopped. Connection loss and owner death
cannot guarantee immediate stopping: use the physical switch if necessary.
Busy movements are rejected, never queued. A missing response never triggers
automatic movement replay. Live `info` must confirm stopped state after an
interruption; link failure requires a fresh session after checking power.
Interrupted camera transactions disable further snapshots until close/start,
while a successful live state check can restore ordinary movement.

## Timing and accuracy evidence

Record discovery, connection/authentication, helper preparation, dispatch and
motion separately. The goal for an already connected idle session is dispatch
p95 below one second, excluding model reasoning. `dispatch_ms` ends when the host
receives the robot's command-issued acknowledgement, not an external wheel-motion
measurement. JSON produces a progress event and then a final result; report
completion without waiting for a separate workshop report.

The earlier BLE turn took 14.835 seconds inside the Python execution and reported
-359.84 degrees through the IMU. Each standalone CLI invocation also scanned for
eight seconds and opened a new connection. The student observed the wrong final
direction: IMU agreement is not proof of physical accuracy.

Software tests exercise real private local IPC with a fake robot, ownership
reuse, rejection while busy, priority stop, caller loss, pending-action cancellation,
protocol bounds and the actual Python helper under interruption/stall conditions.
Physical accuracy, faster-speed promotion, radio sleep/reconnect and in-motion
interruption still require real-robot evidence. Cross-platform CI is separate from
hardware acceptance on each OS.

### Developer hardware harness (not workshop preparation)

With the robot awake and already paired, a stationary benchmark makes no movements:

```powershell
uv run --no-project python dev/benchmark-motion.py --tool cli/target/debug/vexaim.exe --name AIM6518 --samples 20 --output dist/warm-session.json
```

Only after physical readiness/supervision is confirmed, a developer can add
`--motion --ready --surface hard-floor`. Repeat on a smooth workshop mat and
low-pile carpet where available. The default five samples cover both directions,
90/180/360 degrees and 30/60/90 DPS. Begin new higher-speed hardware acceptance
with a small supervised movement first; the batch harness is for after that check.
An error stops the batch without replay; the partial report is retained locally.

Measure actual signed, unwrapped turn angles independently, using external video
or a physical angle reference. Do not use the robot's IMU/odometry as ground truth.
Record displacement so a shifted robot cannot masquerade as correct rotation:

```json
{"source":"physical_angle_reference","observations":[
  {"trial":"60-360-0-left","measured_turn_deg":-357,"robot_displaced":false}
]}
```

Evaluate with `--evaluate dist/motion.json --observations dist/observations.json
--output dist/evaluated.json`. An incomplete dataset cannot promote a speed.
Select the fastest speed whose five repeats of every angle/direction are all
within 5 degrees on **all tested surfaces**. Do not claim 5-degree accuracy on
untested floors. If none qualifies, retain the conservative baseline and report
the measured limitation; do not add calibration tasks to the workshop.

## Target-free camera spike

`dev/turn_frames.py` compares local before/after grayscale frames using ORB binary
features, Hamming matching and RANSAC homography with coverage/inlier checks.
It rejects blank scenes, weak/local matches and inconsistent scenes. It can report
image displacement without asking anyone to place a marker. It never issues
robot commands or adjusts movement and does not rewrite/upload images.

```powershell
uv run dev/turn_frames.py dist/before.jpg dist/after.jpg --output dist/alignment.json
```

The optional developer dependency is pinned OpenCV; students do not install it.
Developer motion tests can add `--capture-pairs` to collect extra stationary JPEGs
around 360-degree trials. These downloads are excluded from normal interactions.

**Decision: automatic camera calibration stays disabled.** Image registration
alone does not separate yaw from translation or scene motion; the AIM's native
JPEG intrinsics have not been independently established here. Even identical
images do not prove capture freshness or a full turn. Reports therefore leave
`robot_yaw_error_deg` null and `physical_accuracy_verified` false. Native JPEG
transfers previously took seconds, so they cannot enter the fast movement path.
The existing on-robot detections remain a potential lower-bandwidth option, but
their rate and usefulness on arbitrary untargeted scenes are not established.

Enable a future automatic correction only after independent degree-level tests,
with no placed targets, extra calibration movements or downloads delaying normal
commands. Otherwise retain normal motion control. Keep all photos/reports local.

The prototype was also run on existing local AIM photographs. Controller-to-spinner
frames had no consistent feature matches. Two spinner captures produced 149
inliers, but they covered only 11.3% of the image and were rejected as too localized.
These are useful rejection controls, not turn-calibration or freshness evidence.

Primary references: [VEX motion](https://api.vex.com/aim/home/python/Motion.html),
[inertial initialization](https://api.vex.com/aim/home/python/Inertial.html),
[on-robot vision](https://api.vex.com/aim/home/python/AI_Vision.html),
[OpenCV feature matching](https://docs.opencv.org/4.13.0/dc/dc3/tutorial_py_matcher.html)
and [homography](https://docs.opencv.org/4.13.0/d1/de0/tutorial_py_feature_homography.html).
