# vexaim 0.4.0

Persistent Bluetooth sessions and quicker workshop retries, with the matching
vex-aim skill and installers for Windows, Linux and both Mac architectures.

- `session start --persistent` keeps the background owner across prompts, chats,
  agent application closure and workshop breaks, without the ordinary 30-minute
  idle cutoff. It renews a finite, firmware-gated power lease while alive.
- `--takeover` explicitly stops an existing student program on the selected robot
  before preparing the REPL. Saved programs and firmware are not deleted.
- Degraded sessions report `reconnecting` instead of cached `ready`, rebuild
  closed Bluetooth transports, authenticate the same robot using saved credentials
  and verify stopped state. No interrupted movement is replayed.
- Changed pairing yields `auth_required` and stops background reconnect attempts.
  Explicit close releases the link without forgetting pairing. AIM two-computer
  handoff still needs hardware verification; release the old connection first.
- Windows retains GattSession.MaintainConnection for the owning transport and
  handles closed GATT objects without panicking.
- JSON progress, retained last result, preparation/upload/execution timings and
  delivery certainty make host timeouts and fresh retries easier to diagnose.
  Execution timeout starts after source submission, rather than during upload.
- The shipped Windows pairing bridge keeps the original stdin process alive,
  accepts one code over a current-user pipe and expires abandoned requests. It
  does not save PIN files or require terminal gymnastics from students.

Update with the one-line installer in the README. Install the matching skill and
binary together, close an old-version owner once, then start a fresh agent chat.
Camera photographs remain local. Persistent mode is a background process, not
an OS service; a computer restart requires starting a new session.

Windows controlled-disconnect recovery passed in 7.3 seconds on AIM6518 firmware
1.0.4, with stopped state and power lease restored. Stationary endurance evidence
is recorded in docs/persistent-workshops.md. CI coverage is separate from real
robot verification; no new macOS/Linux radio or two-computer hardware claim is made.
