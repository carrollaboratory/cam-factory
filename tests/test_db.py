from common_access_model.datamodel.common_access_model_sqla import Investigator
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from cam_testdata import db


def test_registry_excludes_generator_artifacts() -> None:
    names = {t.name for t in db.registry_tables()}
    assert not names & {"Any", "Record", "Record_external_id"}
    assert {"Study", "Study_program", "Concept", "Synonym"} <= names


def test_all_registry_tables_created_in_cam(engine: Engine) -> None:
    with engine.connect() as conn:
        created = set(
            conn.execute(
                text(
                    "select table_name from information_schema.tables where table_schema = 'cam'"
                )
            )
            .scalars()
            .all()
        )
    assert created == {t.name for t in db.registry_tables()}


def test_enum_types_live_in_cam_not_public(engine: Engine) -> None:
    query = text(
        """
        select n.nspname, t.typname
        from pg_type t join pg_namespace n on n.oid = t.typnamespace
        where t.typtype = 'e'
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    expected = {
        c.type.name  # type: ignore[attr-defined]
        for t in db.registry_tables()
        for c in t.columns
        if hasattr(c.type, "enums")
    }
    assert {name for schema, name in rows if schema == "cam"} == expected
    assert not [name for schema, name in rows if schema == "public"]


def test_fix_sequences_moves_past_explicit_ids(session: Session) -> None:
    assert {"Investigator", "Publication", "HashDigest"} <= {
        t.name for t in db.serial_tables()
    }

    session.add(Investigator(id=41, name="Explicit"))
    session.flush()
    db.fix_sequences(session.connection(), [Investigator.__table__])  # type: ignore[list-item]
    nxt = Investigator(name="Next")
    session.add(nxt)
    session.flush()
    assert nxt.id == 42


def test_fix_sequences_on_empty_table_starts_at_one(session: Session) -> None:
    db.fix_sequences(session.connection(), [Investigator.__table__])  # type: ignore[list-item]
    first = Investigator(name="First")
    session.add(first)
    session.flush()
    assert first.id == 1
