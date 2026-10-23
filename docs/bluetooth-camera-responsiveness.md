# Bluetooth camera responsiveness investigation

The target is to identify an ordinary stationary object initially outside AIM's
camera view and start approaching within 15 seconds of an accepted search request.
All robot communication must use Bluetooth. Warm connection/model timing and
cold startup are reported separately. A kit-object demonstration does not prove
that a controller or another unfamiliar object can be found.

## Evidence before the new hardware comparison

Historical firmware-1.0.0 probe reports recorded 2.594–4.781 second camera captures
at a 15 ms interval and MTU 256. The later firmware-1.0.4 Windows acceptance
recorded about 36 seconds for a ~21 KiB JPEG using the stable OS-default policy
and a reported 60 ms interval. These differ in firmware, implementation, scene
and connection policy; they are not a controlled speed comparison.

The vendored Rust backend checks the pairing characteristic using an uncached
GATT read before each command. A ~21 KiB image needs approximately 100 small file
reads. The new developer comparison measures those authentication reads, GATT
writes, pacing, notifications, setup, per-block latency and validation separately.
The local Windows implementation now uses operation-authorized file reads after
the hardware comparison below. Other platforms retain per-packet checks. The
already-published 0.4.1 binary has not been replaced by these local changes.

Standalone `snap` also retained the old throughput request and a separate
60-second outer capture guard. It now uses the same platform-selected policy and
capture guard as the owner. The normal Windows selection remains OS-default.
The optional `balanced` profile is a diagnostic comparison, not a new default.

## Short unattended hardware runner

Prepare dependencies and binaries **before** requesting charge/power/placement.
Run offline tests first. The one physical setup includes a charged selected AIM,
USB unplugged, VEXcode closed, a clear floor and the arranged test objects.
After live setup verification there are no pairing prompts, restarts or object
rearrangements. An unexpected need for attendance ends that phase as incomplete.

Developer-only dependencies can be installed in an ignored virtual environment:

```powershell
uv venv --python 3.11 .vexaim/camera-env
uv pip install --python .vexaim/camera-env/Scripts/python.exe bleak==3.0.2 keyring==25.7.0 pillow==11.2.1 opencv-python-headless==4.13.0.92
cargo build --locked --release --manifest-path cli/Cargo.toml --features ble-diagnostics
```

Keep a separate copy of the installed release for the control. Only after the
initial physical setup has been confirmed, run:

```powershell
.vexaim/camera-env/Scripts/python.exe dev/ble_camera_benchmark.py --name AIM9E18 --released .vexaim/camera/bin/vexaim-released.exe --candidate .vexaim/camera/bin/vexaim-camera-diagnostic.exe --output-dir .vexaim/camera/NEW-RUN --setup-confirmed
```

The runner checks USB absence through the existing read-only Windows monitor,
requires an initial battery level of at least 90%, and stops below 25%. It reserves
14 minutes for measurements and a final minute for cleanup. It uses one complete
released baseline, an instrumented per-packet control, and up to three operation-
authorized captures. A frame already exceeding the complete search goal shortens
that candidate phase immediately. It compares the independent Python/Bleak reader
under OS-default parameters. If necessary it measures one balanced-profile frame.
An improving OS-default candidate receives one five-minute repeated-capture screen
only when the remaining budget permits it. There are no long repeated idle soaks.
For a brief stationary comparison, `--duration-seconds 420 --initial-minimum-pct 35`
explicitly shortens the run and lowers the initial gate while retaining the 25%
running floor. The actual initial battery is recorded even on a rejected setup;
the earlier failed report remains failed. This avoids requesting a recharge for
a short measurement that already has sufficient battery. Random objects are
acceptable; no particular object arrangement is needed for transport timing.

