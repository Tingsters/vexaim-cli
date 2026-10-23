# vexaim 0.4.1

Windows Bluetooth connections now keep the operating system's connection
parameters instead of holding a ThroughputOptimized request for the whole
workshop. This addresses the policy that reproduced USB-radio resets in the
Windows comparison. Persistent ownership, automatic recovery and the AIM power
lease continue to operate. Other operating systems retain their existing policy.

The Windows pairing helper now accepts the PowerShell object pipeline shown in
the skill, as well as native process stdin. Codes still travel only over stdin
and a current-user pipe; no code parameter, PIN file or student terminal is needed.
Regression checks cover exact-code delivery in Windows PowerShell and PowerShell 7.

Native camera/LCD downloads now have ordered, finite transfer/actor/client
deadlines suitable for the stable Windows link rate. The previous 55-second LCD
limit failed on the tested radio; its corrected recheck passed. Allow 360 seconds
for an agent shell capture call. Motion and Python execution limits are unchanged.

The matching skill explains setup-only unattended testing and distinguishes
computer USB charging from a Bluetooth-only connection. Developer diagnostics
record negotiated parameters and Windows metadata, preserve failed comparisons,
and clean up their own test processes without changing Windows drivers or power
settings. These diagnostics are separate from normal student commands.

Windows acceptance on AIM9E18 firmware 1.0.4 recorded 60 uninterrupted minutes
with zero disconnects or radio resets. A same-executable throughput control
reproduced a radio reset and 20-second outage. The original full report retains
its final LCD-timeout failure; a separate corrected capture/display/stop recheck
passed. The CI-built Windows package passed connection/camera/stop/cleanup, and
the stationary OS-default recovery fixture recovered in 10.1 seconds.

On this radio a ~21 KiB camera frame takes ~36 seconds and an LCD download about
three minutes. Prefer native on-robot AI Vision for fast steering. Other radios,
macOS/Linux hardware and second-computer handoff are not newly certified. See
docs/windows-bluetooth-investigation.md for the distinct builds and test scopes.
