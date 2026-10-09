"""Remote evaluation is manual, read-only, staging-branch-only."""
from pathlib import Path
from datetime import datetime

import pytest

from scripts import run_staging_readonly_evaluation as runner


def valid_environment(monkeypatch):
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": (
            "refs/heads/feature/daily-tier-reach-and-builder-supply-20261009"
        ),
        "ENVIRONMENT": "staging",
        "ENABLE_BACKGROUND_JOBS": "false",
        "DATABASE_URL": (
            "postgresql://example_user:example_password@example.invalid/"
            "betsightly_db_staging"
        ),
        "PGOPTIONS": "-c default_transaction_read_only=on",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("key,bad_value", [
    ("GITHUB_ACTIONS", "false"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_REF", "refs/heads/devil"),
    ("ENVIRONMENT", "production"),
    ("ENABLE_BACKGROUND_JOBS", "true"),
    ("DATABASE_URL", "sqlite:///fake"),
    ("PGOPTIONS", ""),
])
def test_rejects_wrong_environment_before_opening_db(monkeypatch, key, bad_value):
    valid_environment(monkeypatch)
    monkeypatch.setenv(key, bad_value)
    monkeypatch.setattr(
        runner, "preflight",
        lambda: pytest.fail("No database access permitted"),
    )
    with pytest.raises(RuntimeError):
        runner.readonly_actions_preflight()


class FakeConnection:
    def __init__(self, *, readonly="on", write_history=False,
                 write_shadow=False, superuser=False):
        self.readonly = readonly
        self.write_history = write_history
        self.write_shadow = write_shadow
        self.superuser = superuser

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        sql = str(statement)
        if "SHOW transaction_read_only" in sql:
            return FakeResult(self.readonly)
        if "pg_roles" in sql:
            return FakeResult({
                "role_name": "betsightly_eval_readonly",
                "superuser": self.superuser,
                "history_available": True,
                "shadow_available": True,
            })
        if "has_table_privilege" in sql:
            return FakeResult({
                "can_change_history": self.write_history,
                "can_change_shadow": self.write_shadow,
            })
        raise AssertionError(f"Unexpected database query: {sql[:100]}")


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def mappings(self):
        return self

    def one(self):
        return self.value


@pytest.mark.parametrize("settings,accepted", [
    ({}, True),
    ({"readonly": "off"}, False),
    ({"write_history": True}, False),
    ({"write_shadow": True}, False),
    ({"superuser": True}, False),
])
def test_database_role_must_be_select_only(monkeypatch, settings, accepted):
    import database

    valid_environment(monkeypatch)
    monkeypatch.setattr(
        runner, "preflight", lambda: "betsightly_db_staging",
    )
    monkeypatch.setattr(
        database.engine, "connect", lambda: FakeConnection(**settings),
    )
    if accepted:
        report = runner.readonly_actions_preflight()
        assert report["read_only"] is True
        assert report["database"] == "betsightly_db_staging"
        assert "example_password" not in str(report)
    else:
        with pytest.raises(RuntimeError):
            runner.readonly_actions_preflight()


def test_wrong_actual_database_is_rejected(monkeypatch):
    valid_environment(monkeypatch)
    monkeypatch.setattr(runner, "preflight", lambda: "betsightly_db")
    with pytest.raises(RuntimeError, match="identity"):
        runner.readonly_actions_preflight()


def test_evaluation_emits_aggregate_reports_not_predictions(monkeypatch, tmp_path):
    from scripts import audit_staging_model_comparison_evidence, export_staging_history_training
    monkeypatch.setattr(runner, "readonly_actions_preflight", lambda: {
        "database": "betsightly_db_staging", "read_only": True,
    })
    monkeypatch.setattr(
        audit_staging_model_comparison_evidence,
        "audit", lambda: {
            "status": "CHAMPION_COMPARISON_BLOCKED",
            "real_bookable_pre_match_observations": 18,
            "settled_real_bookable_pre_match_observations": 0,
            "blockers": ["NO_SETTLED_REAL_BOOKABLE_PREMATCH_OBSERVATIONS"],
        },
    )
    monkeypatch.setattr(
        export_staging_history_training, "training_data",
        lambda **kwargs: {
            "walk_forward_evaluation": {
                "evaluated_folds": 4, "requested_folds": 4,
                "markets": {
                    "match_result": {
                        "winning_folds": 4,
                        "folds_beating_league_conditional_baseline": 3,
                        "weighted_improvement": .02,
                        "weighted_improvement_vs_league_conditional": .013,
                    },
                },
                "production_promotion_authorized": False,
            },
        },
    )
    result = runner.run("all", tmp_path / "reports")
    assert result["status"] == "STAGING_READONLY_EVALUATED"
    assert sorted(result["report_files"]) == [
        "evidence.json", "summary.md", "walkforward.json",
    ]
    assert result["production_unchanged"] is True
    assert result["promotion_authorized"] is False
    summary = (tmp_path / "reports" / "summary.md").read_text()
    assert "CHAMPION_COMPARISON_BLOCKED" in summary
    assert "league" in summary


def test_workflow_is_manual_without_deploy_or_untrusted_shell_interpolation():
    workflow = Path(
        ".github/workflows/staging-model-evaluation.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "environment: betsightly-staging-evaluation" in workflow
    assert "secrets.BETSIGHTLY_STAGING_READONLY_DATABASE_URL" in workflow
    assert "github.ref == 'refs/heads/feature/" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "PGOPTIONS:" in workflow
    assert "default_transaction_read_only=on" in workflow
    assert "upload-artifact@v4" in workflow
    assert "EVALUATION_MODE: ${{ inputs.analysis }}" in workflow
    assert '--mode "$EVALUATION_MODE"' in workflow
    assert '--mode "${{ inputs.analysis }}"' not in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "\n  schedule:" not in workflow
