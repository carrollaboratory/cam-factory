"""Per-class LinkML YAML (DESIGN §9, TODO 5.3), built generically from SchemaView.

- keys in the class's induced-slot order; NULLs and empty lists omitted
- join tables folded back into multivalued slots (values sorted)
- references to classes with a LinkML identifier are written as IDs; classes
  without one (HashDigest, Investigator, Publication) are inlined as objects
- yaml/<Class>.yaml holds a list of instances; tiny also writes
  examples/<Class>-001.yaml (one instance) for the model repo
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from sqlalchemy import Connection, select

from cam_testdata.schema_introspect import ColumnStorage, JoinStorage, Model


class YamlExporter:
    def __init__(self, conn: Connection, model: Model) -> None:
        self.conn = conn
        self.model = model
        self._rows: dict[str, dict[Any, dict[str, Any]]] = {}
        self._joins: dict[tuple[str, str], dict[Any, list[Any]]] = {}

    # ----- cached reads ----------------------------------------------------------

    def rows(self, cls: str) -> dict[Any, dict[str, Any]]:
        if cls not in self._rows:
            table = self.model.metadata.tables[cls]
            pk = next(iter(table.primary_key.columns))
            result = self.conn.execute(select(table).order_by(pk)).mappings()
            self._rows[cls] = {r[pk.name]: dict(r) for r in result}
        return self._rows[cls]

    def join_values(
        self, cls: str, slot: str, store: JoinStorage
    ) -> dict[Any, list[Any]]:
        if (cls, slot) not in self._joins:
            grouped: dict[Any, list[Any]] = defaultdict(list)
            stmt = select(store.owner_column, store.value_column).order_by(
                store.owner_column, store.value_column
            )
            for owner, value in self.conn.execute(stmt):
                grouped[owner].append(value)
            self._joins[(cls, slot)] = grouped
        return self._joins[(cls, slot)]

    def _has_identifier(self, cls: str) -> bool:
        return any(s.identifier for s in self.model.slots(cls).values())

    # ----- instances ---------------------------------------------------------------

    def instance(self, cls: str, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        table = self.model.metadata.tables[cls]
        pk_value = row[next(iter(table.primary_key.columns)).name]
        for name in self.model.slots(cls):
            slot = str(name)  # SchemaView returns a str subclass ruamel can't dump
            try:
                store = self.model.storage(cls, slot)
            except KeyError:
                continue
            target = self.model.range_info(cls, slot).target
            inline = target is not None and not self._has_identifier(target)
            if isinstance(store, ColumnStorage):
                value = row.get(store.column.name)
                if value is None:
                    continue
                out[slot] = (
                    self.instance(target, self.rows(target)[value])
                    if inline and target
                    else value
                )
            else:
                values = self.join_values(cls, slot, store).get(pk_value, [])
                if not values:
                    continue
                if inline and target:
                    out[slot] = [
                        self.instance(target, self.rows(target)[v]) for v in values
                    ]
                else:
                    out[slot] = list(values)
        return out

    def class_instances(self, cls: str) -> list[dict[str, Any]]:
        return [self.instance(cls, row) for row in self.rows(cls).values()]


def _dump(data: Any, path: Path) -> None:
    yaml = YAML()
    yaml.width = 4096
    yaml.representer.ignore_aliases = lambda *_: (
        True
    )  # never emit &anchors for repeated objects
    with path.open("w", encoding="utf-8", newline="") as fh:
        yaml.dump(data, fh)


def export_yaml(
    conn: Connection, model: Model, yaml_dir: Path, examples_dir: Path | None = None
) -> list[Path]:
    exporter = YamlExporter(conn, model)
    yaml_dir.mkdir(parents=True, exist_ok=True)
    if examples_dir is not None:
        examples_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for cls in model.table_classes:
        instances = exporter.class_instances(cls)
        if not instances:
            continue
        path = yaml_dir / f"{cls}.yaml"
        _dump(instances, path)
        written.append(path)
        if examples_dir is not None:
            example = examples_dir / f"{cls}-001.yaml"
            _dump(instances[0], example)
            written.append(example)
    return written
