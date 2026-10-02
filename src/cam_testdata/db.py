"""Database handling (DESIGN §4): engine, schema reset, table creation, sequences."""

from collections.abc import Iterable

from common_access_model.datamodel.common_access_model_sqla import Base
from sqlalchemy import (
    Connection,
    Engine,
    Integer,
    MetaData,
    Table,
    create_engine,
    func,
    select,
    text,
)

from cam_testdata.settings import Settings, get_settings


def metadata() -> MetaData:
    md: MetaData = Base.metadata
    return md


def registry_tables(settings: Settings | None = None) -> list[Table]:
    """Tables we create: every model table except the excluded ones, sorted by name.

    create_all orders creation itself (and handles the Study <-> DOI cycle);
    insert ordering is the scenario loader's job.
    """
    settings = settings or get_settings()
    excluded = set(settings.tables.exclude)
    unknown = excluded - set(metadata().tables)
    if unknown:
        raise ValueError(
            f"tables.exclude names tables the model doesn't have: {sorted(unknown)}"
        )
    return [
        metadata().tables[name]
        for name in sorted(metadata().tables)
        if name not in excluded
    ]


def make_engine(profile: str, settings: Settings | None = None) -> Engine:
    """Engine whose search_path is the cam schema, so tables and enum types land there."""
    settings = settings or get_settings()
    schema = settings.database.schema_name
    return create_engine(
        settings.database.url(profile),
        connect_args={"options": f"-csearch_path={schema}"},
    )


def reset(engine: Engine, settings: Settings | None = None) -> None:
    """Drop and recreate the schema. CASCADE because the model has FK cycles."""
    schema = (settings or get_settings()).database.schema_name
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))


def create_tables(engine: Engine, tables: Iterable[Table] | None = None) -> None:
    tables = list(tables) if tables is not None else registry_tables()
    metadata().create_all(engine, tables=tables)


def serial_tables(tables: Iterable[Table] | None = None) -> list[Table]:
    """Tables with a single autoincrementing integer PK (they own a sequence)."""
    tables = list(tables) if tables is not None else registry_tables()
    found = []
    for table in tables:
        pk = list(table.primary_key.columns)
        if (
            len(pk) == 1
            and isinstance(pk[0].type, Integer)
            and pk[0].autoincrement in (True, "auto")
        ):
            found.append(table)
    return found


def fix_sequences(conn: Connection, tables: Iterable[Table] | None = None) -> None:
    """After explicit integer IDs are inserted, move each sequence past max(id).

    Takes a connection so it runs inside the caller's transaction.
    """
    schema = get_settings().database.schema_name
    for table in serial_tables(tables):
        pk = next(iter(table.primary_key.columns))
        seq = conn.execute(
            select(func.pg_get_serial_sequence(f'"{schema}"."{table.name}"', pk.name))
        ).scalar_one_or_none()
        if seq is None:
            continue
        max_id = conn.execute(select(func.max(pk))).scalar_one()
        # setval(seq, n, is_called): the next nextval() returns n+1 if is_called, else n.
        conn.execute(select(func.setval(seq, max_id or 1, max_id is not None)))
