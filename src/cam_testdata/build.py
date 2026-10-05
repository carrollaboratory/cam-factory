"""A build: the state factories share, and the ordered write into Postgres.

Factories don't touch the session. They create transient objects that the
current Build collects. `Build.write()` then
  1. resolves every coded value through the ConceptRegistry (recording usage),
  2. loads only the used Vocabulary/Concept rows,
  3. inserts table by table in FK order (self-referencing tables parent-first;
     the Study <-> DOI cycle by inserting NULL and setting it after, DESIGN §6.1),
  4. fixes integer-PK sequences.
The ORM can't do the ordering itself: many FKs have no relationship()
(docs/notes/vertical_slice.md).
"""

import hashlib
import random
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from faker import Faker
from sqlalchemy import Table, inspect
from sqlalchemy.orm import Session
from sqlalchemy.schema import sort_tables_and_constraints
from sqlalchemy.sql.schema import ForeignKeyConstraint
from sqlalchemy.sql.sqltypes import String

from cam_testdata import db
from cam_testdata.concept_pools import ConceptPools, load_pools
from cam_testdata.concepts import ConceptRegistry, is_uri
from cam_testdata.ids import IdRegistry
from cam_testdata.schema_introspect import Model, get_model
from cam_testdata.settings import Settings, get_settings
from cam_testdata.text import BarnyardProvider, theme_animal

FLUSH_BATCH = 5000

_current: ContextVar["Build | None"] = ContextVar("cam_testdata_build", default=None)


class BuildError(RuntimeError):
    pass


def current_build() -> "Build":
    build = _current.get()
    if build is None:
        raise BuildError("no active build; use `with Build(profile).active():`")
    return build


class Build:
    def __init__(
        self,
        profile: str,
        settings: Settings | None = None,
        model: Model | None = None,
        registry: ConceptRegistry | None = None,
    ) -> None:
        self.profile = profile
        self.settings = settings or get_settings()
        self.seed = self.settings.seed(profile)
        self.model = model or get_model()
        self.registry = registry or ConceptRegistry(self.model)
        self.pools: ConceptPools = load_pools(self.model, self.registry)
        self.ids = IdRegistry(self.seed, self.settings.ids)
        self.objects: list[Any] = []
        self.handles: dict[int, str] = {}  # id(obj) -> handle, for id_map.csv
        self._faker = Faker(self.settings.faker.locale)
        self._barnyard = BarnyardProvider(self._faker)  # readable farm-themed filler
        self._faker.add_provider(self._barnyard)
        self._curie_columns: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for cc in self.model.curie_columns:
            self._curie_columns[cc.table].append((cc.column, f"{cc.table}.{cc.column}"))

    @contextmanager
    def active(self) -> Iterator["Build"]:
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    # ----- deterministic helpers ---------------------------------------------

    def handle(self, cls: str, key: str) -> str:
        return f"{self.profile}/{cls}/{key}"

    def _int_seed(self, *parts: str) -> int:
        return int.from_bytes(
            hashlib.sha256("|".join((self.seed, *parts)).encode()).digest()[:8], "big"
        )

    def rng(self, handle: str, label: str) -> random.Random:
        """A Random seeded only by (seed, handle, label): stable no matter what else is built."""
        return random.Random(self._int_seed(handle, label))

    def fake(self, handle: str, label: str) -> Faker:
        """The shared Faker, reseeded for (seed, handle, label) before each use."""
        self._faker.seed_instance(self._int_seed(handle, label))
        # one animal per record, so a study's title and description agree
        self._barnyard.theme = theme_animal(self._int_seed(handle, "theme"))
        return self._faker

    def external_id_uri(self, handle: str) -> str:
        return f"{self.settings.ids.external_id_base}/{handle}"

    # ----- collection --------------------------------------------------------

    def collect(self, obj: Any, handle: str | None = None) -> Any:
        self._normalize(obj)
        self.objects.append(obj)
        if handle:
            self.handles[id(obj)] = handle
        return obj

    def _normalize(self, obj: Any) -> None:
        """R12: never carry '' into the database."""
        for column in obj.__table__.columns:
            if isinstance(column.type, String) and getattr(obj, column.key, None) == "":
                setattr(obj, column.key, None)

    def _resolve_concepts(self) -> None:
        """Record every coded value through the registry. Done at write time, so values
        a scenario sets after creating an object (vital status, deferred links) count."""
        for obj in self.objects:
            self._normalize(obj)
            for attr, label in self._curie_columns.get(obj.__table__.name, []):
                value = getattr(obj, attr, None)
                if value is not None and not is_uri(str(value)):
                    self.registry.resolve(str(value), label)

    # ----- write ---------------------------------------------------------------

    def write(self, session: Session, full_reference: bool = False) -> dict[str, int]:
        """Insert everything collected; returns row counts per table. Caller commits."""
        from cam_testdata.factories.reference import load_reference

        self._resolve_concepts()
        missing = self.registry.missing()
        if missing:
            raise BuildError(
                f"unresolved concepts (run `cam-testdata missing-concepts`): {sorted(missing)}"
            )
        load_reference(session, self.registry, full=full_reference)

        by_table: dict[str, list[Any]] = defaultdict(list)
        for obj in self.objects:
            by_table[obj.__table__.name].append(obj)

        order, cyclic = _insert_order(
            [t for t in db.registry_tables(self.settings) if t.name in by_table]
        )
        deferred: list[tuple[Any, str, Any]] = []
        for table in order:
            rows = sorted(by_table[table.name], key=_pk_key)
            rows = _parents_first(table, rows)
            for fk in cyclic.get(table.name, []):
                for obj in rows:
                    value = getattr(obj, fk, None)
                    if value is not None:
                        deferred.append((obj, fk, value))
                        setattr(obj, fk, None)
            for start in range(
                0, len(rows), FLUSH_BATCH
            ):  # batched: memory stays flat on portal
                session.add_all(rows[start : start + FLUSH_BATCH])
                session.flush()
        for obj, attr, value in deferred:
            setattr(obj, attr, value)
        session.flush()
        db.fix_sequences(session.connection())
        return {name: len(rows) for name, rows in sorted(by_table.items())}


