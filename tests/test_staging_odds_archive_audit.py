"""Odds-history readiness report has no writes and no CLV claims."""
from scripts import audit_staging_odds_history_capture as audit


class _Result:
    def __init__(self, data):
        self.data = data

    def mappings(self):
        return self

    def one(self):
        return self.data


class _Conn:
    def __init__(self, table_exists, can_select):
        self.table_exists = table_exists
        self.can_select = can_select
        self.scanned = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        sql = str(statement)
        if "to_regclass" in sql:
            return _Result({
                "table_exists": self.table_exists,
                "can_select": self.can_select,
            })
        assert "WITH per_market AS" in sql
        self.scanned = True
        return _Result({
            "immutable_price_rows": 200,
            "distinct_snapshots": 2,
            "priced_fixture_markets": 100,
            "fixture_markets_with_two_source_snapshots": 95,
            "near_close_research_pairs": 30,
        })


class _DB:
    def __init__(self, *args):
        self.conn = _Conn(*args)

    def connect(self):
        return self.conn


def test_no_archive_is_explicitly_not_clv():
    db = _DB(False, False)
    report = audit.audit_odds_archive(db_engine=db)
    assert report["status"] == "APPEND_ONLY_ODDS_WAREHOUSE_NOT_INITIALIZED"
    assert report["verified_clv_available"] is False
    assert db.conn.scanned is False


def test_no_select_grant_does_not_break_other_evaluation():
    db = _DB(True, False)
    report = audit.audit_odds_archive(db_engine=db)
    assert report["status"] == "ODDS_WAREHOUSE_SELECT_GRANT_REQUIRED"
    assert report["verified_clv_available"] is False
    assert db.conn.scanned is False


def test_price_pairs_remain_research_only():
    db = _DB(True, True)
    report = audit.audit_odds_archive(db_engine=db)
    assert report["distinct_snapshots"] == 2
    assert report["fixture_markets_with_two_source_snapshots"] == 95
    assert report["near_close_research_pairs"] == 30
    assert report["verified_clv_available"] is False
    assert report["read_only"] is True


def test_archive_sql_is_read_only_and_requires_source_snapshot_diversity():
    sql = str(audit.METRICS_QUERY).upper()
    assert "COUNT(DISTINCT SNAPSHOT_ID)" in sql
    assert "COUNT(DISTINCT CAPTURED_AT)" in sql
    assert "UNIQUE_SOURCE_SNAPSHOTS >= 2" in sql
    assert "OBSERVED_PRICE_MOMENTS >= 2" in sql
    assert "CAPTURED_AT < KICKOFF" in sql
    assert "NEAR_CLOSE_RESEARCH_PAIRS" in sql
    assert all(token not in sql for token in (
        "INSERT INTO", "DELETE FROM", "UPDATE ", "DROP TABLE", "TRUNCATE "
    ))
