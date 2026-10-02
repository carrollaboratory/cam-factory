"""Model drift: tables and columns that no factory produces and no skip list covers.

A new column in the model should fail loudly instead of quietly producing
all-NULL data (DESIGN §10).
"""

from dataclasses import dataclass, field
from typing import Any

from cam_testdata import db
from cam_testdata.settings import Settings, get_settings


@dataclass
class DriftReport:
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)  # "Table.column"
    # skip_columns entries the model no longer has
    stale_skips: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.stale_skips)


def produced_columns(factories: list[Any]) -> dict[str, set[str]]:
    """Table name -> columns that some factory declares."""
    produced: dict[str, set[str]] = {}
    for factory in factories:
        table = factory._meta.model.__table__
        declared = set(factory._meta.declarations)
        produced.setdefault(table.name, set()).update(
            c.name for c in table.columns if c.name in declared
        )
    return produced


def check(factories: list[Any], settings: Settings | None = None) -> DriftReport:
    settings = settings or get_settings()
    produced = produced_columns(factories)
    empty = set(settings.tables.empty)
    skips = set(settings.drift.skip_columns)
    report = DriftReport()

    known_columns = set()
    for table in db.registry_tables(settings):
        cols = {f"{table.name}.{c.name}" for c in table.columns}
        known_columns |= cols
        if table.name in empty:
            continue
        if table.name not in produced:
            report.missing_tables.append(table.name)
            continue
        for col in sorted(cols):
            if col.split(".", 1)[1] not in produced[table.name] and col not in skips:
                report.missing_columns.append(col)

    report.stale_skips = sorted(skips - known_columns)
    return report
