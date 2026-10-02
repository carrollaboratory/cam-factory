"""Factory base and shared declarations (DESIGN §8).

Factories never touch the session: `create()` hands the object to the active
Build (cam_testdata.build), which inserts everything in FK order later.

Conventions every entity factory follows:
- `handle` (Param): stable readable key; drives the ID, Faker filler, pool
  choices, and the default external_id.
- `pinned_id` (Param): use this ID instead of minting one (DESIGN §5.1).
- `scope` (Param): the object whose study_id / access_policy_id this record
  inherits (R1). Usually the parent record, or the Study for top-level records.
- Many-valued slots are passed under their LinkML slot names as lists
  (`race=[...]`, `principal_investigator=[pi]`); a post-generation hook
  creates the join-table rows. Never populate secondary= relationships directly.
- Every column is declared, even when its default is None, so the drift check
  (cam_testdata.drift) can tell a new model column from a deliberate omission.
"""

from typing import Any

import factory
from sqlalchemy import inspect

from cam_testdata.build import current_build

PRESENT = "snomedct:410515003"  # Known present
ABSENT = "snomedct:410516002"  # Known absent


class BaseFactory(factory.Factory):  # type: ignore[type-arg]
    """Creates transient model objects and registers them with the active Build."""

    class Meta:
        abstract = True

    class Params:
        handle = None

    cam_handle = factory.SelfAttribute("handle")

    @classmethod
    def _create(cls, model_class: type, *args: Any, **kwargs: Any) -> Any:
        # cam_* declarations aren't columns: keep them on the object for hooks.
        extras = {k: kwargs.pop(k) for k in list(kwargs) if k.startswith("cam_")}
        obj = model_class(*args, **kwargs)
        for key, value in extras.items():
            setattr(obj, f"_{key}", value)
        return current_build().collect(obj, extras.get("cam_handle"))

    @classmethod
    def _build(cls, model_class: type, *args: Any, **kwargs: Any) -> Any:
        """`.build()` returns an unregistered object (used for reference rows)."""
        for key in [k for k in kwargs if k.startswith("cam_")]:
            kwargs.pop(key)
        return model_class(*args, **kwargs)


# ----- declarations ----------------------------------------------------------


def default_handle(cls: str) -> Any:
    """A sequential handle for ad hoc use (tests); scenarios always pass one."""
    return factory.LazyAttributeSequence(
        lambda o, n: current_build().handle(cls, f"auto-{n:04d}")
    )


def minted_id(cls: str) -> Any:
    """The record's ID from its handle (or pinned_id), using the class's ID scheme."""

    def mint(o: Any) -> Any:
        build = current_build()
        spec = build.model.id_spec(cls)
        if spec.kind == "int":
            if o.pinned_id is not None:
                return build.ids.register_explicit_int(cls, int(o.pinned_id), o.handle)
            return build.ids.mint_int(cls, o.handle)
        if o.pinned_id is not None:
            prefixes = spec.prefixes if spec.kind == "global" else None
            return build.ids.register_explicit(str(o.pinned_id), o.handle, prefixes)
        if spec.kind == "global":
            prefix = getattr(o, "id_prefix", None) or spec.prefixes[0]
            if prefix not in spec.prefixes:
                raise ValueError(f"{cls}: id_prefix {prefix!r} not in {spec.prefixes}")
            return build.ids.mint_global(prefix, o.handle)
        if spec.kind == "local":
            return build.ids.mint_local(spec.prefixes[0], o.handle)
        if spec.kind == "doi":
            return build.ids.mint_doi(o.handle)
        raise ValueError(f"{cls}: ID kind {spec.kind!r} isn't minted; pass it")

    return factory.LazyAttribute(mint)


def filler(label: str, method: str, **kwargs: Any) -> Any:
    """Faker filler text, seeded by (seed, handle, label) so it never shifts."""
    return factory.LazyAttribute(
        lambda o: getattr(current_build().fake(o.handle, label), method)(**kwargs)
    )


def pooled(key: str) -> Any:
    """A deterministic choice from config/concept_pools.yaml pools[key]."""
    return factory.LazyAttribute(
        lambda o: (
            current_build().rng(o.handle, key).choice(current_build().pools.pools[key])
        )
    )


def from_scope(attr: str) -> Any:
    """study_id / access_policy_id inherited from `scope` (R1)."""
    return factory.LazyAttribute(
        lambda o: getattr(o.scope, attr) if o.scope is not None else None
    )


def pk_of(obj: Any) -> Any:
    """The single primary-key value of a model object."""
    values = inspect(obj).mapper.primary_key_from_instance(obj)
    if len(values) != 1:
        raise ValueError(f"{type(obj).__name__} has a composite key")
    return values[0]


def linked(slot: str) -> Any:
    """Post-generation hook: create join-table rows for a many-valued slot.

    Uses the list passed as `<slot>=[...]`, else the object's `cam_default_<slot>`.
    Entity values may be model objects or IDs.
    """

    def hook(obj: Any, create: bool, extracted: Any, **_: Any) -> None:
        if not create:
            return
        default = getattr(obj, f"_cam_default_{slot}", None)
        values = extracted if extracted is not None else default
        if values:
            link(obj, slot, list(values))

    return factory.PostGeneration(hook)


def link(owner: Any, slot: str, values: list[Any]) -> list[Any]:
    """Create association rows linking `owner` to `values` via the slot's join table."""
    from cam_testdata.factories.associations import association_factory
    from cam_testdata.schema_introspect import JoinStorage

    build = current_build()
    cls = type(owner).__name__
    store = build.model.storage(cls, slot)
    if not isinstance(store, JoinStorage):
        raise TypeError(f"{cls}.{slot} isn't stored in a join table")
    assoc = association_factory(store.table.name)
    owner_id = pk_of(owner)
    rows = []
    for value in values:
        target = pk_of(value) if hasattr(value, "__table__") else value
        cols = {store.owner_column.key: owner_id, store.value_column.key: target}
        rows.append(assoc(**cols))
    return rows


class RecordFactory(BaseFactory):
    """Base for classes with the Record mixin: scoping and a default external_id."""

    class Meta:
        abstract = True

    class Params:
        scope = None
        pinned_id = None

    study_id = from_scope("study_id")
    access_policy_id = from_scope("access_policy_id")
    cam_default_external_id = factory.LazyAttribute(
        lambda o: [current_build().external_id_uri(o.handle)]
    )
    external_id = linked("external_id")
