"""SQL <-> CSV round trip (DESIGN §10, TODO 5.4): load each dump into a scratch
database, re-export CSV with the same exporter, and byte-compare with the
committed CSVs. Catches type and quoting drift between the two artifacts."""

import os
import subprocess
from pathlib import Path

from cam_testdata import db
from cam_testdata.export.csv_export import table_csv
from cam_testdata.settings import Settings, get_settings


class RoundTripError(RuntimeError):
    pass


def _admin(settings: Settings, sql: str) -> None:
    cmd = [
        *settings.database.psql_cmd(),
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        "-c",
        sql,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def verify_sql(
    profile: str, out_dir: Path, settings: Settings | None = None
) -> dict[str, list[str]]:
    """Return {dump file: [tables whose CSV differs]}; raises if a dump doesn't load."""
    settings = settings or get_settings()
    if os.environ.get("CAM_PG_URL"):
        raise RoundTripError("verify-sql needs the URL template (unset CAM_PG_URL)")
    scratch_profile = f"{profile}_verify"
    scratch_db = f"cam_testdata_{scratch_profile}"
    csv_dir = out_dir / "csv"
    results: dict[str, list[str]] = {}
    for dump in sorted((out_dir / "sql").glob(f"cam_{profile}*.sql")):
        _admin(settings, f'DROP DATABASE IF EXISTS "{scratch_db}"')
        _admin(settings, f'CREATE DATABASE "{scratch_db}"')
        load = subprocess.run(
            [
                *settings.database.psql_cmd(),
                "-d",
                scratch_db,
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
            ],
            input=dump.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            check=False,  # report the error ourselves
        )
        if load.returncode != 0:
            raise RoundTripError(
                f"{dump.name} failed to load: {load.stderr.strip()[-500:]}"
            )
        engine = db.make_engine(scratch_profile, settings)
        try:
            with engine.connect() as conn:
                differing = [
                    table.name
                    for table in db.registry_tables(settings)
                    if table_csv(conn, table)
                    != (csv_dir / f"{table.name}.csv").read_text(encoding="utf-8")
                ]
        finally:
            engine.dispose()
        results[dump.name] = differing
    _admin(settings, f'DROP DATABASE IF EXISTS "{scratch_db}"')
    return results
