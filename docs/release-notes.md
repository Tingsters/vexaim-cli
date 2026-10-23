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

The matching skill explains setup-only unattended testing and distinguishes
computer USB charging from a Bluetooth-only connection. Developer diagnostics
record negotiated parameters and Windows metadata, preserve failed comparisons,
and clean up their own test processes without changing Windows drivers or power
settings. These diagnostics are separate from normal student commands.

Hardware acceptance is in progress. Do not tag this candidate until the
uninterrupted run and camera/display/stop checks are recorded here. See
docs/windows-bluetooth-investigation.md for scope and limitations.
