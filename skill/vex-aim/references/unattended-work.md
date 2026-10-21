# Unattended stationary work

Use this workflow when the user wants to leave a stationary investigation
running. Ordinary short robot requests do not need an alert rehearsal.

Prepare binaries and diagnostics before waking the robot. Gather charge,
power-on/restart, exact robot, requested transport, USB state, competing
applications, controller state and pairing permissions together at the start.
Keep pairing codes in masked local input. State what will run and its duration.

Arrange a distinctive audible cue on the computer while the user is present.
Play a rehearsal and obtain confirmation it is audible from where they will be.
Explain that it means return for one specific action. A sound API returning
success is not confirmation the user heard it. Use available host audio tools;
do not make Python packages, an audio service or changed system volume a student
prerequisite. If the cue cannot be heard, finish only work that needs no later
intervention. The robot's speaker cannot notify someone after power/link loss.

Before requesting later help, checkpoint the run and pause the affected phase.
Write one action and its reason, present it in chat, then play the rehearsed
cue. Repeat at most at 60 and 120 seconds. After ten minutes without a reply,
leave an incomplete report and durable instructions. Continue independent
software work while waiting. Do not assume console attention, treat elapsed
time as agreement, or keep retrying physical recovery indefinitely.

After a reply, verify the physical condition. A failed endurance interval starts
again in a new report; time awaiting the user never counts toward a pass.
Fresh-boot tests need restart confirmation unless a validated boot indicator
proves it. No waiting action is automatically replayed. Acknowledging an alert
does not authorize motion; wheels and kicker still require a person nearby and
fresh physical readiness. Host cues must not generate robot traffic during
quiet measurements. Close owned connections at actual completion.

Maintainers have a Windows developer helper, `dev/attention.py`, in the CLI
source repository. Its three-note rehearsal, explicit acknowledgment, durable
pending action and bounded reminders implement this protocol. It is developer
tooling, not a dependency of the installed robot skill or executable.
