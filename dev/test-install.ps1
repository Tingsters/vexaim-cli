<# Installer regression tests; no robot, administrator access, or Pester required.
   Run in both Windows PowerShell 5.1 and PowerShell 7:
   ./dev/test-install.ps1 -AssetsDir ./dist
   Requires Rust only to build the deliberately obsolete/malformed test binary. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AssetsDir)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$assets = (Resolve-Path -LiteralPath $AssetsDir).Path
$workRoot = Join-Path $repo 'cli/target/installer-tests'
$work = Join-Path $workRoot ([guid]::NewGuid().ToString('N'))
$shellExe = (Get-Process -Id $PID).Path
$installer = Join-Path $repo 'install.ps1'
$archive = 'vexaim-windows-x86_64.zip'
$passed = 0
New-Item -ItemType Directory -Path $work -Force | Out-Null

function Assert-True([bool]$condition, [string]$description) {
  if (-not $condition) { throw "FAIL: $description" }
  $script:passed++
  Write-Host "PASS: $description"
}

function Invoke-Install([string]$destination, [string[]]$options, [string]$failure = '') {
  $previous = $ErrorActionPreference
  try {
    # PowerShell 5.1 turns redirected native stderr into ErrorRecords. Inspect
    # the child's exit status ourselves, including intentional failure cases.
    $ErrorActionPreference = 'Continue'
    $output = & $shellExe -NoProfile -ExecutionPolicy Bypass -File $installer -TargetHome $destination @options 2>&1
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $previous }
  if ($failure) {
    Assert-True ($code -ne 0 -and ($output -join "`n") -match $failure) "refused: $failure"
  } else {
    if ($code -ne 0) { throw "installer failed: $($output -join "`n")" }
  }
}

function Make-FixtureAssets([string]$directory) {
  New-Item -ItemType Directory -Path $directory -Force | Out-Null
  $payload = Join-Path $work 'fixture bundle'
  New-Item -ItemType Directory -Path $payload -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $work 'vexaim.exe') -Destination $payload -Force
  Copy-Item -LiteralPath (Join-Path $repo 'skill') -Destination $payload -Recurse -Force
  '0.2.0-dev' | Set-Content -LiteralPath (Join-Path $payload 'VERSION') -Encoding ASCII
  Compress-Archive -Path (Join-Path $payload '*') -DestinationPath (Join-Path $directory $archive) -Force
  $hash = (Get-FileHash -LiteralPath (Join-Path $directory $archive) -Algorithm SHA256).Hash.ToLower()
  "$hash  $archive" | Set-Content -LiteralPath (Join-Path $directory 'SHA256SUMS') -Encoding ASCII
}

try {
  $allHome = Join-Path $work 'all agents'
  New-Item -ItemType Directory -Path $allHome | Out-Null
  Invoke-Install $allHome @('-FromDir', $assets, '-DryRun')
  Assert-True (@(Get-ChildItem -LiteralPath $allHome -Force).Count -eq 0) 'dry run writes nothing'
  Invoke-Install $allHome @('-FromDir', $assets, '-NoDoctor')
  foreach ($agent in @('.agents', '.claude')) {
    $skill = Join-Path $allHome "$agent/skills/vex-aim"
    Assert-True ((Test-Path "$skill/bin/vexaim.exe") -and (Test-Path "$skill/SKILL.md")) "installed $agent skill and executable"
    Assert-True ((Test-Path "$skill/references/sessions-and-motion.md") -and (Select-String -LiteralPath "$skill/SKILL.md" -SimpleMatch 'references/sessions-and-motion.md' -Quiet)) "installed $agent prompt/session guidance with the tool"
    Assert-True ((Test-Path "$skill/LICENSE") -and (Test-Path "$skill/licenses/btleplug-LICENSE.md")) "installed $agent distribution notices"
    $version = & "$skill/bin/vexaim.exe" --version
    Assert-True ($LASTEXITCODE -eq 0 -and "$version" -match '^vexaim (\d+\.\d+\.\d+)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$' -and [version]$Matches[1] -ge [version]'0.2.0') "packaged executable runs for $agent"
  }
  Invoke-Install $allHome @('-FromDir', $assets, '-NoDoctor')
  Assert-True (Test-Path "$allHome/.agents/skills/vex-aim/.vexaim-installed") 'upgrade is idempotent'

  $singleHome = Join-Path $work 'single'
  Invoke-Install $singleHome @('-FromDir', $assets, '-Agents', 'claude', '-NoDoctor')
  Assert-True ((Test-Path "$singleHome/.claude/skills/vex-aim") -and -not (Test-Path "$singleHome/.agents")) 'single-agent selection'
  $streamedHome = Join-Path $work 'streamed home'
  & ([scriptblock]::Create((Get-Content -Raw $installer))) -TargetHome $streamedHome
  Assert-True ((Test-Path "$streamedHome/.agents/skills/vex-aim/bin/vexaim.exe") -and (Test-Path "$streamedHome/.claude/skills/vex-aim/SKILL.md")) 'streamed PowerShell installs without a script directory'

  $extracted = Join-Path $work 'standalone bundle'
  Expand-Archive -LiteralPath (Join-Path $assets $archive) -DestinationPath $extracted
  $offlineHome = Join-Path $work 'offline standalone'
  & $shellExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $extracted 'install.ps1') -TargetHome $offlineHome -Agents codex
  Assert-True ($LASTEXITCODE -eq 0 -and (Test-Path "$offlineHome/.agents/skills/vex-aim/bin/vexaim.exe")) 'extracted bundle installs offline without a checkout'
  Assert-True (Test-Path "$offlineHome/.agents/skills/vex-aim/references/sessions-and-motion.md") 'offline bundle includes its matching skill references'

  $badAssets = Join-Path $work 'bad-checksum'
  New-Item -ItemType Directory -Path $badAssets | Out-Null
  Copy-Item -LiteralPath (Join-Path $assets $archive), (Join-Path $assets 'SHA256SUMS') -Destination $badAssets
  $stream = [IO.File]::OpenWrite((Join-Path $badAssets $archive))
  try { $null = $stream.Seek(0, [IO.SeekOrigin]::End); $stream.WriteByte(42) } finally { $stream.Dispose() }
  $rejectedHome = Join-Path $work 'rejected'
  Invoke-Install $rejectedHome @('-FromDir', $badAssets, '-NoDoctor') 'checksum mismatch'
  Assert-True (-not (Test-Path $rejectedHome)) 'checksum failure writes no skill folders'
  Copy-Item -LiteralPath (Join-Path $assets $archive) -Destination $badAssets -Force
  '' | Set-Content -LiteralPath (Join-Path $badAssets 'SHA256SUMS')
  Invoke-Install $rejectedHome @('-FromDir', $badAssets, '-NoDoctor') 'not listed in SHA256SUMS'

  & rustc (Join-Path $PSScriptRoot 'installer-fixture.rs') -o (Join-Path $work 'vexaim.exe')
  if ($LASTEXITCODE -ne 0) { throw 'could not build the installer failure fixture' }
  $oldAssets = Join-Path $work 'old-version'
  Make-FixtureAssets $oldAssets
  $installedExe = Join-Path $allHome '.agents/skills/vex-aim/bin/vexaim.exe'
  $before = (Get-FileHash -LiteralPath $installedExe).Hash
  Invoke-Install $allHome @('-FromDir', $oldAssets, '-NoDoctor') '0.2.0 or newer is required'
  Assert-True ((Get-FileHash -LiteralPath $installedExe).Hash -eq $before) 'obsolete release preserves installed executable'
  $env:VEXAIM_FIXTURE_VERSION = 'not-a-version'
  Invoke-Install $rejectedHome @('-FromDir', $oldAssets, '-NoDoctor') 'did not return a supported version'
  $env:VEXAIM_FIXTURE_VERSION = '0.1.1'
  $env:VEXAIM_FIXTURE_FAIL = '1'
  Invoke-Install $rejectedHome @('-FromDir', $oldAssets, '-NoDoctor') 'did not return a supported version'
  Remove-Item Env:VEXAIM_FIXTURE_VERSION, Env:VEXAIM_FIXTURE_FAIL

  $env:VEXAIM_FIXTURE_VERSION = '0.2.0-dev'
  $developmentHome = Join-Path $work 'development'
  Invoke-Install $developmentHome @('-FromDir', $oldAssets, '-Agents', 'codex', '-NoDoctor')
  Assert-True (Test-Path "$developmentHome/.agents/skills/vex-aim/bin/vexaim.exe") 'development SemVer is accepted'
  $env:VEXAIM_FIXTURE_VERSION = '0.2.1'
  Invoke-Install $allHome @('-FromDir', $oldAssets, '-NoDoctor') 'release version mismatch'
  Assert-True ((Get-FileHash -LiteralPath $installedExe).Hash -eq $before) 'version mismatch preserves installed executable'
  Invoke-Install $allHome @('-FromDir', $assets, '-Version', '0.2.99') 'release version mismatch'
  Invoke-Install $rejectedHome @('-BaseUrl', 'http://127.0.0.1:9') 'download failed'
  $env:VEXAIM_FIXTURE_VERSION = '0.1.0-dev'
  Invoke-Install $allHome @('-FromDir', $oldAssets, '-NoDoctor') '0.2.0 or newer is required'
  Remove-Item Env:VEXAIM_FIXTURE_VERSION

  $incomplete = Join-Path $work 'incomplete'
  New-Item -ItemType Directory -Path $incomplete | Out-Null
  Compress-Archive -LiteralPath (Join-Path $work 'vexaim.exe') -DestinationPath (Join-Path $incomplete $archive)
  $hash = (Get-FileHash -LiteralPath (Join-Path $incomplete $archive)).Hash.ToLower()
  "$hash  $archive" | Set-Content -LiteralPath (Join-Path $incomplete 'SHA256SUMS') -Encoding ASCII
  Invoke-Install $allHome @('-FromDir', $incomplete) 'incomplete release bundle'
  Assert-True ((Get-FileHash -LiteralPath $installedExe).Hash -eq $before) 'incomplete bundle preserves installed executable'
  $foreignHome = Join-Path $work 'foreign'
  $foreignSkill = Join-Path $foreignHome '.agents/skills/vex-aim'
  New-Item -ItemType Directory -Path $foreignSkill -Force | Out-Null
  'keep' | Set-Content -LiteralPath (Join-Path $foreignSkill 'SKILL.md')
  Invoke-Install $foreignHome @('-FromDir', $assets, '-Agents', 'codex', '-NoDoctor') 'not installed by this script'
  Invoke-Install $foreignHome @('-Uninstall')
  Assert-True ((Get-Content -LiteralPath (Join-Path $foreignSkill 'SKILL.md')) -eq 'keep') 'foreign skill survives install and uninstall'
  New-Item -ItemType Directory -Path "$allHome/.agents/skills/other" -Force | Out-Null
  Invoke-Install $allHome @('-Uninstall')
  Assert-True (-not (Test-Path "$allHome/.agents/skills/vex-aim") -and -not (Test-Path "$allHome/.claude/skills/vex-aim")) 'uninstall removes both installed skills'
  Assert-True (Test-Path "$allHome/.agents/skills/other") 'uninstall preserves unrelated skills'
  Write-Host "$passed assertions passed ($($PSVersionTable.PSVersion))"
} finally {
  Remove-Item Env:VEXAIM_FIXTURE_VERSION, Env:VEXAIM_FIXTURE_FAIL -ErrorAction SilentlyContinue
  $absolute = [IO.Path]::GetFullPath($work)
  $parent = [IO.Path]::GetFullPath($workRoot).TrimEnd('\') + '\'
  if (-not $absolute.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) { throw "unexpected test path: $absolute" }
  Remove-Item -LiteralPath $absolute -Recurse -Force
}
