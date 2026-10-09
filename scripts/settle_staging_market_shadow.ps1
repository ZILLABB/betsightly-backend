# Staging-only operator wrapper. Never persist connection URLs or skip the
# Python module's separate database identity and explicit-write safeguards.
[CmdletBinding()]
param(
    [switch]$DryRunOnly
)

$ErrorActionPreference = "Stop"
$expectedBranch = "feature/daily-tier-reach-and-builder-supply-20261009"
$repository = Split-Path -Parent $PSScriptRoot
Push-Location $repository
try {
    $branch = (& git branch --show-current)
    if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne $expectedBranch) {
        throw "Wrong Git branch. Switch to $expectedBranch before settling staging."
    }

    $python = Join-Path $repository ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = "python"
    }

    # Only this process inherits the secret. No URL is printed or stored.
    $secret = Read-Host "Enter STAGING ADMIN PostgreSQL URL (hidden)" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $names = @(
        "DATABASE_URL", "ENVIRONMENT", "ENABLE_BACKGROUND_JOBS",
        "PREPARED_BOARD_PERSISTENCE_ENABLED", "BETSIGHTLY_STAGING_BOARD_ONCE",
        "PGOPTIONS", "BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE"
    )
    $oldEnvironment = @{}
    foreach ($name in $names) {
        $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        if (-not $env:DATABASE_URL) {
            throw "Missing staging database URL. No work attempted."
        }
        $env:ENVIRONMENT = "staging"
        $env:ENABLE_BACKGROUND_JOBS = "false"
        $env:PREPARED_BOARD_PERSISTENCE_ENABLED = "true"
        $env:BETSIGHTLY_STAGING_BOARD_ONCE = "CONFIRM_STAGING_ONLY"
        $env:PGOPTIONS = "-c default_transaction_read_only=on"
        Remove-Item Env:\BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE -ErrorAction SilentlyContinue

        $previewText = & $python -m scripts.settle_staging_market_shadow --dry-run
        if ($LASTEXITCODE -ne 0) { throw "Staging dry-run failed. No write attempted." }
        $preview = ($previewText | Out-String | ConvertFrom-Json)

        if ($preview.status -ne "DRY_RUN_ONLY" -or $preview.write_executed -or
            $preview.rows_updated -ne 0 -or
            $preview.database -ne "betsightly_db_staging") {
            throw "Unexpected preview response. Refusing database writes."
        }

        Write-Host "Verified staging preview:" -ForegroundColor Cyan
        Write-Host ($preview | ConvertTo-Json -Depth 5)
        if ($DryRunOnly) {
            Write-Host "Dry-run only: no database write requested."
            return
        }
        if ($preview.would_settle + $preview.would_void -eq 0) {
            Write-Host "No new verified observations to settle."
            return
        }
        if (@($preview.unresolved.PSObject.Properties).Count -gt 0 -or
            @($preview.provider_failures.PSObject.Properties).Count -gt 0) {
            throw "Unresolved fixtures or provider errors in preview. No write attempted."
        }

        $approval = Read-Host "Type SETTLE STAGING to commit verified results"
        if ($approval -cne "SETTLE STAGING") {
            Write-Host "Cancelled. No database changes made."
            return
        }

        Remove-Item Env:\PGOPTIONS -ErrorAction SilentlyContinue
        $env:BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE = "CONFIRM_VERIFIED_SHADOW_SETTLEMENT_ONLY"

        # The Python command re-verifies actual staging DB identity, current
        # UPDATE privileges, verified finals, cutoff and first-write conditions.
        $appliedText = & $python -m scripts.settle_staging_market_shadow --write-staging
        if ($LASTEXITCODE -ne 0) { throw "Staging settlement failed." }
        $applied = ($appliedText | Out-String | ConvertFrom-Json)
        if ($applied.database -ne "betsightly_db_staging" -or
            -not $applied.write_executed -or
            $applied.status -ne "STAGING_SHADOW_SETTLEMENT") {
            throw "Unexpected settlement response. Inspect staging database."
        }
        Write-Host "Staging settlement result:" -ForegroundColor Green
        Write-Host ($applied | ConvertTo-Json -Depth 5)
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        foreach ($name in $names) {
            if ($null -eq $oldEnvironment[$name]) {
                Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
            }
            else {
                [Environment]::SetEnvironmentVariable(
                    $name, $oldEnvironment[$name], "Process"
                )
            }
        }
        Remove-Variable secret -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
