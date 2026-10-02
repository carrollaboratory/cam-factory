"""Load a declarative scenario YAML (DESIGN §8.2) through the factories (TODO 5.1).

    records:
      <Class>:
        - key: <fixture-local key>      # handle = <profile>/<Class>/<key>
          id: <optional pinned ID>
          <slot>: <value>               # LinkML slot names

Slots ranged to an entity class take keys; Concept / enum / uriorcurie slots
take curies. Omitted fields are the factories' business. study_id and
access_policy_id are inherited from the scoping parent; an explicit value
that disagrees is an error. One-to-one classes (Demographics, StudyMetadata)
use their parent's key. Errors name the record: `Class[key].slot: ...`.
"""

from collections import Counter
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

import factory
from ruamel.yaml import YAML

from cam_testdata.build import Build
from cam_testdata.factories import all_factories
from cam_testdata.factories.base import link, pk_of
from cam_testdata.ids import IdError
from cam_testdata.schema_introspect import Model

SCOPE_SLOTS = ("study_id", "access_policy_id")

# Entity slot -> factory parameter, where it isn't the slot minus "_id".
# Slots with no matching parameter are set as plain column values (the target's PK).
REF_PARAMS: dict[tuple[str, str], str] = {
    ("Study", "parent_study"): "parent",
    ("Study", "access_policy_id"): "access_policy",
    ("StudyMetadata", "vbr_id"): "vbr",
    ("Encounter", "encounter_definition_id"): "definition",
    ("FamilyRelationship", "family_member_id"): "member",
    ("Sample", "parent_sample_id"): "parent",
    ("Sample", "biospecimen_collection_id"): "collection",
    ("Assay", "activity_definition_id"): "activity",
    ("Dataset", "do_id"): "doi",
}


class LoaderError(ValueError):
    pass


@dataclass
class LoadedScenario:
    build: Build
    objects: dict[tuple[str, str], Any] = field(
        default_factory=dict
    )  # (Class, key) -> object
    declared: Counter[str] = field(
        default_factory=Counter
    )  # Class -> records in the YAML

    def __getitem__(self, ref: tuple[str, str]) -> Any:
        return self.objects[ref]


def _factories(model: Model) -> dict[str, Any]:
    """Entity factories by LinkML class name (join-table factories excluded)."""
    classes = set(model.table_classes)
    return {
        f._meta.model.__name__: f
        for f in all_factories()
        if f._meta.model.__name__ in classes
    }


def _param_default(fac: Any, name: str) -> Any:
    param = fac._meta.parameters.get(name)
    return getattr(param, "value", None) if param is not None else None


def _auto_parents(fac: Any) -> dict[str, str | None]:
    """Params that would create a parent if not passed: name -> Maybe condition (or None)."""
    out: dict[str, str | None] = {}
    for name in fac._meta.parameters:
        value = _param_default(fac, name)
        if isinstance(value, factory.SubFactory):
            out[name] = None
        elif isinstance(value, factory.Maybe) and isinstance(
            value.no, factory.SubFactory
        ):
            out[name] = value.decider.attribute_name
    return out


def _file_kind(build: Build, record: dict[str, Any]) -> dict[str, Any]:
    """File: use the file_kinds bundle matching an explicit format, so unspecified
    fields come from the right bundle instead of a random one."""
    if "format" not in record:
        return {}
    for kind in build.pools.bundles.get("file_kinds", ()):
        if kind.get("File.format") == record["format"]:
            return {"kind": dict(kind)}
    return {"kind": {"File.file_extension": record.get("file_extension", "")}}


EXTRA_KWARGS = {"File": _file_kind}


