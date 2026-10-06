import pytest

from cam_testdata.settings import get_settings


def test_command_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    db = get_settings().database
    assert db.pg_dump_cmd()[:2] == ["docker", "exec"]
    monkeypatch.setenv("CAM_PG_DUMP", "pg_dump -h localhost -U postgres")
    monkeypatch.setenv("CAM_PSQL", "psql -h localhost -U postgres")
    assert db.pg_dump_cmd() == ["pg_dump", "-h", "localhost", "-U", "postgres"]
    assert db.psql_cmd()[0] == "psql"
