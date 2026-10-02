"""ConceptRegistry (DESIGN §7): resolve curies to Concept rows and track what's used.

Resolution order:
1. data/vocab_content.yaml            (source "vocab_content")
2. data/additional_vocab_content.yaml (source "extra"; the user's vocab_gaps pulls)
3. an enum permissible value in the schema (source "linkml_enum")
4. otherwise missing

Vocabularies come only from the two files (first file wins per prefix).
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from pathlib import Path

from ruamel.yaml import YAML

from cam_testdata.schema_introspect import Model, get_model
from cam_testdata.settings import PROJECT_ROOT

VOCAB_FILES = (
    (PROJECT_ROOT / "data" / "vocab_content.yaml", "vocab_content"),
    (PROJECT_ROOT / "data" / "additional_vocab_content.yaml", "extra"),
)

URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


class ConceptDataError(ValueError):
    pass


class PrefixCaseError(ConceptDataError):
    pass


@dataclass(frozen=True)
class VocabularyRecord:
    vocabulary_prefix: str
    name: str | None
    vocabulary_uri: str | None
    vocabulary_id: str | None
    fhir_system: str | None
    description: str | None
    version: str | None
    vocabulary_source: str | None
    source: str  # which input file

    def row(self) -> dict[str, str | None]:
        return {
            f.name: getattr(self, f.name) for f in fields(self) if f.name != "source"
        }


@dataclass(frozen=True)
class ConceptRecord:
    concept_curie: str
    vocabulary_prefix: str
    concept_code: str
    display: str | None
    definition: str | None
    concept_id: int | None
    source: str  # vocab_content | extra | linkml_enum

    def row(self) -> dict[str, str | int | None]:
        return {
            f.name: getattr(self, f.name) for f in fields(self) if f.name != "source"
        }


def is_uri(value: str) -> bool:
    """Full URIs (scheme://...) are exempt from concept resolution (R9)."""
    return bool(URI.match(value))


def split_curie(curie: str) -> tuple[str, str]:
    prefix, sep, local = curie.partition(":")
    if not sep or not prefix or not local:
        raise ConceptDataError(f"not a curie: {curie!r}")
    return prefix, local


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None  # R12: never carry '' forward


class ConceptRegistry:
    def __init__(
        self,
        model: Model | None = None,
        vocab_files: tuple[tuple[Path, str], ...] = VOCAB_FILES,
    ) -> None:
        self.model = model or get_model()
        self._declared = {p.lower(): p for p in self.model.sv.schema.prefixes}
        self.vocabularies: dict[str, VocabularyRecord] = {}
        self.concepts: dict[str, ConceptRecord] = {}
        self.conflicts: list[str] = []  # curies defined in more than one file
        self._usage: dict[str, Counter[str]] = defaultdict(Counter)
        self._missing: dict[str, Counter[str]] = defaultdict(Counter)
        for path, source in vocab_files:
            if path.exists():
                self._load_file(path, source)

    # ----- loading -------------------------------------------------------------

    def _load_file(self, path: Path, source: str) -> None:
        with path.open() as fh:
            data = YAML(typ="safe").load(fh) or {}
        problems = []
        for key, entry in data.items():
            prefix = str(entry.get("vocabulary_prefix") or key)
            problem = self._case_problem(prefix)
            if problem:
                problems.append(f"{path.name}: vocabulary {problem}")
                continue
            if prefix not in self.vocabularies:
                self.vocabularies[prefix] = VocabularyRecord(
                    vocabulary_prefix=prefix,
                    **{
                        f.name: _blank_to_none(entry.get(f.name))
                        for f in fields(VocabularyRecord)
                        if f.name not in ("vocabulary_prefix", "source")
                    },
                    source=source,
                )
            for code in entry.get("codes") or []:
                curie = str(code["concept_curie"])
                if curie in self.concepts:
                    self.conflicts.append(
                        f"{curie} ({self.concepts[curie].source} kept, {source} ignored)"
                    )
                    continue
                self.concepts[curie] = ConceptRecord(
                    concept_curie=curie,
                    vocabulary_prefix=str(code.get("vocabulary_prefix") or prefix),
                    concept_code=str(code.get("concept_code") or split_curie(curie)[1]),
                    display=_blank_to_none(code.get("display")),
                    definition=_blank_to_none(code.get("definition")),
                    concept_id=code.get("concept_id"),
                    source=source,
                )
        if problems:
            raise PrefixCaseError("; ".join(problems))

    def _case_problem(self, prefix: str) -> str | None:
        declared = self._declared.get(prefix.lower())
        if declared is not None and declared != prefix:
            return (
                f"prefix {prefix!r} differs only in case from the schema's {declared!r}"
            )
        return None

    # ----- resolution ----------------------------------------------------------

    def resolve(self, curie: str, used_by: str | None = None) -> ConceptRecord | None:
        """Resolve a curie, recording who asked. Returns None if missing (or a full URI)."""
        if is_uri(curie):
            return None
        prefix, local = split_curie(curie)
        problem = self._case_problem(prefix)
        if problem:
            raise PrefixCaseError(f"{curie} ({used_by or 'unknown use'}): {problem}")
        if used_by:
            self._usage[curie][used_by] += 1

        record = self.concepts.get(curie)
        if record is None:
            pv = self.model.find_permissible_value(curie)
            if pv is not None:
                record = ConceptRecord(
                    concept_curie=curie,
                    vocabulary_prefix=prefix,
                    concept_code=local,
                    display=_blank_to_none(pv.title),
                    definition=_blank_to_none(pv.description),
                    concept_id=None,
                    source="linkml_enum",
                )
                self.concepts[curie] = record
        if record is None:
            self._missing[curie][used_by or "unknown"] += 1
        return record

    # ----- reporting -------------------------------------------------------------

    def used_concepts(self) -> list[ConceptRecord]:
        return [self.concepts[c] for c in sorted(self._usage) if c in self.concepts]

    def usage(self) -> dict[str, Counter[str]]:
        return {c: Counter(u) for c, u in sorted(self._usage.items())}

    def missing(self) -> dict[str, Counter[str]]:
        return {c: Counter(u) for c, u in sorted(self._missing.items())}

    def vocabularies_for(
        self, concepts: list[ConceptRecord]
    ) -> tuple[list[VocabularyRecord], list[str]]:
        """Vocabularies needed by these concepts, and the prefixes that have none."""
        prefixes = sorted({c.vocabulary_prefix for c in concepts})
        found = [self.vocabularies[p] for p in prefixes if p in self.vocabularies]
        missing = [p for p in prefixes if p not in self.vocabularies]
        return found, missing

    def all_concepts(self) -> list[ConceptRecord]:
        """Every concept from the input files (for --full-reference)."""
        return [
            self.concepts[c]
            for c in sorted(self.concepts)
            if self.concepts[c].source != "linkml_enum"
        ]
