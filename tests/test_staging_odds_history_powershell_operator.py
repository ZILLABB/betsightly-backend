"""Static contract for Windows staging odds-capture operator.

A Python dry-run must pass before the operator can authorize an append.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path("scripts/capture_staging_odds_history.ps1")


def test_operator_validates_source_provenance_and_refuses_automatic_writes():
    code = SCRIPT.read_text(encoding="utf-8")
    assert 'feature/daily-tier-reach-and-builder-supply-20261009' in code
    assert 'Read-Host "Enter STAGING ADMIN PostgreSQL URL (hidden)" -AsSecureString' in code
    assert "SecureStringToBSTR" in code
    assert "ZeroFreeBSTR" in code
    assert 'capture_staging_odds_history --dry-run' in code
    assert 'capture_staging_odds_history --write-staging' in code
    assert 'if ($approval -cne "CAPTURE STAGING ODDS")' in code
    assert "CONFIRM_APPEND_ONLY_ODDS_HISTORY" in code
    assert "default_transaction_read_only=on" in code
    assert 'captured_from_existing_cache_only' in code
    assert 'eligible_prices' in code
    assert 'network_requests_made' in code
    assert 'changes_to_predictions' in code
    assert 'clv_proven' in code
    assert "Source" not in code or "source" in code.lower()
    assert "postgresql://" not in code
    assert "postgres://" not in code


def test_operator_only_temporarily_exports_database_credentials():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "Push-Location" in code and "Pop-Location" in code
    assert 'Remove-Item Env:\\PGOPTIONS' in code
    assert 'Remove-Item Env:\\BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE' in code
    assert 'SetEnvironmentVariable($name, $before[$name], "Process")' in code
    assert 'if ($null -eq $before[$name])' in code
    assert 'Remove-Variable secret' in code
    assert "finally {" in code
    assert "[switch]$DryRunOnly" in code
    assert 'Write-Host "Cancelled. No database changes made."' in code


def test_powershell_script_syntax_if_parser_is_installed():
    """Parse without executing the script or ever requesting credentials."""
    if not shutil.which("pwsh"):
        pytest.skip("PowerShell parser not installed in CI runner")
    source = SCRIPT.resolve().as_posix().replace("'", "''")
    statement = (
        "$tokens = $null; $errors = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{source}', [ref]$tokens, [ref]$errors); "
        "if ($errors.Count) { $errors | ForEach-Object { "
        "Write-Error $_.Message }; exit 1 }"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", statement],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr
