"""TODO 5.6: two builds of tiny into two databases give byte-identical artifacts."""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from cam_testdata.pipeline import run_build
from cam_testdata.settings import get_settings

DBS = ("determinism_a", "determinism_b")


def _admin(sql: str) -> None:
    cmd = [*get_settings().database.psql, "-d", "postgres", "-q", "-c", sql]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def scratch_dbs() -> Iterator[None]:
    for name in DBS:
        _admin(f'DROP DATABASE IF EXISTS "cam_testdata_{name}"')
        _admin(f'CREATE DATABASE "cam_testdata_{name}"')
    yield
    for name in DBS:
        _admin(f'DROP DATABASE IF EXISTS "cam_testdata_{name}" WITH (FORCE)')


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_two_builds_are_byte_identical(tmp_path: Path, scratch_dbs: None) -> None:
    outputs = []
    for name in DBS:
        out = tmp_path / name
        run_build(
            "tiny",
            out_dir=out,
            db_profile=name,
            scenario_doc_path=out / "SCENARIO_TINY.md",
        )
        outputs.append(_files(out))
    a, b = outputs
    assert sorted(a) == sorted(b)
    assert [name for name in a if a[name] != b[name]] == []
    assert len(a) > 100
