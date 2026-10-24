# Stage 2E: optional hourly current-season NBA pregame monitor, PRIVATE.
# -InstallSchedule is explicit: nothing installs itself when source is updated.
# Uses exact same lock as existing score/daily jobs, no bookmaker integration.
param([switch]$InstallSchedule)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$marker = Join-Path $root "basketball\research_automation.py"
if (-not (Test-Path $python) -or -not (Test-Path $marker)) {
    throw "Stage 2E NBA private environment not installed."
}
if ($InstallSchedule) {
    $actionArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
    $next = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes(5)
    if ($next -le (Get-Date)) { $next = $next.AddHours(1) }
    $trigger = New-ScheduledTaskTrigger -Once -At $next `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Days 365)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName "BetSightly NBA Pregame Check" `
        -Description "Private current-season NBA pregame monitor; no betting" `
        -Action $action -Trigger $trigger -Settings $settings -Force |
        Out-Null
    Write-Host "Registered private NBA pregame check hourly at :05 local."
    Write-Host "Task needs a powered-on Windows PC; expires after 365 days."
    Write-Host "Next task time: $next"
    exit 0
}
Set-Location $root
$private = Join-Path $root "data\basketball\research"
New-Item -ItemType Directory -Force -Path $private | Out-Null
$log = Join-Path $private "pregame_check.log"
$resultText = (& $python -m basketball.research_cli automate --mode pregame 2>&1 |
    Out-String)
$exitCode = $LASTEXITCODE
Add-Content -LiteralPath $log -Value $resultText -Encoding UTF8
Write-Host $resultText
if ($exitCode -ne 0) {
    throw "Pregame check failed. Inspect automation_pregame.json and $log"
}
try {
    $result = $resultText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "Pregame checker did not return valid JSON. See $log"
}
if ($result.status -eq "busy") {
    Write-Host "Another NBA research task was active; skipped overlapping pregame run."
    exit 0
}
if ($result.status -ne "succeeded") {
    throw "NBA pregame verification incomplete: $($result.status)"
}
Write-Host "NBA pregame check passed. Original saved forecasts are immutable."