Diagnostic block deadlines are 1.5 seconds and the inner transfer budget is
60 seconds. A stalled block fails promptly; ordinary student deadlines remain
unchanged. Stop/close are priority requests so cleanup does not wait behind a
stalled capture. Failed cleanup blocks another connection. The private Windows
job contains only investigative children and releases them when the runner exits.
Independent final power restoration remains unverified by the current close API.

The current runner is stationary. It does **not** claim physical search acceptance:
recognition accuracy and native/JPEG field-of-view correspondence must be verified
before enabling movement. `camera_search.seek` exercises the bounded search and
initial 150 mm approach against a supplied adapter; generated tests verify target
behind, absent/ambiguous targets, failures and the whole-search deadline. It reports
an initial approach, not arrival or magnetic collection.

## Read-only authorization and instrumentation

Diagnostic builds accept these environment variables; normal builds ignore them:

- `VEXAIM_DIAGNOSTIC_CAPTURE_AUTH=packet|operation`
- `VEXAIM_DIAGNOSTIC_CAPTURE_BLOCK_MS=500..3000`
- `VEXAIM_DIAGNOSTIC_CAPTURE_TOTAL_MS=1000..240000`
- `VEXAIM_DIAGNOSTIC_CAPTURE_REPORT=ABSOLUTE-LOCAL-JSONL-PATH`
- `VEXAIM_DIAGNOSTIC_CAPTURE_WINDOW=legacy|payload`
- `VEXAIM_DIAGNOSTIC_CAPTURE_PACING=legacy|reply`
- `VEXAIM_DIAGNOSTIC_CONNECTION_PROFILE=os-default|balanced|throughput`

The operation authorization is opaque and bound to a single connection. Only a
typed file-data **read** can use it. Other commands retain their checks. Pairing
is checked again before returning the image; a changed value rejects the result.
Cancellation drops the authorization without leaving a connection-wide bypass.
The library never formats the authorization value. Numeric timing reports contain
no credentials or packet payloads. An interrupted owner capture disables further
captures until a fresh session; no previous image is returned as new evidence.
The developer runner exposes the separate `--capture-window payload` and
`--capture-pacing reply` experiments. Controls retain legacy settings. Neither
experiment changes the production defaults or allows concurrent reads.

## Local recognition alternatives already checked

The pinned Apache-2.0 `IDEA-Research/grounding-dino-tiny` model was evaluated locally
at revision `a2bb814dd30d776dcf7e30523b00659f4f141c71`, using four CPU threads.
On this Ryzen 9 desktop, short-edge 320 input took approximately 0.69–0.77 seconds;
800 input took 3.69–3.72 seconds. It detected the controller and spinner but also
misclassified the spinner as a controller at every tested input size. Adding
competing labels caused a controller/spinner confusion in the opposite direction.
It is **rejected for autonomous steering** on this evidence. No student model
dependency or automatic image upload is introduced.

A local SIFT reference matcher is an alternative for an object the agent has
already identified and cropped. Existing images gave approximately 15–32 ms per
match; a second controller view matched, and controller/spinner cross-negatives
were rejected. Same-image positive controls are not independent generalization
tests. Generated fixtures additionally check translated targets, unrelated texture,
blank references and label binding. This is visual memory, not a new neural class
on AIM, and cannot promise recognition of a never-seen object or indistinguishable
copies. Reference photos and comparisons remain local.

Prefer native AI Vision for supported classes. An agent-confirmed distinctive
color/code can provide fast native feedback for another object, but must be
validated in its scene. A local reference matcher can reduce repeated agent work;
it cannot remove the Bluetooth image-transfer cost. Do not claim a 15-second
arbitrary-object search until capture timing, scene coverage, identification and
physical approach have all passed together.

## 23 October Windows hardware results

The user supplied random objects, rather than a staged target arrangement. No
object repositioning, new pairing code, power cycle or other attendance was
requested after readiness. AIM9E18 reported REV1 / firmware 1.0.4; USB data was
absent throughout the Windows monitor records. The accepted short run began at
58% battery. No wheels or kicker ran.

