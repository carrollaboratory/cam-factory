"""Schema-driven facts from the LinkML SchemaView and SQLAlchemy metadata (TODO 1.3).

Everything that would otherwise be a hard-coded list of tables, columns, ID
prefixes, enum values or units comes from here (AGENTS.md rule 6).
"""

import re
from dataclasses import dataclass
from functools import cache, cached_property
from typing import Any, Literal

from common_access_model.datamodel.common_access_model_sqla import Base
from linkml_runtime import SchemaView
from linkml_runtime.linkml_model import SlotDefinition
from sqlalchemy import Column, Enum, Integer, Table
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm import Mapper

from cam_testdata.settings import SCHEMA_PATH, Settings, get_settings

GLOBAL_ID_TYPE = re.compile(r"^([a-z]{2})GlobalID$")
CONCEPT_CLASS = "Concept"
REFERENCE_CLASSES = frozenset({"Concept", "Vocabulary"})

RangeKind = Literal["entity", "concept", "enum", "uriorcurie", "literal"]
IdKind = Literal["global", "local", "doi", "int", "parent", "reference"]
CurieKind = Literal["concept_fk", "enum", "uriorcurie"]


@dataclass(frozen=True)
class RangeInfo:
    kind: RangeKind
    target: str | None = None  # entity class, for kind == "entity"
    enums: tuple[str, ...] = ()  # enums named by range/any_of (binding or suggestion)


@dataclass(frozen=True)
class IdSpec:
    cls: str
    slot: str  # identifier slot (or PK column for integer IDs)
    kind: IdKind
    prefixes: tuple[str, ...] = ()  # global: 2-letter; local: 3-letter


@dataclass(frozen=True)
class ColumnStorage:
    table: Table
    column: Column  # type: ignore[type-arg]


@dataclass(frozen=True)
class JoinStorage:
    table: Table
    owner_column: Column  # type: ignore[type-arg]
    value_column: Column  # type: ignore[type-arg]


Storage = ColumnStorage | JoinStorage


@dataclass(frozen=True)
class PermissibleValue:
    curie: str
    title: str | None
    description: str | None


@dataclass(frozen=True)
class CurieColumn:
    cls: str
    slot: str
    table: str
    column: str
    kind: CurieKind


