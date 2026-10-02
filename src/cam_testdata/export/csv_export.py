"""Per-table CSV (DESIGN §9, TODO 5.2).

One file per DDL table, named exactly like the table; header in SQLAlchemy
column order; rows sorted by primary key; NULL written as an empty field (R12
guarantees no '' to confuse it with); UTF-8, \\n line endings, RFC 4180 quoting.
"""

import csv
import io
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, select

from cam_testdata import db
from cam_testdata.settings import Settings


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)  # shortest round-tripping form, stable across runs
    return str(value)


def table_csv(conn: Connection, table: Table) -> str:
    rows = conn.execute(select(table).order_by(*table.primary_key.columns)).all()
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([c.name for c in table.columns])
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return buf.getvalue()


def export_csv(
    conn: Connection, out_dir: Path, settings: Settings | None = None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for table in db.registry_tables(settings):
        path = out_dir / f"{table.name}.csv"
        path.write_text(table_csv(conn, table), encoding="utf-8", newline="")
        written.append(path)
    return written
