"""Find curies a profile needs that no input provides (TODO 2.5, DESIGN §7)."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from cam_testdata.concept_pools import load_pools
from cam_testdata.concepts import ConceptRegistry, is_uri, split_curie
from cam_testdata.schema_introspect import ColumnStorage, Model
from cam_testdata.settings import PROJECT_ROOT

SCENARIO_FILES = {"tiny": PROJECT_ROOT / "scenarios" / "tiny.yaml"}


@dataclass
class MissingReport:
    concepts: dict[str, dict[str, int]]  # curie -> {used_by: count}
    vocabularies: list[str]  # prefixes with resolvable concepts but no Vocabulary entry

    @property
    def ok(self) -> bool:
        return not self.concepts and not self.vocabularies


def _column_label(model: Model, cls: str, slot: str) -> str:
    store = model.storage(cls, slot)
    column = store.column if isinstance(store, ColumnStorage) else store.value_column
    return f"{store.table.name}.{column.name}"


def collect_record(
    model: Model, registry: ConceptRegistry, cls: str, record: dict[str, Any]
) -> None:
    """Resolve every coded value in one scenario record (recursing into inlined objects)."""
    coded = set(model.settings.concepts.coded_uriorcurie_slots)
    for slot, value in record.items():
        if slot in ("key", "id") or slot not in model.slots(cls):
            continue
        info = model.range_info(cls, slot)
        values = value if isinstance(value, list) else [value]
        if info.kind == "entity":
            for v in values:
                if (
                    isinstance(v, dict) and info.target
                ):  # inlined object, e.g. File.hash
                    collect_record(model, registry, info.target, v)
            continue
        if info.kind in ("concept", "enum") or f"{cls}.{slot}" in coded:
            label = _column_label(model, cls, slot)
            for v in values:
                if v is not None and not is_uri(str(v)):
                    registry.resolve(str(v), label)


def collect_scenario(model: Model, registry: ConceptRegistry, path: Path) -> None:
    with path.open() as fh:
        doc = YAML(typ="safe").load(fh) or {}
    for cls, records in (doc.get("records") or {}).items():
        for record in records or []:
            collect_record(model, registry, cls, record)


def find_missing(
    model: Model, registry: ConceptRegistry, profile: str
) -> MissingReport:
    load_pools(model, registry)  # pool entries are recorded as pool:<Class.slot>
    if profile in SCENARIO_FILES:
        collect_scenario(model, registry, SCENARIO_FILES[profile])
    _, missing_vocabs = registry.vocabularies_for(registry.used_concepts())
    return MissingReport(
        {c: dict(u) for c, u in registry.missing().items()}, missing_vocabs
    )


def write_report(
    model: Model, registry: ConceptRegistry, report: MissingReport, out_dir: Path
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "missing_concepts.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["curie", "used_by", "count"])
        for curie, uses in sorted(report.concepts.items()):
            for used_by, count in sorted(uses.items()):
                writer.writerow([curie, used_by, count])
        for prefix in report.vocabularies:
            writer.writerow([f"{prefix}:", "Vocabulary (no entry for this prefix)", 0])

    # A stub in data/vocab_gaps.yaml format: merge the entries, fill the nulls.
    declared = {
        str(p): str(v.prefix_reference) for p, v in model.sv.schema.prefixes.items()
    }
    stub: dict[str, dict[str, Any]] = {}

    def entry(prefix: str) -> dict[str, Any]:
        if prefix not in stub:
            existing = registry.vocabularies.get(prefix)
            stub[prefix] = {
                "name": existing.name if existing else None,
                "vocabulary_prefix": prefix,
                "vocabulary_uri": existing.vocabulary_uri
                if existing
                else declared.get(prefix),
                "fhir_system": existing.fhir_system if existing else None,
                "source": None,
                "codes": [],
            }
        return stub[prefix]

    for curie in sorted(report.concepts):
        entry(split_curie(curie)[0])["codes"].append(curie)
    for prefix in report.vocabularies:
        # list the codes that need it, so follow_up_codes.py pulls their definitions too
        entry(prefix)["codes"] += [
            c.concept_curie
            for c in registry.used_concepts()
            if c.vocabulary_prefix == prefix
        ]
    stub_path = out_dir / "vocab_gaps_stub.yaml"
    with stub_path.open("w") as fh:
        yaml = YAML()
        yaml.width = 4096
        if stub:
            fh.write(
                "# Merge into data/vocab_gaps.yaml, fill in the nulls, then run scripts/follow_up_codes.py\n"
            )
            yaml.dump(stub, fh)
        else:
            fh.write("# Nothing missing.\n")
    return csv_path, stub_path
