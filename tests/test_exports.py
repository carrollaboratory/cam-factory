import csv
from pathlib import Path

from sqlalchemy.orm import Session

from cam_testdata.export.csv_export import export_csv
from cam_testdata.export.yaml_export import YamlExporter, export_yaml
from cam_testdata.schema_introspect import get_model
from cam_testdata.validate.linkml_check import validate_yaml_file
from dataset import build_dataset


def test_csv_and_yaml_exports(session: Session, tmp_path: Path) -> None:
    data = build_dataset()
    data.build.write(session)
    conn = session.connection()

    export_csv(conn, tmp_path / "csv")
    sample = list(csv.reader((tmp_path / "csv" / "Sample.csv").open()))
    header, rows = sample[0], sample[1:]
    assert header[:3] == ["sample_id", "biospecimen_collection_id", "parent_sample_id"]
    assert rows == sorted(rows, key=lambda r: r[0])  # sorted by PK
    blood = next(r for r in rows if r[0] == data["blood"].sample_id)
    assert blood[header.index("parent_sample_id")] == ""  # NULL -> empty
    concepts = (tmp_path / "csv" / "Concept.csv").read_text()
    assert ",0000024," in concepts  # leading zeros survive

    files = export_yaml(conn, get_model(), tmp_path / "yaml", tmp_path / "examples")
    assert (tmp_path / "examples" / "Study-001.yaml") in files
    for path in sorted((tmp_path / "yaml").glob("*.yaml")):
        assert validate_yaml_file(path) == [], path.name

    study = YamlExporter(conn, get_model()).instance(
        "Study", YamlExporter(conn, get_model()).rows("Study")[data["s1"].study_id]
    )
    assert next(iter(study)) == "study_title"  # induced slot order, NULLs omitted
    assert isinstance(
        study["principal_investigator"][0], dict
    )  # no LinkML identifier -> inlined
    assert study["do_id"] == data["doi"].do_id