class ScenarioLoader:
    def __init__(self, build: Build, path: Path) -> None:
        self.build = build
        self.model: Model = build.model
        self.path = path
        with path.open() as fh:
            doc = YAML(typ="safe").load(fh) or {}
        self.records: dict[str, list[dict[str, Any]]] = doc.get("records") or {}
        self.factories = _factories(self.model)
        self.result = LoadedScenario(build)

    # ----- validation ------------------------------------------------------------

    def _err(self, cls: str, key: str, slot: str | None, message: str) -> LoaderError:
        where = f"{cls}[{key}]" + (f".{slot}" if slot else "")
        return LoaderError(f"{self.path.name}: {where}: {message}")

    def validate(self) -> None:
        keys: dict[str, set[str]] = {}
        for cls, rows in self.records.items():
            if cls not in self.factories:
                raise LoaderError(f"{self.path.name}: unknown class {cls!r}")
            seen: set[str] = set()
            for row in rows:
                key = row.get("key")
                if not key:
                    raise LoaderError(f"{self.path.name}: a {cls} record has no key")
                if key in seen:
                    raise self._err(cls, key, None, "duplicate key")
                seen.add(str(key))
            keys[cls] = seen
        for cls, rows in self.records.items():
            slots = self.model.slots(cls)
            for row in rows:
                for slot, value in row.items():
                    if slot in ("key", "id"):
                        continue
                    if slot not in slots:
                        raise self._err(cls, row["key"], slot, "unknown slot")
                    info = self.model.range_info(cls, slot)
                    if info.kind != "entity" or info.target is None:
                        continue
                    for v in value if isinstance(value, list) else [value]:
                        if isinstance(v, dict):
                            continue  # inlined object (File.hash)
                        if str(v) not in keys.get(info.target, set()):
                            raise self._err(
                                cls,
                                row["key"],
                                slot,
                                f"unknown key {v!r} for {info.target}",
                            )

    # ----- loading -----------------------------------------------------------------

    def load(self) -> LoadedScenario:
        self.validate()
        order, cyclic = self._class_order()
        deferred_links: list[tuple[str, str, Any, str, list[Any]]] = []
        deferred_columns: list[tuple[str, str, Any, str, str, str]] = []

        with self.build.active():
            for cls in order:
                for row in self._parents_first(cls, self.records[cls]):
                    obj = self._create(
                        cls, row, cyclic.get(cls, []), deferred_links, deferred_columns
                    )
                    self.result.objects[(cls, str(row["key"]))] = obj
                    self.result.declared[cls] += 1
            for cls, key, obj, slot, target_cls, target_key in deferred_columns:
                setattr(obj, slot, pk_of(self.result[(target_cls, target_key)]))
            for cls, key, obj, slot, values in deferred_links:
                link(
                    obj,
                    slot,
                    [
                        self.result[
                            (self.model.range_info(cls, slot).target or "", str(v))
                        ]
                        for v in values
                    ],
                )
            self._fill_participant_counts()
        self._check_no_auto_parents()
        return self.result

    def _class_order(self) -> tuple[list[str], dict[str, list[str]]]:
        """Classes so that single-valued references point backwards. A cycle is broken
        at a non-scoping slot (Study.do_id), which is then set after both exist."""
        edges: dict[tuple[str, str], str] = {}  # (cls, slot) -> target class
        for cls, rows in self.records.items():
            used = {slot for row in rows for slot in row}
            for slot in used:
                if slot in ("key", "id") or self.model.slot(cls, slot).multivalued:
                    continue
                target = self.model.range_info(cls, slot).target
                if target and target != cls and target in self.records:
                    edges[(cls, slot)] = target
            spec = self.model.id_spec(cls)
            if spec.kind == "parent":
                target = self.model.range_info(cls, spec.slot).target
                if target and target in self.records:
                    edges[(cls, spec.slot)] = target
        cyclic: dict[str, list[str]] = {}
        while True:
            graph: dict[str, set[str]] = {cls: set() for cls in sorted(self.records)}
            for (cls, _), target in edges.items():
                graph[cls].add(target)
            try:
                return list(TopologicalSorter(graph).static_order()), cyclic
            except CycleError as exc:
                cycle = set(exc.args[1])
                breakable = sorted(
                    (cls, slot)
                    for (cls, slot), t in edges.items()
                    if cls in cycle
                    and t in cycle
                    and slot not in SCOPE_SLOTS
                    and self.model.storage(cls, slot).table.c[slot].nullable
                )
                if not breakable:
                    raise LoaderError(
                        f"{self.path.name}: unbreakable reference cycle among {sorted(cycle)}"
                    ) from exc
                cls, slot = breakable[0]
                cyclic.setdefault(cls, []).append(slot)
                del edges[(cls, slot)]

    def _parents_first(
        self, cls: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self_slots = [
            s
            for s in self.model.slots(cls)
            if not self.model.slot(cls, s).multivalued
            and self.model.range_info(cls, s).target == cls
        ]
        if not self_slots:
            return rows
        by_key = {str(r["key"]): r for r in rows}
        ordered: list[dict[str, Any]] = []
        done: set[str] = set()

        def visit(row: dict[str, Any], path: frozenset[str]) -> None:
            key = str(row["key"])
            if key in done:
                return
            if key in path:
                raise self._err(cls, key, None, "self-reference cycle")
            for slot in self_slots:
                if row.get(slot) is not None:
                    visit(by_key[str(row[slot])], path | {key})
            done.add(key)
            ordered.append(row)

        for row in rows:
            visit(row, frozenset())
        return ordered

    def _create(
        self,
        cls: str,
        row: dict[str, Any],
        cyclic_slots: list[str],
        deferred_links: list[Any],
        deferred_columns: list[Any],
    ) -> Any:
        fac = self.factories[cls]
        key = str(row["key"])
        params = set(fac._meta.parameters)
        kwargs: dict[str, Any] = {"handle": self.build.handle(cls, key)}
        if "id" in row:
            kwargs["pinned_id"] = row["id"]
        kwargs.update(EXTRA_KWARGS.get(cls, lambda b, r: {})(self.build, row))

        spec = self.model.id_spec(cls)
        if (
            spec.kind == "parent"
        ):  # one-to-one: the identifier slot points at the parent with the same key
            parent_cls = self.model.range_info(cls, spec.slot).target or ""
            if (parent_cls, key) not in self.result.objects:
                raise self._err(
                    cls, key, spec.slot, f"no {parent_cls} with key {key!r}"
                )
            kwargs[spec.slot.removesuffix("_id")] = self.result[(parent_cls, key)]

        explicit_scope: dict[str, Any] = {}
        for slot, value in row.items():
            if slot in ("key", "id"):
                continue
            s = self.model.slot(cls, slot)
            info = self.model.range_info(cls, slot)
            if info.kind != "entity":
                kwargs[slot] = value
                continue
            if s.multivalued:
                if value and all(isinstance(v, dict) for v in value):
                    kwargs[slot] = value  # inlined objects
                else:
                    deferred_links.append((cls, key, None, slot, list(value or [])))
                    # suppress any default; linked after everything exists
                    kwargs[slot] = []
                continue
            target = self.result.objects.get((info.target or "", str(value)))
            if slot in cyclic_slots:
                deferred_columns.append((cls, key, None, slot, info.target, str(value)))
                continue
            if slot in SCOPE_SLOTS:
                scope_default = _param_default(fac, "scope")
                if slot == "study_id" and isinstance(scope_default, factory.SubFactory):
                    kwargs["scope"] = target  # top-level record: the study is its scope
                elif slot == "access_policy_id" and "access_policy" in params:
                    kwargs["access_policy"] = target
                else:
                    explicit_scope[slot] = (value, target)
                continue
            param = REF_PARAMS.get((cls, slot), slot.removesuffix("_id"))
            if param in params:
                kwargs[param] = target
            else:
                kwargs[slot] = pk_of(target)

        for param, condition in _auto_parents(fac).items():
            if param in kwargs or (
                condition is not None and kwargs.get(condition) is not None
            ):
                continue
            slot = next(
                (s for (c, s), p in REF_PARAMS.items() if c == cls and p == param),
                f"{param}_id",
            )
            if param == "scope":
                slot = "study_id"
            raise self._err(cls, key, slot, "required (no parent to inherit it from)")

        try:
            obj = fac(**kwargs)
        except IdError as exc:
            raise self._err(
                cls, key, "id" if "pinned_id" in kwargs else None, str(exc)
            ) from exc
        # fill in the object for deferred work recorded before it existed
        for items in (deferred_links, deferred_columns):
            for i, item in enumerate(items):
                if item[0] == cls and item[1] == key and item[2] is None:
                    items[i] = (item[0], item[1], obj, *item[3:])

        for slot, (value, target) in explicit_scope.items():
            expected = getattr(target, slot) if slot == "study_id" else pk_of(target)
            if getattr(obj, slot) != expected:
                raise self._err(
                    cls,
                    key,
                    slot,
                    f"{value!r} conflicts with the inherited value {getattr(obj, slot)!r}",
                )
        return obj

    def _fill_participant_counts(self) -> None:
        """StudyMetadata.actual_number_of_participants, unless given (R8)."""
        from cam_testdata.validate.integrity import PARTICIPANT

        counts: Counter[str] = Counter(
            obj.study_id
            for (cls, _), obj in self.result.objects.items()
            if cls == "Subject" and obj.subject_type == PARTICIPANT
        )
        for row in self.records.get("StudyMetadata", []):
            if "actual_number_of_participants" not in row:
                obj = self.result[("StudyMetadata", str(row["key"]))]
                obj.actual_number_of_participants = counts[obj.study_id]

    def _check_no_auto_parents(self) -> None:
        """Every entity row the build collected must come from the YAML (inlined hashes excepted)."""
        built: Counter[str] = Counter(type(o).__name__ for o in self.build.objects)
        hashes = sum(len(r.get("hash") or ()) for r in self.records.get("File", []))
        expected = Counter(self.result.declared)
        default_hashes = sum(1 for r in self.records.get("File", []) if "hash" not in r)
        if hashes or default_hashes:
            expected["HashDigest"] += hashes + default_hashes
        extra = {
            cls: built[cls] - expected[cls]
            for cls in expected | built
            if cls in self.factories and built[cls] != expected[cls]
        }
        if extra:
            raise LoaderError(
                f"{self.path.name}: built rows don't match the scenario (built - declared): {extra}"
            )


def load_scenario(build: Build, path: Path) -> LoadedScenario:
    return ScenarioLoader(build, path).load()
