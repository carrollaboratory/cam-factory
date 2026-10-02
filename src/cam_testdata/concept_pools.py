"""Load and validate config/concept_pools.yaml (TODO 2.2)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from cam_testdata.concepts import ConceptRegistry, is_uri
from cam_testdata.schema_introspect import Model
from cam_testdata.settings import PROJECT_ROOT

POOLS_PATH = PROJECT_ROOT / "config" / "concept_pools.yaml"


class PoolError(ValueError):
    pass


@dataclass(frozen=True)
class ConceptPools:
    pools: dict[str, tuple[str, ...]]  # "Class.slot" -> curies
    bundles: dict[str, tuple[dict[str, Any], ...]]

    def pool(self, cls: str, slot: str) -> tuple[str, ...]:
        try:
            return self.pools[f"{cls}.{slot}"]
        except KeyError:
            raise KeyError(f"no concept pool for {cls}.{slot}") from None

    def curies(self) -> list[tuple[str, str]]:
        """Every (curie, "Class.slot") referenced by pools and bundles."""
        out = [(c, key) for key, values in self.pools.items() for c in values]
        for items in self.bundles.values():
            for item in items:
                out += [
                    (v, k) for k, v in item.items() if "." in k and isinstance(v, str)
                ]
        return out


def _check_entry(
    model: Model, registry: ConceptRegistry, key: str, value: str, where: str
) -> str | None:
    """Return a hard error for an entry, or None. Unresolved concepts are recorded, not raised."""
    cls, _, slot = key.partition(".")
    if cls not in model.classes or slot not in model.slots(cls):
        return f"{where}: {key} isn't a slot in the model"
    info = model.range_info(cls, slot)
    if info.kind == "enum":
        allowed = {pv for enum in info.enums for pv in model.enum_values(enum)}
        if value not in allowed:
            return f"{where}: {value} isn't a permissible value of {'/'.join(info.enums)} ({key})"
    elif info.kind in ("concept", "uriorcurie"):
        if not is_uri(value):
            registry.resolve(value, f"pool:{key}")
    # entity / literal slots (e.g. File.file_extension) aren't coded; nothing to check
    return None


def load_pools(
    model: Model, registry: ConceptRegistry, path: Path = POOLS_PATH
) -> ConceptPools:
    """Load pools, failing on structural errors and enum-binding violations."""
    with path.open() as fh:
        data = YAML(typ="safe").load(fh) or {}

    errors: list[str] = []
    pools: dict[str, tuple[str, ...]] = {}
    for key, values in (data.get("pools") or {}).items():
        values = [str(v) for v in values or []]
        if len(set(values)) != len(values):
            errors.append(f"pools.{key}: duplicate entries")
        for value in values:
            if (
                err := _check_entry(model, registry, key, value, f"pools.{key}")
            ) is not None:
                errors.append(err)
        pools[key] = tuple(values)

    bundles: dict[str, tuple[dict[str, Any], ...]] = {}
    for name, items in (data.get("bundles") or {}).items():
        for i, item in enumerate(items or []):
            for key, value in item.items():
                if not ("." in key and isinstance(value, str)):
                    continue  # plain attribute (extension, value range)
                where = f"bundles.{name}[{i}]"
                if (
                    err := _check_entry(model, registry, key, value, where)
                ) is not None:
                    errors.append(err)
        bundles[name] = tuple(dict(item) for item in items or [])

    if errors:
        raise PoolError("concept pool errors:\n  " + "\n  ".join(errors))
    return ConceptPools(pools, bundles)
