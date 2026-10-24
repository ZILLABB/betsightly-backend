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
    Register-ScheduledTask -TaskName "BetSightly NBA Score Check" `
        -Description "Hourly private final-score verification; no bets, no training" `
        -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Registered private NBA SCORE-ONLY task every hour at :20 local."
    Write-Host "Runs when the Windows computer is available; expires after 365 days."
    Write-Host "Next task time: $next"
    exit 0
}
Set-Location $root
$private = Join-Path $root "data\basketball\research"
New-Item -ItemType Directory -Force -Path $private | Out-Null
$log = Join-Path $private "score_check.log"
& $python -m basketball.research_cli settle 2>&1 |
    Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) {
    throw "NBA score check failed (exit code $LASTEXITCODE). See $log"
}