def _pk_key(obj: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in inspect(obj).mapper.primary_key_from_instance(obj))


def _insert_order(tables: list[Table]) -> tuple[list[Table], dict[str, list[str]]]:
    """Tables in FK order, plus the cycle-forming FK columns per table (inserted NULL, set after)."""
    order: list[Table] = []
    cyclic: dict[str, list[str]] = defaultdict(list)
    for table, fkcs in sort_tables_and_constraints(tables):  # type: ignore[no-untyped-call]
        if table is not None:
            order.append(table)
            continue
        for fkc in fkcs:
            assert isinstance(fkc, ForeignKeyConstraint)
            if fkc.referred_table is fkc.table:
                continue  # self-reference: handled by row order, not NULLs
            for col in fkc.columns:
                if not col.nullable:
                    raise BuildError(
                        f"FK cycle through NOT NULL {fkc.table.name}.{col.name}"
                    )
                cyclic[fkc.table.name].append(col.key)
    return order, cyclic


def _parents_first(table: Table, rows: list[Any]) -> list[Any]:
    """For self-referencing tables (Study.parent_study, Sample.parent_sample_id), order parents first."""
    self_fks = [
        (fk.parent.key, fk.column.key)
        for fk in table.foreign_keys
        if fk.column.table is table
    ]
    if not self_fks:
        return rows
    by_pk = {getattr(r, fk_target): r for r in rows for _, fk_target in self_fks[:1]}
    done: set[int] = set()
    ordered: list[Any] = []

    def visit(row: Any, path: frozenset[int]) -> None:
        if id(row) in done:
            return
        if id(row) in path:
            raise BuildError(f"self-reference cycle in {table.name}")
        for attr, _ in self_fks:
            parent = by_pk.get(getattr(row, attr, None))
            if parent is not None:
                visit(parent, path | {id(row)})
        done.add(id(row))
        ordered.append(row)

    for row in rows:
        visit(row, frozenset())
    return ordered
