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


# ----- model shape snapshot (manifest) and comparison (check-drift, TODO 6.4) ----------


def model_shape(model: Any, settings: Settings | None = None) -> dict[str, Any]:
    """Tables with their columns, and enums with a count + hash of their values."""
    import hashlib

    tables = {t.name: [c.name for c in t.columns] for t in db.registry_tables(settings)}
    enums = {}
    for name in sorted(model.enums):
        values = sorted(model.enum_values(name))
        digest = hashlib.sha256("\n".join(values).encode()).hexdigest()[:16]
        enums[str(name)] = {"count": len(values), "sha256": digest}
    return {"tables": tables, "enums": enums}


def compare_shapes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    old_t, new_t = old.get("tables", {}), new.get("tables", {})
    changes += [f"table added: {t}" for t in sorted(set(new_t) - set(old_t))]
    changes += [f"table removed: {t}" for t in sorted(set(old_t) - set(new_t))]
    for t in sorted(set(old_t) & set(new_t)):
        changes += [f"column added: {t}.{c}" for c in new_t[t] if c not in old_t[t]]
        changes += [f"column removed: {t}.{c}" for c in old_t[t] if c not in new_t[t]]
    old_e, new_e = old.get("enums", {}), new.get("enums", {})
    changes += [f"enum added: {e}" for e in sorted(set(new_e) - set(old_e))]
    changes += [f"enum removed: {e}" for e in sorted(set(old_e) - set(new_e))]
    for e in sorted(set(old_e) & set(new_e)):
        if old_e[e] != new_e[e]:
            changes.append(
                f"enum changed: {e} ({old_e[e]['count']} -> {new_e[e]['count']} values)"
            )
    return changes
