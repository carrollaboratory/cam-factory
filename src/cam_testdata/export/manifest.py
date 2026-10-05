"""id_map.csv, manifest.json (DESIGN §5.3, §9; TODO 5.5).

The manifest deliberately leaves out the generator's git commit: tiny and small
outputs are committed, and a per-commit value would make every build differ.
"""

import csv
import hashlib
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, func, select

from cam_testdata import db
from cam_testdata.build import Build
from cam_testdata.drift import model_shape
from cam_testdata.factories.base import pk_of
from cam_testdata.schema_introspect import JoinStorage, Model
from cam_testdata.settings import SCHEMA_PATH

PACKAGES = (
    "common-access-model",
    "sqlalchemy",
    "psycopg",
    "factory-boy",
    "faker",
    "linkml",
    "linkml-runtime",
)


def id_map_rows(build: Build, conn: Connection, model: Model) -> list[dict[str, str]]:
    """handle, table, id, external_id for every record that has a handle."""
    external: dict[tuple[str, str], str] = {}
    for cls in model.table_classes:
        if "external_id" not in model.slots(cls):
            continue
        store = model.storage(cls, "external_id")
        assert isinstance(store, JoinStorage)
        stmt = select(store.owner_column, func.min(store.value_column)).group_by(
            store.owner_column
        )
        for owner, ext in conn.execute(stmt):
            external[(cls, str(owner))] = ext
    rows = []
    for obj in build.objects:
        handle = build.handles.get(id(obj))
        if handle is None:
            continue
        table = obj.__table__.name
        key = str(pk_of(obj))
        rows.append(
            {
                "handle": handle,
                "table": table,
                "id": key,
                "external_id": external.get((table, key), ""),
            }
        )
    return sorted(rows, key=lambda r: r["handle"])


def write_id_map(rows: list[dict[str, str]], path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["handle", "table", "id", "external_id"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def fhir_counts(conn: Connection, model: Model) -> dict[str, int]:
    """Rows per GlobalID prefix: the FHIR resources the dbt pipeline should produce."""
    counts: Counter[str] = Counter()
    for cls in model.table_classes:
        spec = model.id_spec(cls)
        if spec.kind != "global":
            continue
        table = model.metadata.tables[cls]
        for value in conn.execute(select(table.c[spec.slot])).scalars():
            counts[str(value).split("-", 1)[0]] += 1
    return dict(sorted(counts.items()))


def row_counts(conn: Connection, model: Model) -> dict[str, int]:
    return {
        t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
        for t in db.registry_tables(model.settings)
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    *,
    build: Build,
    conn: Connection,
    model: Model,
    out_dir: Path,
    artifacts: list[Path],
    features: dict[str, list[str]],
    id_rows: list[dict[str, str]],
    pg_dump_version: str,
) -> dict[str, Any]:
    # one-to-one records (Demographics, StudyMetadata) share their parent's ID; name the parent
    handle_of = {
        r["id"]: r["handle"]
        for r in id_rows
        if model.id_spec(r["table"]).kind != "parent"
    }
    return {
        "profile": build.profile,
        "seed": build.seed,
        "model": {
            "common_access_model": version("common-access-model"),
            "schema_file": SCHEMA_PATH.resolve().name,
            "schema_sha256": sha256(SCHEMA_PATH),
            "shape": model_shape(model, model.settings),  # for check-drift
        },
        "packages": {name: version(name) for name in PACKAGES},
        "pg_dump": pg_dump_version,
        "row_counts": row_counts(conn, model),
        "fhir_counts_by_prefix": fhir_counts(conn, model),
        "coverage_features": {
            name: sorted(handle_of.get(k, k) for k in keys)
            for name, keys in sorted(features.items())
        },
        "artifacts": {
            str(p.relative_to(out_dir)): sha256(p) for p in sorted(artifacts)
        },
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    return path
