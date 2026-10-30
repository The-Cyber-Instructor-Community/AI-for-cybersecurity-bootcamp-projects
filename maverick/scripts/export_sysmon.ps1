# Export Sysmon process-creation events (Event ID 1) to JSON lines for the lab.
# Run INSIDE the Windows VM, in an elevated PowerShell, after your Atomic Red Team tests.
#   .\export_sysmon.ps1 -Minutes 60 -OutFile C:\lab\sysmon.jsonl
param(
    [int]$Minutes = 60,
    [string]$OutFile = "C:\lab\sysmon.jsonl"
)
$since = (Get-Date).AddMinutes(-$Minutes)
New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
$events = Get-WinEvent -FilterHashtable @{
    LogName   = 'Microsoft-Windows-Sysmon/Operational'
    Id        = 1
    StartTime = $since
} -ErrorAction Stop
$lines = foreach ($e in $events) {
    $xml = [xml]$e.ToXml()
    $row = [ordered]@{ EventID = $e.Id; Computer = $e.MachineName }
    foreach ($d in $xml.Event.EventData.Data) { $row[$d.Name] = $d.'#text' }
    # UtcTime from Sysmon is "yyyy-MM-dd HH:mm:ss.fff" in UTC
    $row['UtcTime'] = ([datetime]$row['UtcTime']).ToString("yyyy-MM-ddTHH:mm:ss.fff") + "+00:00"
    ($row | ConvertTo-Json -Compress)
}
$lines | Set-Content -Path $OutFile -Encoding UTF8
Write-Host "Wrote $($lines.Count) events to $OutFile"
