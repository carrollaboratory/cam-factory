from importlib.metadata import version

from typer.testing import CliRunner

from cam_testdata.cli import app


def test_version_reports_model_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"common-access-model {version('common-access-model')}" in result.output
