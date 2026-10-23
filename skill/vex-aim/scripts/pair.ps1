param(
  [ValidateSet('Start','Submit','Status','Broker')][string]$Action = 'Start',
  [string]$Name,
  [string]$Directory,
  [ValidateRange(1,120)][int]$WaitSeconds = 120,
  [string]$Tool = (Join-Path $PSScriptRoot '../bin/vexaim.exe')
)
$ErrorActionPreference = 'Stop'

function Quote-Argument([string]$Value) {
  if ($Value.Contains([char]0)) { throw 'Invalid process argument' }
  '"' + ([regex]::Replace($Value, '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}
function Save-State([string]$State, [string]$Message = '') {
  $value = @{state=$State; name=$Name; pipe=$script:pipeName; message=$Message}
  $temp = Join-Path $Directory 'state.new'
  $value | ConvertTo-Json -Compress | Set-Content -LiteralPath $temp -Encoding UTF8
  Move-Item -LiteralPath $temp -Destination (Join-Path $Directory 'state.json') -Force
}

if ($Action -eq 'Start') {
  if (-not $Name) { throw 'Select the exact robot name' }
  if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) { throw 'CLI executable not found' }
  $Tool = (Resolve-Path -LiteralPath $Tool).Path
  $Directory = Join-Path ([IO.Path]::GetTempPath()) ('vexaim-pair-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $Directory | Out-Null
  $script:pipeName = 'vexaim-pair-' + [guid]::NewGuid().ToString('N')
  Save-State 'starting'
  $argsList = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,
      '-Action','Broker','-Name',$Name,'-Directory',$Directory,'-Tool',$Tool,'-WaitSeconds',"$WaitSeconds")
  # Avoid inheriting any of the agent tool's capture handles.
  Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class PairLauncher {
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 public struct SI { public int cb; public string reserved, desktop, title;
 public int x,y,xsize,ysize,xchars,ychars,fill,flags; public short show,reserved2;
 public IntPtr reservedPtr,input,output,error; }
 [StructLayout(LayoutKind.Sequential)]
 public struct PI { public IntPtr process,thread; public int pid,tid; }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
 static extern bool CreateProcess(string app,StringBuilder command,IntPtr pa,IntPtr ta,
 bool inherit,int flags,IntPtr env,string cwd,ref SI si,out PI pi);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 public static int Start(string executable,string command) {
  var si=new SI(); si.cb=Marshal.SizeOf(typeof(SI)); PI pi;
  if(!CreateProcess(executable,new StringBuilder(command),IntPtr.Zero,IntPtr.Zero,
      false,0x08000000,IntPtr.Zero,null,ref si,out pi))
    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  CloseHandle(pi.thread); CloseHandle(pi.process); return pi.pid;
 }
}
'@
  $powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
  $command = (Quote-Argument $powershell) + ' ' + (($argsList | ForEach-Object { Quote-Argument $_ }) -join ' ')
  $helperPid = [PairLauncher]::Start($powershell, $command)
  @{directory=$Directory; helper_pid=$helperPid; state='starting'; expires_in_seconds=$WaitSeconds} |
    ConvertTo-Json -Compress
  exit
}
if (-not $Directory -or -not (Test-Path -LiteralPath (Join-Path $Directory 'state.json'))) {
  throw 'Unknown pairing helper directory'
}
$state = Get-Content -LiteralPath (Join-Path $Directory 'state.json') -Raw | ConvertFrom-Json
$script:pipeName = $state.pipe
if ($Action -eq 'Status') { $state | ConvertTo-Json -Compress; exit }
if ($Action -eq 'Submit') {
  # The code is only stdin data, never a parameter, file, output or exception.
  $code = [Console]::In.ReadLine()
  if ($null -eq $code -or $code -notmatch '^\d{4}$') { throw 'Supply exactly four digits on stdin' }
  $client = New-Object IO.Pipes.NamedPipeClientStream('.', $script:pipeName, [IO.Pipes.PipeDirection]::Out)
  try {
    $client.Connect(5000)
    $writer = New-Object IO.StreamWriter($client)
    $writer.WriteLine($code)
    $writer.Flush()
    $code = $null
    @{submitted=$true} | ConvertTo-Json -Compress
  } finally { $client.Dispose() }
  exit
}

# Broker runs in Windows PowerShell 5.1 so pipe ACLs work on every supported Windows install.
$server = $null
$process = $null
try {
  $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $security = New-Object IO.Pipes.PipeSecurity
  $security.SetAccessRuleProtection($true, $false)
  $security.AddAccessRule((New-Object IO.Pipes.PipeAccessRule($sid, 'FullControl', 'Allow')))
  $server = New-Object IO.Pipes.NamedPipeServerStream($script:pipeName,
    [IO.Pipes.PipeDirection]::In, 1, [IO.Pipes.PipeTransmissionMode]::Byte,
    [IO.Pipes.PipeOptions]::Asynchronous, 4096, 4096, $security)
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $Tool
  $start.Arguments = ((@('--name',$Name,'bluetooth','pair','--code-stdin') |
    ForEach-Object { Quote-Argument $_ }) -join ' ')
  $start.UseShellExecute = $false
  $start.CreateNoWindow = $true
  $start.RedirectStandardInput = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $start
  if (-not $process.Start()) { throw 'Unable to start pairing' }
  $stdout = $process.StandardOutput.ReadToEndAsync()
  $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
  # Signal readiness only after the CLI requested the LCD code, not while it is
  # still discovering the robot. Never persist arbitrary child output.
  while ($true) {
    $line = $process.StandardError.ReadLineAsync()
    while (-not $line.Wait(100)) {
      if ($process.HasExited -or [DateTime]::UtcNow -ge $deadline) { throw 'Pairing request timed out' }
    }
    if ($null -eq $line.Result) { throw 'Pairing exited before requesting a code' }
    if ($line.Result.StartsWith('Read the four-digit code on the selected robot')) { break }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'Pairing request timed out' }
  }
  $stderr = $process.StandardError.ReadToEndAsync()
  Save-State 'waiting' 'Watch the selected robot for its code, then submit through stdin.'
  $pending = $server.BeginWaitForConnection($null, $null)
  while (-not $pending.AsyncWaitHandle.WaitOne(100)) {
    if ($process.HasExited) { throw 'Pairing exited before a code was submitted' }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'Pairing input timed out' }
  }
  $server.EndWaitForConnection($pending)
  $reader = New-Object IO.StreamReader($server)
  $reading = $reader.ReadLineAsync()
  if (-not $reading.Wait(5000)) { throw 'Pairing input timed out' }
  $code = $reading.Result
  if ($null -eq $code -or $code -notmatch '^\d{4}$') { throw 'Invalid pairing input' }
  $process.StandardInput.WriteLine($code)
  $process.StandardInput.Close()
  $code = $null
  Save-State 'authenticating'
  if (-not $process.WaitForExit(30000)) { throw 'Pairing completion timed out' }
  if ($process.ExitCode -ne 0) { throw 'Pairing failed; start a fresh request and code' }
  Save-State 'paired' 'Credential saved by the CLI in the native OS store.'
} catch {
  # Do not persist raw subprocess streams or arbitrary exception data containing input.
  Save-State 'failed' 'Pairing failed or timed out; start a fresh request and code.'
} finally {
  if ($null -ne $server) { $server.Dispose() }
  if ($null -ne $process) {
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    $process.Dispose()
  }
}
