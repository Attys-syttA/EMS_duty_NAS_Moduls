param(
    [string]$Action = "restart",
    [string]$Reason = "manual_event"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$eventsDir = Join-Path $root "events"
if (-not (Test-Path $eventsDir)) { New-Item -Path $eventsDir -ItemType Directory | Out-Null }
$payload = @{ action = $Action; reason = $Reason } | ConvertTo-Json -Depth 3
$file = Join-Path $eventsDir "watchdog_event.json"
Set-Content -Path $file -Value $payload -Encoding UTF8
Write-Output "Event file written: $file"
