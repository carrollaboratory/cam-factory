"""Small factories for every join table, generated from the model (AGENTS.md:
association tables get their own factories; schema-driven, not hand-listed).

Each is named <ModelClass>Factory (e.g. StudyProgramFactory) and declares every
column; callers pass both the owner and the value column.
"""

from functools import cache
from typing import Any

from common_access_model.datamodel.common_access_model_sqla import Base

from cam_testdata.factories.base import BaseFactory
from cam_testdata.schema_introspect import JoinStorage, get_model


@cache
def _association_models() -> dict[str, type]:
    """Join table name -> mapped class, for every join table some slot uses."""
    model = get_model()
    tables = set()
    for cls in model.table_classes:
        for slot, s in model.slots(cls).items():
            if s.multivalued:
                store = model.storage(cls, slot)
                if isinstance(store, JoinStorage):
                    tables.add(store.table.name)
    mapped = {m.local_table.name: m.class_ for m in Base.registry.mappers}
    missing = tables - set(mapped)
    if missing:
        raise RuntimeError(f"join tables without a mapped class: {sorted(missing)}")
    return {name: mapped[name] for name in sorted(tables)}


@cache
def association_factory(table: str) -> Any:
    model_class = _association_models()[table]
    attrs: dict[str, Any] = {"Meta": type("Meta", (), {"model": model_class})}
    for column in model_class.__table__.columns:  # type: ignore[attr-defined]
        attrs[column.key] = None  # declared so the drift check sees it; always passed
    return type(f"{model_class.__name__}Factory", (BaseFactory,), attrs)


def all_association_factories() -> list[Any]:
    return [association_factory(t) for t in _association_models()]
