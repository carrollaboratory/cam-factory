from pathlib import Path

from ruamel.yaml import YAML

from cam_testdata.validate.linkml_check import validate_instances, validate_yaml_file

GOOD = {
    "subject_id": "pt-0123456789",
    "subject_type": "CAMO:0000024",
    "study_id": "sd-0123456789",
    "access_policy_id": "co-0123456789",
    "external_id": ["https://example.org/cam-testdata/tiny/Subject/a"],
}


def test_valid_instance_passes() -> None:
    assert validate_instances("Subject", [GOOD]) == []


def test_both_validators_report_problems() -> None:
    bad = {**GOOD, "subject_type": "NOT-A-CODE", "flavor": "x"}
    problems = validate_instances("Subject", [GOOD, bad])
    assert {p.index for p in problems} == {1}
    assert {p.source for p in problems} == {"linkml", "pydantic"}
    assert any("flavor" in p.message for p in problems if p.source == "linkml")


def test_yaml_file_class_from_name(tmp_path: Path) -> None:
    path = tmp_path / "Subject-001.yaml"
    YAML().dump(GOOD, path.open("w"))
    assert validate_yaml_file(path) == []
    listing = tmp_path / "Subject.yaml"
    YAML().dump([GOOD, {**GOOD, "subject_id": 5}], listing.open("w"))
    assert {p.index for p in validate_yaml_file(listing)} == {1}
