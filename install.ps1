<# Installs vexaim and its matching general-purpose skill; no robot required.
   -Agents all|goose|codex|claude -Version VERSION -FromDir RELEASE_ASSETS
   -FromSource is an explicit developer option requiring an existing Rust toolchain. #>
[CmdletBinding()]
param([string]$Agents='all', [string]$Version='', [string]$FromDir='',
  [string]$BaseUrl='', [string]$TargetHome=$HOME,
  [switch]$FromSource, [switch]$DryRun, [switch]$Uninstall,
  [switch]$NoDoctor, [switch]$Force)
$ErrorActionPreference='Stop'
$Marker='.vexaim-installed'
$Repo='https://github.com/Tingsters/vexaim-cli'
$Archive='vexaim-windows-x86_64.zip'
function Say($m) { Write-Host "==> $m" }
function Valid-Version($v) { return $v -match '^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$' }
function Remove-Within([string]$path,[string]$root) {
  $absolute=[IO.Path]::GetFullPath($path)
  $prefix=[IO.Path]::GetFullPath($root).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
  if (-not $absolute.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw "refusing unexpected removal: $absolute" }
  if (Test-Path -LiteralPath $absolute) { Remove-Item -LiteralPath $absolute -Recurse -Force }
}
$wantDirs=@()
foreach ($a in ($Agents -split ',')) {
  switch ($a.Trim().ToLower()) {
    { $_ -in 'goose','codex' } { $wantDirs+=Join-Path $TargetHome '.agents/skills/vex-aim' }
    'claude' { $wantDirs+=Join-Path $TargetHome '.claude/skills/vex-aim' }
    'all' { $wantDirs+=Join-Path $TargetHome '.agents/skills/vex-aim'; $wantDirs+=Join-Path $TargetHome '.claude/skills/vex-aim' }
    default { throw "unknown agent '$a' (use goose, codex, claude or all)" }
  }
}
$wantDirs=@($wantDirs | Select-Object -Unique)
foreach ($d in $wantDirs) {
  if ((Test-Path -LiteralPath $d) -and (Get-Item -LiteralPath $d -Force).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) { throw "refusing linked skill folder: $d" }
}
if ($Uninstall) {
  foreach ($d in $wantDirs) {
    if (Test-Path -LiteralPath (Join-Path $d $Marker)) {
      if ($DryRun) { Say "would remove $d" } else { Remove-Within $d (Split-Path $d -Parent); Say "removed $d" }
    } elseif (Test-Path -LiteralPath $d) { Say "$d was not installed by this script: left alone" }
  }
  exit 0
}
if ($Version -and -not (Valid-Version $Version)) { throw 'invalid release version' }
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and -not $FromSource) { throw 'no prebuilt binary for this Windows architecture; see source build instructions' }
foreach ($d in $wantDirs) {
  if ((Test-Path -LiteralPath $d) -and -not (Test-Path -LiteralPath (Join-Path $d $Marker)) -and -not $Force) { throw "$d was not installed by this script; move it away or use -Force" }
}
if ($DryRun) { Say "would install matching executable and skill into $($wantDirs -join ', ')"; Say 'dry run: nothing changed'; exit 0 }
$Tmp=Join-Path ([IO.Path]::GetTempPath()) ('vexaim-install-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
  $bundle=$Tmp
  if ($FromSource) {
    if (-not $PSScriptRoot -or -not (Test-Path (Join-Path $PSScriptRoot 'cli/Cargo.toml'))) { throw 'source builds require a repository checkout' }
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw 'cargo not found; source builds require an existing Rust toolchain' }
    & cargo build --locked --release --manifest-path (Join-Path $PSScriptRoot 'cli/Cargo.toml')
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
    Copy-Item (Join-Path $PSScriptRoot 'cli/target/release/vexaim.exe') $Tmp
    Copy-Item (Join-Path $PSScriptRoot 'VERSION') $Tmp
    Copy-Item -Recurse (Join-Path $PSScriptRoot 'skill') $Tmp
    Copy-Item (Join-Path $PSScriptRoot 'LICENSE'),(Join-Path $PSScriptRoot 'NOTICE.md') $Tmp
  } elseif ($PSScriptRoot -and -not $FromDir -and -not $BaseUrl -and (Test-Path (Join-Path $PSScriptRoot 'vexaim.exe'))) {
    $bundle=$PSScriptRoot
  } else {
    $assets=$FromDir
    if (-not $assets) {
      if (-not $BaseUrl) {
        if (-not $Version) {
          try {
            Invoke-WebRequest -UseBasicParsing -Uri "$Repo/releases/latest/download/VERSION" -OutFile (Join-Path $Tmp 'latest')
            $Version=(Get-Content -Raw (Join-Path $Tmp 'latest')).Trim()
          }
          catch { throw 'download failed; retry or use -FromDir with downloaded release assets' }
        }
        if (-not (Valid-Version $Version)) { throw 'invalid release version' }
        $BaseUrl="$Repo/releases/download/v$Version"
      }
      try {
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/$Archive" -OutFile (Join-Path $Tmp $Archive)
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/SHA256SUMS" -OutFile (Join-Path $Tmp 'SHA256SUMS')
      } catch { throw 'download failed; retry or use -FromDir (no automatic source build)' }
      $assets=$Tmp
    }
    $lines=@(Get-Content (Join-Path $assets 'SHA256SUMS') | Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+'+[regex]::Escape($Archive)+'$') })
    if ($lines.Count -ne 1) { throw "$Archive is not listed in SHA256SUMS exactly once" }
    $want=($lines[0] -split '\s+')[0]
    $got=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $assets $Archive)).Hash
    if ($want -ne $got) { throw "checksum mismatch for $Archive; refusing to install" }
    Expand-Archive -LiteralPath (Join-Path $assets $Archive) -DestinationPath $Tmp -Force
  }
  $skill=Join-Path $bundle 'skill/vex-aim'
  if (-not (Test-Path (Join-Path $skill 'SKILL.md')) -or -not (Test-Path (Join-Path $bundle 'VERSION'))) { throw 'incomplete release bundle: missing skill or VERSION' }
  $bundledVersion=(Get-Content -Raw (Join-Path $bundle 'VERSION')).Trim()
  $exe=Join-Path $bundle 'vexaim.exe'
  try { $output=& $exe --version; $code=$LASTEXITCODE } catch { throw 'the vexaim binary cannot run; check Windows download restrictions' }
  if ($code -ne 0 -or "$output" -notmatch '^vexaim (\d+\.\d+\.\d+)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$') { throw "binary did not return a supported version: $output" }
  if ([version]$Matches[1] -lt [version]'0.2.0') { throw 'vexaim 0.2.0 or newer is required' }
  if (-not (Valid-Version $bundledVersion) -or "$output" -ne "vexaim $bundledVersion" -or ($Version -and $Version -ne $bundledVersion)) { throw 'release version mismatch; no skill folders changed' }
  foreach ($d in $wantDirs) {
    $parent=Split-Path $d -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $stage="$d.stage-$([guid]::NewGuid().ToString('N'))"
    $backup="$d.backup-$([guid]::NewGuid().ToString('N'))"
    foreach ($p in @($d,$stage,$backup)) {
      if (-not [IO.Path]::GetFullPath($p).StartsWith([IO.Path]::GetFullPath($parent).TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'unexpected skill move path' }
    }
    $committed=$false
    try {
      Copy-Item -LiteralPath $skill -Destination $stage -Recurse
      New-Item -ItemType Directory -Path (Join-Path $stage 'bin') -Force | Out-Null
      Copy-Item -LiteralPath $exe -Destination (Join-Path $stage 'bin/vexaim.exe')
      foreach ($notice in @('LICENSE','NOTICE.md','licenses')) {
        $noticePath=Join-Path $bundle $notice
        if (Test-Path -LiteralPath $noticePath) { Copy-Item -LiteralPath $noticePath -Destination $stage -Recurse }
      }
      Set-Content -LiteralPath (Join-Path $stage $Marker) -Value "vexaim-cli $bundledVersion" -Encoding ASCII
      if (Test-Path -LiteralPath $d) { Move-Item -LiteralPath $d -Destination $backup }
      try { Move-Item -LiteralPath $stage -Destination $d }
      catch { if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $d }; throw }
      $committed=$true
      Say "installed $bundledVersion executable and skill: $d"
    } finally {
      Remove-Within $stage $parent
      if ($committed) { Remove-Within $backup $parent }
    }
  }
  Say "DONE. Tool: $(Join-Path $wantDirs[0] 'bin/vexaim.exe')"
  Say 'Start a NEW agent session to load vex-aim. Then check readiness using your chosen USB or Bluetooth transport.'
} finally { Remove-Within $Tmp ([IO.Path]::GetTempPath()) }
