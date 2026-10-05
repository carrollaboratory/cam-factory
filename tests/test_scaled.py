"""TODO 6.1-6.4: scaled scenarios, archives, drift."""

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cam_testdata.build import Build
from cam_testdata.cli import app
from cam_testdata.dist import make_dist
from cam_testdata.drift import compare_shapes
from cam_testdata.factories.base import pk_of
from cam_testdata.scenarios.scaled import ScaledScenario, load_profile
from cam_testdata.validate.integrity import run_all


def small_config(families: int) -> dict[str, Any]:
    config = copy.deepcopy(load_profile("small"))
    config["families_per_study"] = families
    return config


def generate(config: dict[str, Any]) -> Build:
    build = Build("small")
    with build.active():
        ScaledScenario(build, config).generate()
    return build


def ids_by_handle(build: Build) -> dict[str, Any]:
    return {
        build.handles[id(o)]: pk_of(o) for o in build.objects if id(o) in build.handles
    }


def test_scaled_scenario_is_valid(session: Session) -> None:
    build = generate(small_config(4))
    build.write(session)
    assert {rule: v for rule, v in run_all(session.connection()).items() if v} == {}


def test_growing_a_profile_keeps_existing_records() -> None:
    fewer, more = (
        ids_by_handle(generate(small_config(3))),
        ids_by_handle(generate(small_config(6))),
    )
    shared = set(fewer) & set(more)
    family_records = {h for h in fewer if "-f000" in h}
    assert family_records <= shared  # every family-level record still exists...
    assert all(fewer[h] == more[h] for h in family_records)  # ...with the same ID
    assert len(more) > len(fewer)


def test_handles_carry_index_numbers() -> None:
    handles = set(ids_by_handle(generate(small_config(2))))
    assert "small/Study/s01" in handles and "small/Family/s01-f0002" in handles
    assert any(h.startswith("small/Subject/s02-f0001-proband") for h in handles)


def test_dist_is_reproducible(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "csv").mkdir(parents=True)
    (out / "csv" / "A.csv").write_text("a\n1\n")
    (out / "manifest.json").write_text(
        json.dumps({"model": {"common_access_model": "9.9"}})
    )
    first = make_dist("demo", out, tmp_path / "d1").read_bytes()
    second = make_dist("demo", out, tmp_path / "d2").read_bytes()
    assert first == second
    assert (tmp_path / "d1" / "cam-testdata-demo-9.9.tar.gz").exists()


def test_compare_shapes_reports_changes() -> None:
    old = {
        "tables": {"A": ["x", "y"], "Gone": ["z"]},
        "enums": {
            "E": {"count": 2, "sha256": "aa"},
            "Old": {"count": 1, "sha256": "bb"},
        },
    }
    new = {
        "tables": {"A": ["x", "w"], "New": ["q"]},
        "enums": {
            "E": {"count": 3, "sha256": "cc"},
            "Fresh": {"count": 1, "sha256": "dd"},
        },
    }
    assert compare_shapes(old, new) == [
        "table added: New",
        "table removed: Gone",
        "column added: A.w",
        "column removed: A.y",
        "enum added: Fresh",
        "enum removed: Old",
        "enum changed: E (2 -> 3 values)",
    ]


def test_check_drift_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    tiny = Path("output/tiny")
    result = runner.invoke(
        app, ["check-drift", "--profile", "tiny", "--out-dir", str(tiny)]
    )
    assert result.exit_code == 0, result.output
    doctored = tmp_path / "tiny"
    doctored.mkdir()
    manifest = json.loads((tiny / "manifest.json").read_text())
    manifest["model"]["common_access_model"] = "0.0.1"
    manifest["model"]["shape"]["tables"]["Subject"].append("flavor")
    (doctored / "manifest.json").write_text(json.dumps(manifest))
    result = runner.invoke(
        app, ["check-drift", "--profile", "tiny", "--out-dir", str(doctored)]
    )
    assert result.exit_code == 1
    assert "model version: built 0.0.1" in result.output
    assert "column removed: Subject.flavor" in result.output
    shutil.rmtree(doctored)
