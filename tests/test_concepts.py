from pathlib import Path

import pytest
from ruamel.yaml import YAML

from cam_testdata.concepts import (
    ConceptRegistry,
    PrefixCaseError,
    is_uri,
)


@pytest.fixture(scope="module")
def registry() -> ConceptRegistry:
    return ConceptRegistry()


def write_yaml(path: Path, data: dict) -> Path:  # type: ignore[type-arg]
    with path.open("w") as fh:
        YAML().dump(data, fh)
    return path


def test_resolution_order(registry: ConceptRegistry) -> None:
    reg = ConceptRegistry()
    hp = reg.resolve("HP:0000821", "SubjectAssertion_concept.concept_concept_curie")
    assert (
        hp is not None
        and hp.source == "vocab_content"
        and hp.display == "Hypothyroidism"
    )
    kin = reg.resolve("KIN:028", "FamilyMembership.family_role")
    assert kin is not None and kin.source == "extra"
    enum = reg.resolve("CAMO:0000025", "Subject.subject_type")  # not in camo extra pull
    assert (
        enum is not None
        and enum.source == "linkml_enum"
        and enum.display == "Non-Participant"
    )
    assert enum.concept_code == "0000025" and enum.vocabulary_prefix == "CAMO"
    assert reg.resolve("NOPE:123", "X.y") is None
    assert reg.missing() == {"NOPE:123": {"X.y": 1}}


def test_usage_is_recorded_per_column() -> None:
    reg = ConceptRegistry()
    reg.resolve("snomedct:248152002", "Demographics.sex")
    reg.resolve("snomedct:248152002", "Demographics.sex")
    reg.resolve("snomedct:248152002", "Other.col")
    assert reg.usage()["snomedct:248152002"] == {"Demographics.sex": 2, "Other.col": 1}
    assert [c.concept_curie for c in reg.used_concepts()] == ["snomedct:248152002"]


def test_full_uris_are_exempt() -> None:
    reg = ConceptRegistry()
    assert is_uri("https://www.nih.gov/include-project")
    assert not is_uri("ucum:/mL")
    assert (
        reg.resolve("https://www.nih.gov/include-project", "Study_program.program")
        is None
    )
    assert reg.missing() == {}


def test_prefix_case_mismatch_is_rejected() -> None:
    reg = ConceptRegistry()
    with pytest.raises(PrefixCaseError, match="CDCREC"):
        reg.resolve("cdcrec:2106-3", "Demographics_race.race_concept_curie")


def test_prefix_case_mismatch_in_input_file_is_rejected(tmp_path: Path) -> None:
    bad = write_yaml(
        tmp_path / "bad.yaml",
        {
            "cdcrec": {
                "vocabulary_prefix": "cdcrec",
                "vocabulary_uri": "x",
                "fhir_system": "y",
                "codes": [],
            }
        },
    )
    with pytest.raises(PrefixCaseError, match="cdcrec"):
        ConceptRegistry(vocab_files=((bad, "vocab_content"),))


def test_first_file_wins_and_conflicts_are_noted(tmp_path: Path) -> None:
    def vocab(display: str) -> dict:  # type: ignore[type-arg]
        return {
            "ZZ": {
                "vocabulary_prefix": "ZZ",
                "vocabulary_uri": "http://zz/",
                "fhir_system": "http://zz",
                "description": "",
                "codes": [
                    {"concept_curie": "ZZ:1", "concept_code": "1", "display": display}
                ],
            }
        }

    a = write_yaml(tmp_path / "a.yaml", vocab("first"))
    b = write_yaml(tmp_path / "b.yaml", vocab("second"))
    reg = ConceptRegistry(vocab_files=((a, "vocab_content"), (b, "extra")))
    record = reg.resolve("ZZ:1")
    assert record is not None and record.display == "first"
    assert reg.conflicts == ["ZZ:1 (vocab_content kept, extra ignored)"]
    assert reg.vocabularies["ZZ"].description is None  # '' becomes NULL (R12)


def test_vocabularies_for_reports_missing_prefixes() -> None:
    reg = ConceptRegistry()
    hp = reg.resolve("HP:0000821")
    # A concept that only an enum PV provides, with a prefix no file defines:
    orphan = ConceptRegistry(vocab_files=()).resolve("CAMO:0000024")
    assert hp is not None and orphan is not None
    found, missing = reg.vocabularies_for([hp, orphan])
    assert missing == []
    assert [v.vocabulary_prefix for v in found] == ["CAMO", "HP"]
    assert ConceptRegistry(vocab_files=()).vocabularies_for([orphan]) == ([], ["CAMO"])


def test_concept_codes_stay_strings(registry: ConceptRegistry) -> None:
    for record in registry.all_concepts():
        assert isinstance(record.concept_code, str)
