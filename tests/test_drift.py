import pytest

from cam_testdata import drift
from cam_testdata.factories import all_factories


@pytest.mark.xfail(
    strict=True, reason="factories arrive in Phase 3; remove this marker at TODO 3.8"
)
def test_every_table_and_column_is_produced_or_skipped() -> None:
    report = drift.check(all_factories())
    assert report.ok, report


def test_drift_check_reports_missing_tables_without_factories() -> None:
    report = drift.check([])
    assert "Study" in report.missing_tables
    assert "Synonym" not in report.missing_tables  # tables.empty
    assert "Any" not in report.missing_tables  # tables.exclude
