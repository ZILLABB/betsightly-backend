# Local lightweight NBA scoreboard checker (no historical re-download or ML).
# -InstallSchedule registers an OPTIONAL hourly Windows task at HH:20.
# The original daily 18:00 research task remains unchanged.
param([switch]$InstallSchedule)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$marker = Join-Path $root "basketball\research_score_only.py"
if (-not (Test-Path $python) -or -not (Test-Path $marker)) {
    throw "NBA research environment not installed. Update the isolated research checkout."
}
if ($InstallSchedule) {
    $actionArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
    $next = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes(20)
    if ($next -le (Get-Date)) { $next = $next.AddHours(1) }
    $trigger = New-ScheduledTaskTrigger -Once -At $next `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Days 365)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName "BetSightly NBA Score Check" `
        -Description "Hourly private final-score verification; no bets, no training" `
        -Action $action -Trigger $trigger -Settings $settings -Force |
        Out-Null
    Write-Host "Registered private NBA SCORE-ONLY task every hour at :20 local."
    Write-Host "Runs when the Windows computer is available; expires after 365 days."
    Write-Host "Next task time: $next"
    exit 0
}
Set-Location $root
$private = Join-Path $root "data\basketball\research"
New-Item -ItemType Directory -Force -Path $private | Out-Null
$log = Join-Path $private "score_check.log"
# Capture the machine-readable output so Windows Task Scheduler does not
# confuse "Python exited successfully" with "the data provider was healthy".
$resultText = (& $python -m basketball.research_cli automate --mode score 2>&1 | Out-String)
$exitCode = $LASTEXITCODE
Write-Host $resultText
Add-Content -LiteralPath $log -Value $resultText -Encoding UTF8
if ($exitCode -ne 0) {
    throw "NBA score check process failed (exit code $exitCode). See $log"
}
try {
    $result = $resultText | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "NBA score check did not return valid JSON. See $log"
}
if ($result.status -eq "idle") {
    Write-Host "NBA score checker idle: no unresolved games required a provider request."
    exit 0
}
if ($result.status -eq "busy") {
    Write-Host "NBA research already running. Skipped duplicate score check."
    exit 0
}
if ($result.status -ne "succeeded") {
    throw ("NBA score check incomplete: $($result.status). " +
        "Review data/basketball/research/automation_score.json and $log")
}
Write-Host "NBA score verification successfully processed its scheduled work."
