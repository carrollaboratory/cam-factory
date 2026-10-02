"""SQL dumps (DESIGN §9, TODO 5.4): two full pg_dump files, byte-stable.

- sql/cam_<profile>.sql          plain format with COPY
- sql/cam_<profile>_inserts.sql  same, with --column-inserts (for loaders without COPY)

Both are full dumps: a data-only dump can't be loaded once the Study <-> DOI
cycle has data (docs/notes/vertical_slice.md). pg_dump runs through the
configured command (the Postgres container) with a fixed --restrict-key.
"""

import subprocess
from pathlib import Path

from cam_testdata.settings import Settings, get_settings


def pg_dump(dbname: str, *extra: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    database = settings.database
    cmd = [
        *database.pg_dump,
        "-d",
        dbname,
        f"--schema={database.schema_name}",
        "--no-owner",
        "--no-privileges",
        f"--restrict-key={database.restrict_key}",
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def pg_dump_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    cmd = settings.database.pg_dump
    # --version must stand alone, so drop options that follow the program (e.g. -U postgres)
    program = next(i for i, part in enumerate(cmd) if part.endswith("pg_dump"))
    out = subprocess.run(
        [*cmd[: program + 1], "--version"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def export_sql(
    profile: str,
    out_dir: Path,
    settings: Settings | None = None,
    dbname: str | None = None,
) -> list[Path]:
    """Dump database `dbname` (default cam_testdata_<profile>) to files named for the profile."""
    dbname = dbname or f"cam_testdata_{profile}"
    out_dir.mkdir(parents=True, exist_ok=True)
    copy = out_dir / f"cam_{profile}.sql"
    inserts = out_dir / f"cam_{profile}_inserts.sql"
    copy.write_text(pg_dump(dbname, settings=settings), encoding="utf-8", newline="")
    inserts.write_text(
        pg_dump(dbname, "--column-inserts", settings=settings),
        encoding="utf-8",
        newline="",
    )
    return [copy, inserts]
