from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from cam_testdata.cli import app
from cam_testdata.concepts import ConceptRegistry
from cam_testdata.missing import collect_scenario, find_missing, write_report
from cam_testdata.schema_introspect import get_model


def test_scenario_curies_are_recorded_by_table_column(tmp_path: Path) -> None:
    scenario = tmp_path / "s.yaml"
    YAML().dump(
        {
            "records": {
                "Demographics": [
                    {"key": "p", "sex": "snomedct:248152002", "race": ["CDCREC:2106-3"]}
                ],
                "File": [
                    {
                        "key": "f",
                        "format": "edam:format_3462",
                        "hash": [{"hash_type": "MS:1000568"}],
                    }
                ],
                "Study": [
                    {"key": "s", "program": ["https://www.nih.gov/include-project"]}
                ],
                "Sample": [{"key": "x", "sample_type": "UBERON:0000000"}],
            }
        },
        scenario.open("w"),
    )
    registry = ConceptRegistry()
    collect_scenario(get_model(), registry, scenario)
    usage = registry.usage()
    assert usage["snomedct:248152002"] == {"Demographics.sex": 1}
    assert usage["CDCREC:2106-3"] == {"Demographics_race.race_concept_curie": 1}
    assert usage["MS:1000568"] == {"HashDigest.hash_type": 1}  # inlined object
    assert "https://www.nih.gov/include-project" not in usage  # full URI, exempt
    assert registry.missing() == {"UBERON:0000000": {"Sample.sample_type": 1}}


def test_report_files(tmp_path: Path) -> None:
    model = get_model()
    registry = ConceptRegistry(model)
    registry.resolve("UBERON:0000000", "Sample.sample_type")
    report = find_missing(model, registry, "tiny")
    csv_path, stub_path = write_report(model, registry, report, tmp_path)
    assert "UBERON:0000000,Sample.sample_type,1" in csv_path.read_text()
    stub = YAML(typ="safe").load(stub_path)
    assert "UBERON:0000000" in stub["UBERON"]["codes"]
    assert (
        stub["UBERON"]["fhir_system"] == "http://purl.obolibrary.org/obo/uberon.owl"
    )  # from the extra file


def test_cli_exit_code_reflects_missing(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["missing-concepts", "--profile", "tiny", "--out-dir", str(tmp_path)]
    )
    report = find_missing(get_model(), ConceptRegistry(), "tiny")
    assert result.exit_code == (0 if report.ok else 1), result.output
