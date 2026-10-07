from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML
from sqlalchemy.orm import Session

from cam_testdata.build import Build
from cam_testdata.scenarios.loader import LoaderError, load_scenario
from cam_testdata.settings import PROJECT_ROOT
from cam_testdata.validate.coverage import NOT_REQUIRED_IN_TINY, missing_features
from cam_testdata.validate.integrity import run_all

TINY = PROJECT_ROOT / "scenarios" / "tiny.yaml"

BASE: dict[str, list[dict[str, Any]]] = {
    "AccessPolicy": [{"key": "ap"}],
    "Study": [
        {
            "key": "s1",
            "access_policy_id": "ap",
            "program": ["https://www.nih.gov/include-project"],
        }
    ],
    "Subject": [{"key": "p1", "study_id": "s1"}],
}


def write(tmp_path: Path, records: dict[str, Any]) -> Path:
    path = tmp_path / "scenario.yaml"
    YAML().dump({"scenario": "t", "records": records}, path.open("w"))
    return path


def load(tmp_path: Path, **extra: Any) -> Any:
    records = {k: [dict(r) for r in v] for k, v in BASE.items()}
    for cls, rows in extra.items():
        records.setdefault(cls, []).extend(rows)
    return load_scenario(Build("test"), write(tmp_path, records))


def test_minimal_scenario_loads(tmp_path: Path) -> None:
    result = load(tmp_path)
    assert result[("Subject", "p1")].study_id == result[("Study", "s1")].study_id


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"Nope": [{"key": "x"}]}, "unknown class 'Nope'"),
        (
            {"Subject": [{"key": "p2", "study_id": "s1", "flavor": "x"}]},
            r"Subject\[p2\].flavor: unknown slot",
        ),
        (
            {"Encounter": [{"key": "e1", "subject_id": "nobody"}]},
            r"Encounter\[e1\].subject_id: unknown key 'nobody'",
        ),
        (
            {"Subject": [{"key": "p1", "study_id": "s1"}]},
            r"Subject\[p1\]: duplicate key",
        ),
        (
            {"Subject": [{"key": "p2", "study_id": "s1", "id": "sd-0123456789"}]},
            r"Subject\[p2\].id: .*prefix",
        ),
        ({"Encounter": [{"key": "e1"}]}, r"Encounter\[e1\].subject_id: required"),
        ({"Investigator": [{"key": "pi"}]}, r"Investigator\[pi\].study_id: required"),
    ],
)
def test_errors_name_the_record(
    tmp_path: Path, extra: dict[str, Any], message: str
) -> None:
    with pytest.raises(LoaderError, match=message):
        load(tmp_path, **extra)


def test_conflicting_inherited_study_id(tmp_path: Path) -> None:
    extra = {
        "Study": [
            {
                "key": "s2",
                "access_policy_id": "ap",
                "program": ["https://www.nih.gov/include-project"],
            }
        ],
        "Encounter": [{"key": "e1", "subject_id": "p1", "study_id": "s2"}],
    }
    with pytest.raises(
        LoaderError,
        match=r"Encounter\[e1\].study_id: 's2' conflicts with the inherited value",
    ):
        load(tmp_path, **extra)


def test_one_to_one_uses_parent_key(tmp_path: Path) -> None:
    result = load(tmp_path, Demographics=[{"key": "p1", "race": ["CDCREC:2106-3"]}])
    assert (
        result[("Demographics", "p1")].subject_id
        == result[("Subject", "p1")].subject_id
    )
    other = tmp_path / "missing-parent"
    other.mkdir()
    with pytest.raises(
        LoaderError, match=r"Demographics\[nobody\].subject_id: no Subject"
    ):
        load(other, Demographics=[{"key": "nobody"}])


# Pinned per-table counts for tiny (update together with docs/SCENARIO_TINY.md).
TINY_ENTITY_COUNTS = {
    "AccessPolicy": 3,  # controlled, open, Farm
    "ActivityDefinition": 3,
    "Aliquot": 7,
    "Assay": 3,
    "BiospecimenCollection": 3,
    "DOI": 1,
    "Dataset": 1,
    "Demographics": 4,
    "Encounter": 5,
    "EncounterDefinition": 2,
    "Family": 1,
    "FamilyMembership": 4,
    "FamilyRelationship": 3,
    "File": 5,
    "HashDigest": 6,
    "Investigator": 2,
    "Person": 1,  # one subject so far (first study ingested)
    "Publication": 1,
    "Sample": 6,
    "Study": 3,  # S1, S2, Farm umbrella
    "StudyMetadata": 3,
    "Subject": 5,
    "SubjectAssertion": 6,
    "VirtualBiorepository": 1,
}


def test_tiny_builds_valid_and_covers_every_feature(session: Session) -> None:
    build = Build("tiny")
    result = load_scenario(build, TINY)
    counts = build.write(session)
    assert {
        t: n for t, n in counts.items() if t in TINY_ENTITY_COUNTS
    } == TINY_ENTITY_COUNTS
    assert sum(counts.values()) == 242
    assert {rule: v for rule, v in run_all(session.connection()).items() if v} == {}
    missing = set(missing_features(session.connection()))
    assert missing <= NOT_REQUIRED_IN_TINY
    s1 = result[("Study", "s1")]
    assert (
        s1.study_id == "sd-7hwpqzc2yr" and s1.do_id == result[("DOI", "s1-doi")].do_id
    )
