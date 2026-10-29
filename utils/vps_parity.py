"""Compare source and recovered PostgreSQL public-table inventories.

Only schema names and exact aggregate row counts are reported. A successful
comparison is a necessary but not sufficient application-consistency check.
"""

from __future__ import annotations


def compare_inventory(source: dict[str, int], restored: dict[str, int]) -> dict:
    left, right = set(source), set(restored)
    missing = sorted(left - right)
    extra = sorted(right - left)
    mismatched = {
        table: {"source": source[table], "restored": restored[table]}
        for table in sorted(left & right)
        if source[table] != restored[table]
    }
    return {
        "healthy": not (missing or extra or mismatched) and bool(left),
        "source_table_count": len(left),
        "restored_table_count": len(right),
        "source_total_rows": sum(source.values()),
        "restored_total_rows": sum(restored.values()),
        "missing_tables": missing,
        "extra_tables": extra,
        "mismatched_rows": mismatched,
        "limitations": "Compares public table names and counts only; final source writes must be fenced",
    }
