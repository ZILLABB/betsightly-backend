from utils.vps_parity import compare_inventory


def test_equal_table_counts_pass():
    result = compare_inventory({"daily_runs": 2, "tickets": 15},
                               {"daily_runs": 2, "tickets": 15})
    assert result["healthy"] is True
    assert result["source_total_rows"] == 17


def test_missing_and_extra_tables_fail_closed():
    result = compare_inventory({"daily_runs": 2, "tickets": 15},
                               {"daily_runs": 2, "other": 15})
    assert not result["healthy"]
    assert result["missing_tables"] == ["tickets"]
    assert result["extra_tables"] == ["other"]


def test_mismatched_rows_flagged_without_disclosing_content():
    result = compare_inventory({"booking_audit": 100}, {"booking_audit": 99})
    assert not result["healthy"]
    assert result["mismatched_rows"] == {
        "booking_audit": {"source": 100, "restored": 99}
    }


def test_empty_inventory_is_not_success():
    assert not compare_inventory({}, {})["healthy"]
