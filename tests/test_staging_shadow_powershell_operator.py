"""Static safety assertions for the staging PowerShell operator helper.

This doesn't replace executing the script on Windows; backend Python preflight
also verifies actual database identity and write authorizations.
"""
from pathlib import Path


SCRIPT = Path("scripts/settle_staging_market_shadow.ps1")


def test_operator_helper_fails_closed_and_has_no_inline_database_credentials():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "feature/daily-tier-reach-and-builder-supply-20261009" in code
    assert 'Read-Host "Enter STAGING ADMIN PostgreSQL URL (hidden)" -AsSecureString' in code
    assert "SecureStringToBSTR" in code
    assert "ZeroFreeBSTR" in code
    assert "ConvertFrom-Json" in code
    assert 'settle_staging_market_shadow --dry-run' in code
    assert 'settle_staging_market_shadow --write-staging' in code
    assert "SETTLE STAGING" in code
    assert 'if ($approval -cne "SETTLE STAGING")' in code
    assert "DRY_RUN_ONLY" in code
    assert "STAGING_SHADOW_SETTLEMENT" in code
    assert "BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE" in code
    assert "CONFIRM_VERIFIED_SHADOW_SETTLEMENT_ONLY" in code
    assert "$env:PGOPTIONS" in code
    assert "default_transaction_read_only=on" in code
    assert "-DryRunOnly" not in code or "[switch]$DryRunOnly" in code
    assert "Remove-Item Env:\\PGOPTIONS" in code
    assert "STAGING ADMIN PostgreSQL URL" in code
    assert "postgresql://" not in code
    assert "postgres://" not in code


def test_operator_helper_restores_process_environment_and_never_auto_approves():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "Push-Location" in code and "Pop-Location" in code
    assert "finally {" in code
    assert 'SetEnvironmentVariable(' in code
    assert 'oldEnvironment' in code
    assert 'if ($preview.would_settle + $preview.would_void -eq 0)' in code
    assert "provider_failures" in code
    assert "unresolved" in code
    assert 'Write-Host "Cancelled. No database changes made."' in code
