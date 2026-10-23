param(
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$StopFile,
    [int]$DurationSeconds = 5500
)
# Read-only, payload-free collection. No driver, power or logging settings change.
$ErrorActionPreference = 'Stop'
$clock = [Diagnostics.Stopwatch]::StartNew()
$started = Get-Date
$utf8 = New-Object Text.UTF8Encoding($false)
function Record($value) {
    $value.utc = [DateTime]::UtcNow.ToString('o')
    $value.monitor_s = [Math]::Round($clock.Elapsed.TotalSeconds, 3)
    [IO.File]::AppendAllText($Output, (($value | ConvertTo-Json -Depth 6 -Compress) + [Environment]::NewLine), $utf8)
}
$lastArrival = @{}
$lastEvent = 0L
$lastHeartbeat = -5
try {
    Record @{event='monitor_started';scope='PnP and System BTHUSB metadata; no HCI/GATT payloads'}
    while ($clock.Elapsed.TotalSeconds -lt $DurationSeconds -and -not (Test-Path -LiteralPath $StopFile)) {
        $radios = @(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object InstanceId -like 'USB\*')
        foreach ($radio in $radios) {
            $arrival = (Get-PnpDeviceProperty -InstanceId $radio.InstanceId -KeyName DEVPKEY_Device_LastArrivalDate -ErrorAction SilentlyContinue).Data
            $problem = (Get-PnpDeviceProperty -InstanceId $radio.InstanceId -KeyName DEVPKEY_Device_ProblemCode -ErrorAction SilentlyContinue).Data
            $key = $radio.InstanceId
            if (-not $lastArrival.ContainsKey($key)) {
                $location = (Get-PnpDeviceProperty -InstanceId $key -KeyName DEVPKEY_Device_LocationPaths -ErrorAction SilentlyContinue).Data
                $driver = (Get-PnpDeviceProperty -InstanceId $key -KeyName DEVPKEY_Device_DriverVersion -ErrorAction SilentlyContinue).Data
                $parent = (Get-PnpDeviceProperty -InstanceId $key -KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue).Data
                $parentName = if ($parent) { (Get-PnpDevice -InstanceId $parent -ErrorAction SilentlyContinue).FriendlyName } else { $null }
                Record @{event='adapter_snapshot';name=$radio.FriendlyName;instance=$key;status=$radio.Status;problem=$problem;arrival=$arrival;location=$location;driver=$driver;parent=$parent;parent_name=$parentName}
            } elseif ($arrival -and $arrival -ne $lastArrival[$key]) {
                Record @{event='adapter_arrival_changed';name=$radio.FriendlyName;instance=$key;previous=$lastArrival[$key];arrival=$arrival}
            }
            $lastArrival[$key] = $arrival
        }
        $events = @(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='BTHUSB';StartTime=$started} -MaxEvents 200 -ErrorAction SilentlyContinue | Where-Object RecordId -gt $lastEvent | Sort-Object RecordId)
        foreach ($entry in $events) {
            Record @{event='bthusb';id=$entry.Id;record_id=$entry.RecordId;event_utc=$entry.TimeCreated.ToUniversalTime().ToString('o');level=$entry.LevelDisplayName}
            $lastEvent = $entry.RecordId
        }
        if ($clock.Elapsed.TotalSeconds - $lastHeartbeat -ge 5) {
            $aimUsb = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object InstanceId -like 'USB\VID_2888&PID_0700*')
            Record @{event='monitor_health';radio_nodes=$radios.Count;aim_usb_present=($aimUsb.Count -gt 0)}
            $lastHeartbeat = $clock.Elapsed.TotalSeconds
        }
        Start-Sleep -Seconds 1
    }
    Record @{event='monitor_finished'}
} catch {
    Record @{event='monitor_failed';error_type=$_.Exception.GetType().Name}
    exit 1
}