class Model:
    """The CAM model as seen through SchemaView + SQLAlchemy."""

    def __init__(self, schema_view: SchemaView, settings: Settings) -> None:
        self.sv = schema_view
        self.settings = settings
        self.metadata = Base.metadata
        self.mappers: dict[str, Mapper[Any]] = {
            m.class_.__name__: m for m in Base.registry.mappers
        }

    # ----- classes and slots -------------------------------------------------

    @cached_property
    def classes(self) -> frozenset[str]:
        return frozenset(self.sv.all_classes())

    @cached_property
    def enums(self) -> frozenset[str]:
        return frozenset(self.sv.all_enums())

    @cached_property
    def table_classes(self) -> tuple[str, ...]:
        """LinkML classes that have their own (non-excluded) table, sorted."""
        excluded = set(self.settings.tables.exclude)
        return tuple(
            sorted(
                c
                for c in self.classes
                if c in self.metadata.tables and c not in excluded
            )
        )

    @cache  # noqa: B019 - Model instances live for the whole process
    def slots(self, cls: str) -> dict[str, SlotDefinition]:
        return {s.name: s for s in self.sv.class_induced_slots(cls)}

    def slot(self, cls: str, slot: str) -> SlotDefinition:
        try:
            return self.slots(cls)[slot]
        except KeyError:
            raise KeyError(f"{cls} has no slot {slot!r}") from None

    def range_info(self, cls: str, slot: str) -> RangeInfo:
        s = self.slot(cls, slot)
        ranges = [s.range, *(a.range for a in s.any_of or [])]
        enums = tuple(r for r in ranges if r in self.enums)
        if s.range in self.classes and s.range != CONCEPT_CLASS:
            return RangeInfo("entity", target=s.range)
        if CONCEPT_CLASS in ranges:
            return RangeInfo("concept", enums=enums)
        if s.range in self.enums:
            return RangeInfo("enum", enums=enums)
        if "uriorcurie" in ranges:
            return RangeInfo("uriorcurie", enums=enums)
        return RangeInfo("literal")

    def slot_unit(self, cls: str, slot: str) -> str | None:
        unit = self.slot(cls, slot).unit
        return unit.ucum_code if unit is not None else None

    def required_slots(self, cls: str) -> list[str]:
        return [name for name, s in self.slots(cls).items() if s.required]

    # ----- storage -----------------------------------------------------------

    def storage(self, cls: str, slot: str) -> Storage:
        """Where a slot's values live: a column of the class table, or a join table."""
        s = self.slot(cls, slot)
        table = self.metadata.tables[cls]
        if not s.multivalued:
            if slot not in table.columns:
                raise KeyError(f"{cls}.{slot} has no column in {table.name}")
            return ColumnStorage(table, table.columns[slot])

        mapper = self.mappers[cls]
        descriptor = mapper.all_orm_descriptors.get(slot)
        if isinstance(descriptor, AssociationProxy):
            # value list: relationship to an association class + proxy to its value attribute
            rel = mapper.relationships[descriptor.target_collection]
            join = rel.mapper.local_table
            value = join.columns[descriptor.value_attr]
        elif (
            slot in mapper.relationships
            and mapper.relationships[slot].secondary is not None
        ):
            # entity list: many-to-many through a secondary table
            rel = mapper.relationships[slot]
            join = rel.secondary  # type: ignore[assignment]
            target = rel.mapper.local_table
            value = next(
                c
                for c in join.columns
                if any(fk.column.table is target for fk in c.foreign_keys)
            )
        else:
            raise KeyError(f"can't find the join table for {cls}.{slot}")
        assert isinstance(join, Table)
        owner = next(
            c
            for c in join.columns
            if c is not value and any(fk.column.table is table for fk in c.foreign_keys)
        )
        assert isinstance(value, Column) and isinstance(owner, Column)
        return JoinStorage(join, owner, value)

    def required_storage(
        self, cls: str, multivalued: bool | None = None
    ) -> dict[str, Storage]:
        """Required slots of a class mapped to their storage (R2 uses multivalued=True)."""
        out = {}
        for name in self.required_slots(cls):
            if (
                multivalued is not None
                and bool(self.slot(cls, name).multivalued) != multivalued
            ):
                continue
            out[name] = self.storage(cls, name)
        return out

    # ----- identifiers -------------------------------------------------------

    def id_spec(self, cls: str) -> IdSpec:
        ids = self.settings.ids
        identifiers = [s for s in self.slots(cls).values() if s.identifier]
        if cls in REFERENCE_CLASSES:
            return IdSpec(cls, identifiers[0].name, "reference")
        if not identifiers:
            pk = list(self.metadata.tables[cls].primary_key.columns)
            if len(pk) == 1 and isinstance(pk[0].type, Integer):
                return IdSpec(cls, pk[0].name, "int")
            raise ValueError(f"{cls}: no identifier slot and no integer PK")

        ident = identifiers[0]
        ranges = [ident.range, *(a.range for a in ident.any_of or [])]
        prefixes = tuple(
            m.group(1) for r in ranges if (m := GLOBAL_ID_TYPE.match(str(r)))
        )
        if prefixes:
            return IdSpec(cls, ident.name, "global", prefixes)
        if ident.range in self.classes:
            return IdSpec(cls, ident.name, "parent")
        if cls in ids.local_prefixes:
            return IdSpec(cls, ident.name, "local", (ids.local_prefixes[cls],))
        if cls in ids.doi_classes:
            return IdSpec(cls, ident.name, "doi")
        raise ValueError(
            f"{cls}.{ident.name}: no ID scheme (add it to ids.local_prefixes or ids.doi_classes)"
        )

    def global_id_prefixes(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        """class -> (ID slot, allowed prefixes) for classes with GlobalIDs."""
        out = {}
        for cls in self.table_classes:
            spec = self.id_spec(cls)
            if spec.kind == "global":
                out[cls] = (spec.slot, spec.prefixes)
        return out

    # ----- enums and coded columns ---------------------------------------------

    @cache  # noqa: B019
    def enum_values(self, enum: str) -> dict[str, PermissibleValue]:
        pvs = self.sv.get_enum(enum).permissible_values or {}
        return {k: PermissibleValue(k, v.title, v.description) for k, v in pvs.items()}

    def find_permissible_value(self, curie: str) -> PermissibleValue | None:
        """The curie as a permissible value of any enum (ConceptRegistry step 3)."""
        for enum in sorted(self.enums):
            pv = self.enum_values(enum).get(curie)
            if pv is not None:
                return pv
        return None

    @cached_property
    def curie_columns(self) -> tuple[CurieColumn, ...]:
        """Every column holding coded curies (R9): Concept FKs, enums, listed uriorcurie slots."""
        coded = set(self.settings.concepts.coded_uriorcurie_slots)
        unknown = {
            c
            for c in coded
            if c.partition(".")[0] not in self.classes
            or c.partition(".")[2] not in self.slots(c.partition(".")[0])
        }
        if unknown:
            raise ValueError(
                f"concepts.coded_uriorcurie_slots names unknown slots: {sorted(unknown)}"
            )

        found: dict[tuple[str, str], CurieColumn] = {}
        for cls in self.table_classes:
            for name in self.slots(cls):
                try:
                    store = self.storage(cls, name)
                except KeyError:
                    continue  # inlined objects (e.g. File.hash) or slots without SQL storage
                column = (
                    store.column
                    if isinstance(store, ColumnStorage)
                    else store.value_column
                )
                kind: CurieKind | None = None
                if any(
                    fk.column.table.name == CONCEPT_CLASS for fk in column.foreign_keys
                ):
                    kind = "concept_fk"
                elif isinstance(column.type, Enum):
                    kind = "enum"
                elif f"{cls}.{name}" in coded:
                    kind = "uriorcurie"
                if kind is not None and cls not in REFERENCE_CLASSES:
                    found[(store.table.name, column.name)] = CurieColumn(
                        cls, name, store.table.name, column.name, kind
                    )
        return tuple(found[k] for k in sorted(found))


@cache
def get_model() -> Model:
    return Model(SchemaView(str(SCHEMA_PATH)), get_settings())
