"""Shared fixtures. Tests hit the real cam_testdata_test database (AGENTS.md)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from cam_testdata import db


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine on cam_testdata_test with a freshly reset schema and all registry tables."""
    eng = db.make_engine("test")
    db.reset(eng)
    db.create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test (savepoints for inner commits)."""
    with engine.connect() as conn:
        outer = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as sess:
            yield sess
        outer.rollback()
