# Append-safe structured status of an ACTUAL Windows task-script invocation.
# Separate from automation_{mode}.json, which is written ONLY when the
# shared kernel lock has been acquired and actual NBA work was performed.
function Write-NbaScheduledAttempt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$ResearchFolder,
        [Parameter(Mandatory=$true)][ValidateSet('pregame','score')][string]$Mode,
        [Parameter(Mandatory=$true)][string]$StartedAt,
        [Parameter(Mandatory=$true)][string]$Status,
        [Parameter(Mandatory=$true)][int]$ExitCode
    )
    $path = Join-Path $ResearchFolder ("scheduled_" + $Mode + "_attempt.json")
    $content = [ordered]@{
        mode = $Mode
        status = $Status
        started_at = $StartedAt
        finished_at = [DateTime]::UtcNow.ToString("o")
        process_exit_code = $ExitCode
        scheduling = "windows_task_runner"
        local_only = $true
        public_publishing_enabled = $false
    }
    $payload = $content | ConvertTo-Json -Depth 3
    $temporary = "$path.$PID.tmp"
    try {
        [System.IO.File]::WriteAllText(
            $temporary, $payload, (New-Object System.Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporary -Destination $path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}
