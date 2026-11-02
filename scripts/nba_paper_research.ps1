# Local Windows runner for BetSightly NBA research.
# Manual execution runs ONE paper-test cycle. -InstallSchedule only registers
# a task on this computer if the owner explicitly invokes it.
param(
    [switch]$InstallSchedule,
    [string]$LocalTime = "18:00",
    [switch]$ShowDashboard
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$venvPython = Join-Path $root ".venv/Scripts/python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$repoMarker = Join-Path $root "basketball/research_cycle.py"
if (-not (Test-Path $repoMarker)) {
    throw "Not an NBA research checkout. Use the isolated research branch."
}
if ($InstallSchedule) {
    if ($LocalTime -notmatch "^([01][0-9]|2[0-3]):[0-5][0-9]$") {
        throw "LocalTime must be HH:mm in your WINDOWS local timezone."
    }
    $actionArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
    $trigger = New-ScheduledTaskTrigger -Daily -At $LocalTime
    Register-ScheduledTask -TaskName "BetSightly NBA Paper Research" -Description "Private local NBA research: no bets or publishing" -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Registered a LOCAL-only daily task for $LocalTime computer time."
    Write-Host "This task runs only when this Windows computer is available."
    exit 0
}
if ($ShowDashboard) {
    & $python -m basketball.research_cli dashboard
} else {
    & $python -m basketball.research_cli cycle --days-ahead 2
}
if ($LASTEXITCODE -ne 0) {
    throw "NBA research command failed (exit code $LASTEXITCODE)."
}
