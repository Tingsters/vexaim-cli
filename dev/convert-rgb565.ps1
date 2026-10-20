# Decode the known AIM LCD framebuffer locally; no image leaves this machine.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [ValidateRange(1, 4096)][int]$Width = 240,
    [ValidateRange(1, 4096)][int]$Height = 240
)

$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $InputPath).Path
$pixels = [IO.File]::ReadAllBytes($sourcePath)
if ($pixels.Length -ne $Width * $Height * 2) {
    throw 'Framebuffer size does not match the supplied RGB565 dimensions; refusing to guess a format.'
}
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object Drawing.Bitmap($Width, $Height, [Drawing.Imaging.PixelFormat]::Format16bppRgb565)
try {
    $rectangle = New-Object Drawing.Rectangle(0, 0, $Width, $Height)
    $locked = $bitmap.LockBits($rectangle, [Drawing.Imaging.ImageLockMode]::WriteOnly, [Drawing.Imaging.PixelFormat]::Format16bppRgb565)
    try {
        for ($row = 0; $row -lt $Height; $row++) {
            [Runtime.InteropServices.Marshal]::Copy($pixels, $row * $Width * 2, [IntPtr]::Add($locked.Scan0, $row * $locked.Stride), $Width * 2)
        }
    } finally {
        $bitmap.UnlockBits($locked)
    }
    $destinationPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
    $bitmap.Save($destinationPath, [Drawing.Imaging.ImageFormat]::Jpeg)
    Write-Host "Saved local ${Width}x${Height} JPEG: $OutputPath"
} finally {
    $bitmap.Dispose()
}
