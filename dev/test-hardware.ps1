<# Stationary Windows hardware checks. No actuators or camera are used.
   ./dev/test-hardware.ps1 -Tool ./cli/target/release/vexaim.exe
   Add -ReplugCycles 3 for supervised unplug/replug checks (follow the printed cues).
   Uses only PowerShell 5.1+ and the executable under test. #>
[CmdletBinding()]
param(
  [string]$Tool = (Join-Path $PSScriptRoot '../cli/target/release/vexaim.exe'),
  [ValidateRange(1,10000)][int]$Iterations = 100,
  [ValidateRange(0,20)][int]$ReplugCycles = 0,
  [string]$ReportPath = ''
)
$ErrorActionPreference = 'Stop'
$Tool = (Resolve-Path -LiteralPath $Tool).Path
$checks = [Collections.Generic.List[string]]::new()
$latencies = [Collections.Generic.List[double]]::new()
$reconnectAttempts = [Collections.Generic.List[object]]::new()

function Invoke-Vexaim([string[]]$ToolArgs, [string]$InputCode = '', [int]$ExpectedExit = 0) {
  if ($InputCode) { $output = $InputCode | & $Tool --json @ToolArgs }
  else { $output = & $Tool --json @ToolArgs }
  $code = $LASTEXITCODE
  if ($code -ne $ExpectedExit) { throw "exit $code (expected $ExpectedExit): $($output -join "`n")" }
  return ($output -join "`n" | ConvertFrom-Json)
}

function Check([bool]$condition, [string]$name) {
  if (-not $condition) { throw "FAIL: $name" }
  $checks.Add($name)
  Write-Host "PASS: $name"
}

function Aim-PortCount {
  # CIM serial instances can briefly linger during device removal; query present PnP endpoints.
  return @((Get-PnpDevice -PresentOnly -Class Ports -ErrorAction SilentlyContinue) |
    Where-Object { $_.InstanceId -like '*VID_2888&PID_0700*' -and $_.Status -eq 'OK' }).Count
}

function Wait-Presence([bool]$present, [int]$seconds = 180) {
  $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
  $stableSince = $null
  while ([DateTime]::UtcNow -lt $deadline) {
    $count = Aim-PortCount
    $matches = if ($present) { $count -ge 2 } else { $count -eq 0 }
    if ($matches) {
      if ($null -eq $stableSince) { $stableSince = [DateTime]::UtcNow }
      if (([DateTime]::UtcNow - $stableSince).TotalSeconds -ge 1) { return }
    } else { $stableSince = $null }
    Start-Sleep -Milliseconds 250
  }
  throw "timed out waiting for robot present=$present"
}

$diagnostic = Invoke-Vexaim @('doctor')
Check ($diagnostic.verdict -eq 'ready') 'doctor ready'
$status = Invoke-Vexaim @('info')
$state = $status.stdout | ConvertFrom-Json
Check ($status.ok -and $state.stopped -eq $true -and $state.battery_pct -ge 0) 'info reports battery and stopped state'
$invalid = Invoke-Vexaim @('--device', '9999', 'doctor') -ExpectedExit 1
Check ($invalid.verdict -eq 'not ready' -and @($invalid.checks | Where-Object { $_.check -eq 'device-selection' -and -not $_.ok }).Count -eq 1) 'invalid device cannot report ready'
$reply = Invoke-Vexaim @('exec', "print('PONG42')")
Check ($reply.ok -and $reply.stdout.Trim() -eq 'PONG42') 'one-line execution'
$multiline = "value = 6 * 7`nprint('PONG' + str(value))`n"
$reply = Invoke-Vexaim @('exec', '-') -InputCode $multiline
Check ($reply.ok -and $reply.stdout.Trim() -eq 'PONG42') 'PowerShell multiline stdin'
$testDir = Join-Path $PSScriptRoot '../cli/target/hardware-tests'
New-Item -ItemType Directory -Path $testDir -Force | Out-Null
$testFile = Join-Path $testDir 'program with spaces.py'
$multiline | Set-Content -LiteralPath $testFile -Encoding ASCII
$reply = Invoke-Vexaim @('exec', '-f', $testFile)
Check ($reply.ok -and $reply.stdout.Trim() -eq 'PONG42') 'file execution with spaces in path'
$reply = Invoke-Vexaim @('exec', 'print(1/0)') -ExpectedExit 1
Check (-not $reply.ok -and $reply.stderr -match 'ZeroDivisionError') 'Python error propagation'
$reply = Invoke-Vexaim @('exec', '--timeout', '1', '-') -InputCode "while True:`n    pass`n" -ExpectedExit 1
Check (-not $reply.ok -and $reply.timed_out) 'timeout interrupts Python'
Check ((Invoke-Vexaim @('doctor')).verdict -eq 'ready') 'ready after error and timeout'

for ($i = 1; $i -le $Iterations; $i++) {
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $reply = Invoke-Vexaim @('exec', "print('PONG42')")
  if (-not $reply.ok -or $reply.stdout.Trim() -ne 'PONG42') { throw "round trip $i failed" }
  $latencies.Add($timer.Elapsed.TotalMilliseconds)
  if ($i % 10 -eq 0) { Write-Host "Round trips: $i/$Iterations" }
}
Check ($latencies.Count -eq $Iterations) "$Iterations consecutive round trips"

for ($cycle = 1; $cycle -le $ReplugCycles; $cycle++) {
  Write-Host "Cycle $cycle/${ReplugCycles}: UNPLUG the robot's USB cable now."
  Wait-Presence $false
  $missing = Invoke-Vexaim @('doctor') -ExpectedExit 1
  Check ($missing.verdict -eq 'not ready') "cycle $cycle detects unplugged robot"
  Write-Host "Cycle $cycle/${ReplugCycles}: RECONNECT USB now (leave the robot switched on)."
  Wait-Presence $true
  $ready = $false
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    $raw = & $Tool --json doctor
    $code = $LASTEXITCODE
    $entry = [pscustomobject]@{ cycle=$cycle; attempt=$attempt; exit_code=$code; doctor=($raw -join "`n") }
    $reconnectAttempts.Add($entry)
    # Persist each attempt, including failures, instead of losing evidence on an exception.
    if ($ReportPath) {
      @($reconnectAttempts.ToArray()) | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath ($ReportPath + '.reconnect.json') -Encoding UTF8
    }
    if ($code -ne 0) { Write-Host "Reconnect attempt $attempt failed: $($entry.doctor)" }
    if ($code -eq 0 -and ($raw | ConvertFrom-Json).verdict -eq 'ready') { $ready = $true; break }
    if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
  }
  Check $ready "cycle $cycle ready after replug"
}

$report = [ordered]@{
  version = (& $Tool --version)
  tested_utc = [DateTime]::UtcNow.ToString('o')
  os_version = [Environment]::OSVersion.VersionString
  powershell = $PSVersionTable.PSVersion.ToString()
  doctor = $diagnostic
  battery_pct = $state.battery_pct
  checks = $checks.ToArray()
  roundtrips = $latencies.Count
  mean_ms = [Math]::Round(($latencies | Measure-Object -Average).Average, 1)
  replug_cycles = $ReplugCycles
  reconnect_attempts = $reconnectAttempts.ToArray()
}
$json = $report | ConvertTo-Json -Depth 5
if ($ReportPath) { $json | Set-Content -LiteralPath $ReportPath -Encoding UTF8 }
$json
