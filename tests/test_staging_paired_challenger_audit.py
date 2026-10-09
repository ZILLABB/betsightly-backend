"""Prospective pairs remain read-only, version-scoped, and non-promotable."""
from scripts import audit_staging_paired_challenger as pairs


def fake_row(version, n, champion, challenger):
    return {
        "model_version": version,
        "feature_version": "runtime",
        "paired_observations": n,
        "distinct_fixtures": n,
        "champion_multiclass_brier": champion,
        "challenger_multiclass_brier": challenger,
        "champion_log_loss": 0.99,
        "challenger_log_loss": 1.01,
    }


def test_separate_cohorts_never_sum_overlapping_fixtures():
    report = pairs.summarize([
        fake_row("core", 39, 0.595, 0.603),
        fake_row("v2", 38, 0.601, 0.608),
    ])
    assert report["status"] == "DESCRIPTIVE_PAIRED_EVIDENCE_ONLY"
    assert report["do_not_sum_fixtures_across_versions"] is True
    assert report["production_promotion_authorized"] is False
    assert report["linked_to_real_sportybet_closing_odds"] is False
    assert len(report["cohorts"]) == 2
    assert all(item["below_research_review_minimum"] for item in report["cohorts"])
    assert report["cohorts"][0]["challenger_brier_gain"] < 0
    assert report["cohorts"][1]["challenger_brier_gain"] < 0


def test_empty_evidence_never_promotes():
    report = pairs.summarize([])
    assert report["status"] == "NO_VERIFIED_PAIRED_EVIDENCE"
    assert report["cohorts"] == []
    assert report["production_promotion_authorized"] is False


class MappingResult:
    def __init__(self, payload):
        self.payload = payload

    def mappings(self):
        return self

    def one(self):
        return self.payload

    def __iter__(self):
        return iter(self.payload if isinstance(self.payload, list) else [])


class FakeEngine:
    def __init__(self, available):
        self.available = available
        self.queried_pair_rows = False

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        if "to_regclass" in str(sql):
            return MappingResult(self.available)
        if "GROUP BY model_version" in str(sql):
            self.queried_pair_rows = True
            return MappingResult([fake_row("core", 39, .59, .60)])
        raise AssertionError("Unexpected SQL")


def test_missing_select_grant_is_reported_without_trying_to_read_rows():
    engine = FakeEngine({"table_exists": True, "can_select": False})
    report = pairs.audit_paired_challenger(db_engine=engine)
    assert report["status"] == "STAGING_READONLY_SELECT_GRANT_REQUIRED"
    assert engine.queried_pair_rows is False
    assert report["production_promotion_authorized"] is False


def test_missing_table_is_not_a_workflow_failure():
    engine = FakeEngine({"table_exists": False, "can_select": False})
    report = pairs.audit_paired_challenger(db_engine=engine)
    assert report["status"] == "PROSPECTIVE_PAIRS_TABLE_MISSING"
    assert engine.queried_pair_rows is False


def test_select_grant_reads_aggregate_only():
    engine = FakeEngine({"table_exists": True, "can_select": True})
    report = pairs.audit_paired_challenger(db_engine=engine)
    assert report["cohorts"][0]["independent_fixtures"] == 39
    assert engine.queried_pair_rows is True
    assert report["production_promotion_authorized"] is False


def test_sql_requires_verified_prematch_and_does_not_write():
    sql = str(pairs.PAIRED_QUERY).upper()
    assert sql.strip().startswith("SELECT")
    assert "STATUS = 'SETTLED'" in sql
    assert "TARGET = 'MATCH_RESULT'" in sql
    assert "OBSERVED_AT < KICKOFF" in sql
    assert "SETTLED_AT >= KICKOFF" in sql
    assert "SETTLEMENT_SOURCE IS NOT NULL" in sql
    assert "COUNT(DISTINCT FIXTURE_ID)" in sql
    assert "CHAMPION_MULTICLASS_BRIER" in sql
    assert "CHALLENGER_MULTICLASS_BRIER" in sql
    assert all(word not in sql for word in (
        "UPDATE ", "DELETE FROM", "DROP TABLE", "INSERT INTO"
    ))
