# Instructor feasibility probe. Students use the published USB tool until the BLE camera gate passes.
[CmdletBinding()]
param(
    [string]$Name = 'AIM6518',
    [string]$Report = 'dist/ble-feasibility.json'
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'This development probe needs uv. It is not part of the student installer.'
}

Write-Host "Bluetooth feasibility check for $Name. The robot will remain stationary."
Write-Host 'Unplug only the robot USB cable, leave the robot switched on, and keep it nearby.'
Read-Host 'When ready, press Enter to request the code on the robot screen' | Out-Null
& uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python dev/ble-feasibility.py --name $Name --pair --report $Report
$probeExitCode = $LASTEXITCODE
Write-Host "Probe exit code: $probeExitCode. Local report: $Report"
Read-Host 'Press Enter to close this window' | Out-Null
exit $probeExitCode