| Same stationary scene, roughly 27 KiB JPEG | Capture + local file/control result | Inner capture |
| --- | ---: | ---: |
| Published Windows 0.4.1 | 43.563 s | not instrumented |
| Instrumented candidate, per-packet authentication | 45.141 s | 43.142 s |
| Same candidate, operation authentication | 26.656 s | 25.080 s |
| Balanced profile, operation authentication | 28.219 s | 26.400 s |
| OS-default operation repeat | 28.516 s | 26.400 s |

The paired comparison reduced uncached authentication reads from 149 to 16 and
their aggregate duration from 17.375 s to 1.624 s. The remaining checks include
the capture boundaries and ordinary keepalive traffic. Equivalent-sized frame
delivery improved about 41%; the frame bytes differ slightly with sensor noise
and exposure. OS-default was retained because the balanced comparison gave no
benefit. Monitor records show zero radio re-enumerations and no AIM USB data.
Every CLI measurement finished with confirmed stopped state and owner exit;
independent final power restoration remains outside the close API's evidence.

The hardware-tested diagnostic executable was
`5d5342a8f3cc65ad65a7042cfb68d44a40cc35e22b7f7e7120d496e174d205ef`.
Later source changes enable that same operation-auth/legacy-pacing/216-byte path
by default on Windows. The final production build is not a newly hardware-tested
binary. New MTU/negotiated-parameter logging was added after this comparison;
these runs do not establish their exact current values.

The first 90%-charge setup gate ended before capturing; it remains a failed
setup report. It was too restrictive for this brief stationary task, so the
separately labeled seven-minute run accepted an explicit 35% initial minimum
while keeping the 25% running floor. It connected at 58%.

The seven-minute report remains **incomplete**: the independent Python reference
could not locate the existing credential. The later balanced/OS-default follow-up
passed and does not rewrite that failure. The source of the reference problem
was identified offline: Rust keyring uses `username.service`, whereas Python
keyring also searches `username@service`. The developer reader now checks the
exact native targets with an owner-name guard; an offline vault check succeeded,
but the independent live reference was not rerun within the budget.

Official installed VEXcode source treats the advertised read window as payload,
capped at 232 bytes, rather than subtracting another 14 bytes. The reply already
provides flow control for a sequential request. These findings justify bounded
232-byte/reply-pacing experiments, but time left in the physical window was
insufficient for a complete new comparison. Neither optimization is enabled by
default or claimed hardware-verified. The five-minute screen, changed-scene
freshness and physical search/approach were not completed. Original local reports
remain under `.vexaim/camera/hardware-20261023-*` and must not be uploaded.

## Recommendation and remaining limit

The measured bottleneck is this BLE file-transfer/request path and Windows link
configuration, not a demonstrated universal camera or Bluetooth technology
limit. Authentication overhead was fixable; the remaining 25–29 seconds per
image still exceeds the entire 15-second search budget. Multiple downloaded
views cannot meet that goal on this measured configuration. Increasing timeouts,
host-side resizing or a faster language model cannot solve that transfer cost.

Keep supported object search and feedback on AIM. For an unfamiliar object with
a distinctive appearance, the useful next feature is agent-confirmed target
memory: derive and validate native color/code tracking proxies where possible,
then perform the whole search/approach in one finite robot script. Local visual
reference matching can supplement identity checks without repeated model turns.
This is conditional on the proxy actually distinguishing the requested object;
an arbitrary category or indistinguishable copies do not acquire a native class.

General first-time arbitrary-object search within 15 seconds remains **unmet**.
A future BLE-only transport experiment must demonstrate sufficient frame rate
and fresh scene coverage before it can supply that feature. A faster adapter or
short-lived parameter preference is not a certified solution on this evidence.
No new student-facing search command, model installation or unsupported success
claim is added. The actual code fixes, diagnostics and local prototypes are ready
for review; this investigation does not certify new physical movement behavior.
