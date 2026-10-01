from typer.testing import CliRunner

from cam_testdata.cli import app


def test_version_reports_model_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "common-access-model 0.2.0" in result.output
