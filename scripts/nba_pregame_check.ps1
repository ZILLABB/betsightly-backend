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
. (Join-Path $PSScriptRoot "nba_task_attempt.ps1")
$attemptStart = [DateTime]::UtcNow.ToString("o")
$attemptStatus = "failed"
$attemptExit = 1
try {
    $resultText = (& $python -m basketball.research_cli automate --mode pregame 2>&1 |
        Out-String)
    $attemptExit = [int]$LASTEXITCODE
    Add-Content -LiteralPath $log -Value $resultText -Encoding UTF8
    Write-Host $resultText
    if ($attemptExit -ne 0) {
        throw "Pregame check failed (exit code $attemptExit). Inspect $log"
    }
    # The provider may print one source-quality exclusion notice before JSON.
    $jsonStart = $resultText.IndexOf("{")
    if ($jsonStart -ge 0) {
        try {
            $payload = $resultText.Substring($jsonStart) | ConvertFrom-Json -ErrorAction Stop
            $attemptStatus = [string]$payload.status
        } catch {
            $attemptStatus = "unparsed_output"
        }
    } else {
        $attemptStatus = "unparsed_output"
    }
    if ($attemptStatus -eq "failed" -or $attemptStatus -eq "degraded") {
        throw "NBA pregame reported $attemptStatus; inspect $log"
    }
    if ($attemptStatus -eq "busy") {
        Write-Host "NBA pregame skipped due to another active task; no new research receipt."
    }
} finally {
    Write-NbaScheduledAttempt -ResearchFolder $private -Mode pregame `
        -StartedAt $attemptStart -Status $attemptStatus -ExitCode $attemptExit
}
# The CSV validator may print a harmless source exclusion notice.
# Trust the Python process exit code, not brittle parsing of mixed output.
# run_automation persists exact status in automation_pregame.json.
Write-Host "Check automation_pregame.json for the outcome and source attempts."
