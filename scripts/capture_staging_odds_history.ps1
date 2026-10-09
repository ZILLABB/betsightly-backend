# Manual staging-only append-only SportyBet odds-history capture.
# This never fetches new bookmaker odds or refreshes/publishes the daily board.
[CmdletBinding()]
param(
    [switch]$DryRunOnly,
    [switch]$LiveOnce
)

$ErrorActionPreference = "Stop"
if ($DryRunOnly -and $LiveOnce) {
    throw "Choose either -DryRunOnly or -LiveOnce, not both."
}
$expectedBranch = "feature/daily-tier-reach-and-builder-supply-20261009"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $branch = (& git branch --show-current)
    if ($LASTEXITCODE -ne 0 -or $branch.Trim() -cne $expectedBranch) {
        throw "Refusing: switch to the staging feature branch before capture."
    }

    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = "python"
    }

    $names = @(
        "DATABASE_URL", "ENVIRONMENT", "ENABLE_BACKGROUND_JOBS",
        "PREPARED_BOARD_PERSISTENCE_ENABLED", "BETSIGHTLY_STAGING_BOARD_ONCE",
        "PGOPTIONS", "BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE",
        "BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE"
    )
    $before = @{}
    foreach ($name in $names) {
        $before[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    $ptr = [IntPtr]::Zero
    try {
        $secret = Read-Host "Enter STAGING ADMIN PostgreSQL URL (hidden)" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
            throw "Missing staging database URL. No capture attempted."
        }

        $env:ENVIRONMENT = "staging"
        $env:ENABLE_BACKGROUND_JOBS = "false"
        $env:PREPARED_BOARD_PERSISTENCE_ENABLED = "true"
        $env:BETSIGHTLY_STAGING_BOARD_ONCE = "CONFIRM_STAGING_ONLY"
        $env:PGOPTIONS = "-c default_transaction_read_only=on"
        Remove-Item Env:\BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE -ErrorAction SilentlyContinue
        Remove-Item Env:\BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE -ErrorAction SilentlyContinue

        if ($LiveOnce) {
            # The backend fetches ONE real complete board, displays the
            # precise source snapshot, and demands operator approval before
            # appending those exact same in-memory quotes to staging.
            # No second live fetch, no staging bookmaker cache mutation.
            Remove-Item Env:\PGOPTIONS -ErrorAction SilentlyContinue
            $env:BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE = "CONFIRM_APPEND_ONLY_ODDS_HISTORY"
            $env:BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE = "CONFIRM_SOURCE_ONLY_LIVE_FETCH"
            & $python -m scripts.capture_staging_odds_history --source live --review-live-and-write
            if ($LASTEXITCODE -ne 0) {
                throw "One-shot live staging odds capture failed or was interrupted."
            }
            return
        }

        # The Python CLI verifies actual connected DB identity and original
        # bookmaker source timestamps before returning a JSON preview.
        $raw = & $python -m scripts.capture_staging_odds_history --dry-run
        if ($LASTEXITCODE -ne 0) {
            throw "Capture preview failed (stale, incomplete, or missing cached board). No write attempted."
        }
        $preview = $raw | Out-String | ConvertFrom-Json
        if ($preview.database -cne "betsightly_db_staging" -or
            $preview.mode -cne "DRY_RUN_ONLY" -or
            $preview.rows_inserted -ne 0 -or
            -not $preview.append_only -or
            -not $preview.captured_from_existing_cache_only -or
            $preview.network_requests_made -or $preview.changes_to_predictions -or
            $preview.clv_proven -or
            $preview.eligible_prices -le 0 -or $preview.eligible_fixtures -le 0) {
            throw "Unexpected/unsafe preview. Refusing any database write."
        }

        Write-Host "Verified pre-match SOURCE snapshot preview:" -ForegroundColor Cyan
        Write-Host ($preview | ConvertTo-Json -Depth 6)

        if ($DryRunOnly) {
            Write-Host "Dry run complete. No odds-history rows created."
            return
        }

        $approval = Read-Host "Type CAPTURE STAGING ODDS to append verified prices"
        if ($approval -cne "CAPTURE STAGING ODDS") {
            Write-Host "Cancelled. No database changes made."
            return
        }

        Remove-Item Env:\PGOPTIONS -ErrorAction SilentlyContinue
        $env:BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE = "CONFIRM_APPEND_ONLY_ODDS_HISTORY"

        # Rechecks connected staging identity and cached source freshness.
        # It does NOT copy prices into the published prediction tables.
        $written = & $python -m scripts.capture_staging_odds_history --write-staging
        if ($LASTEXITCODE -ne 0) {
            throw "Staging capture returned an error. Verify staging archive state."
        }
        $result = $written | Out-String | ConvertFrom-Json
        if ($result.database -cne "betsightly_db_staging" -or
            $result.mode -cne "WRITE_STAGING" -or
            -not $result.append_only -or
            $result.network_requests_made -or
            $result.changes_to_predictions -or
            $result.clv_proven -or
            $result.rows_inserted -lt 0) {
            throw "Unexpected capture response. Inspect isolated staging archive."
        }
        Write-Host "Append-only staging archive result:" -ForegroundColor Green
        Write-Host ($result | ConvertTo-Json -Depth 6)
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        foreach ($name in $names) {
            if ($null -eq $before[$name]) {
                Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
            }
            else {
                [Environment]::SetEnvironmentVariable($name, $before[$name], "Process")
            }
        }
        Remove-Variable secret -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
