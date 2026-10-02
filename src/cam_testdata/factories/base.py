"""Factory base: every factory writes through the session bound by the scenario runner."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from factory.alchemy import SQLAlchemyModelFactory
from sqlalchemy.orm import Session

_session: ContextVar[Session | None] = ContextVar("cam_testdata_session", default=None)


def current_session() -> Session:
    session = _session.get()
    if session is None:
        raise RuntimeError(
            "no session bound; wrap factory use in `with bind_session(session):`"
        )
    return session


@contextmanager
def bind_session(session: Session) -> Iterator[Session]:
    """Bind the session factories use. The caller owns commit (DESIGN §8)."""
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)


class BaseFactory(SQLAlchemyModelFactory):
    class Meta:
        abstract = True
        sqlalchemy_session_factory = current_session
        sqlalchemy_session_persistence = "flush"
