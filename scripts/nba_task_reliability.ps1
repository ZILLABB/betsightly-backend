# Local-only Windows Task Scheduler diagnostics and opt-in repair.
# Read-only unless -Repair is explicitly supplied. Never modifies the NBA
# private data, original model, forecasts, booking or football production.
[CmdletBinding()]
param(
    [switch]$Repair,
    [switch]$WakeToRun,
    [switch]$AllowBattery
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$expected = [ordered]@{
    "BetSightly NBA Paper Research" = "nba_paper_research.ps1"
    "BetSightly NBA Score Check" = "nba_score_check.ps1"
    "BetSightly NBA Pregame Check" = "nba_pregame_check.ps1"
}
$backup = Join-Path $root "data\basketball\research\scheduler_backups"
if ($Repair) {
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
}
$results = @()
foreach ($name in $expected.Keys) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
    $actionText = ($task.Actions | ForEach-Object {
        [string]$_.Execute + " " + [string]$_.Arguments
    }) -join " "
    $scriptName = $expected[$name]
    $matchesExpected = $actionText -like ("*" + $scriptName + "*")
    if (-not $matchesExpected) {
        throw "Task action mismatch for $name. Do not repair an unrecognized task."
    }
    $before = Get-ScheduledTaskInfo -TaskName $name
    if ($Repair) {
        # Preserve exact existing triggers, principal, action and task path.
        # Export before changing settings, so the registration can be
        # restored locally if a Windows policy interferes.
        $safe = ($name -replace "[^A-Za-z0-9_-]","_")
        $stamp = Get-Date -Format "yyyyMMddTHHmmss"
        Export-ScheduledTask -TaskName $name |
            Set-Content -LiteralPath (Join-Path $backup "$safe-$stamp.xml") -Encoding UTF8
        $settings = $task.Settings
        $settings.StartWhenAvailable = $true
        if ($WakeToRun) {
            $settings.WakeToRun = $true
        }
        if ($AllowBattery) {
            $settings.DisallowStartIfOnBatteries = $false
            $settings.StopIfGoingOnBatteries = $false
        }
        Set-ScheduledTask -TaskName $name -Settings $settings -ErrorAction Stop |
            Out-Null
        $task = Get-ScheduledTask -TaskName $name
    }
    $latest = Get-ScheduledTaskInfo -TaskName $name
    $results += [pscustomobject]@{
        TaskName = $name
        Enabled = [bool]$task.Settings.Enabled
        State = [string]$task.State
        LastRunTime = $latest.LastRunTime
        NextRunTime = $latest.NextRunTime
        LastTaskResult = $latest.LastTaskResult
        NumberOfMissedRuns = $latest.NumberOfMissedRuns
        StartWhenAvailable = [bool]$task.Settings.StartWhenAvailable
        WakeToRun = [bool]$task.Settings.WakeToRun
        DisallowStartIfOnBatteries = [bool]$task.Settings.DisallowStartIfOnBatteries
        StopIfGoingOnBatteries = [bool]$task.Settings.StopIfGoingOnBatteries
        RunOnlyIfIdle = [bool]$task.Settings.RunOnlyIfIdle
        LogonType = [string]$task.Principal.LogonType
    }
}
$results | Format-List
if ($Repair) {
    Write-Host "Private NBA task settings updated; triggers and script actions preserved."
    Write-Host "Original task XML backups: $backup"
    Write-Host "WakeToRun requires OS wake timers and supported sleep hardware."
    Write-Host "Windows cannot execute tasks when powered off, and network sources may fail offline."
} else {
    Write-Host "Read-only task diagnostic. No scheduler settings modified."
    Write-Host "Optional repair: add -Repair -WakeToRun (consider battery impact)."
}
