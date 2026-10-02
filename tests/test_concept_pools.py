from pathlib import Path

import pytest
from ruamel.yaml import YAML

from cam_testdata.concept_pools import PoolError, load_pools
from cam_testdata.concepts import ConceptRegistry
from cam_testdata.schema_introspect import get_model


def write_pools(tmp_path: Path, data: dict) -> Path:  # type: ignore[type-arg]
    path = tmp_path / "pools.yaml"
    with path.open("w") as fh:
        YAML().dump(data, fh)
    return path


def test_real_pools_load_and_resolve() -> None:
    registry = ConceptRegistry()
    pools = load_pools(get_model(), registry)
    assert "OBI:0002117" in pools.pool("Assay", "assay_type")
    assert len(pools.bundles["measurements"]) == 3
    # Every pooled concept resolves through the registry.
    assert registry.missing() == {}


def test_bad_enum_entry_fails_clearly(tmp_path: Path) -> None:
    path = write_pools(
        tmp_path, {"pools": {"Assay.assay_type": ["OBI:0002117", "OBI:9999999"]}}
    )
    with pytest.raises(
        PoolError,
        match=r"OBI:9999999 isn't a permissible value of EnumAssayType \(Assay.assay_type\)",
    ):
        load_pools(get_model(), ConceptRegistry(), path)


def test_bad_enum_entry_in_bundle_fails(tmp_path: Path) -> None:
    path = write_pools(
        tmp_path,
        {
            "bundles": {
                "file_kinds": [
                    {"File.format": "edam:format_0000", "File.file_extension": ".x"}
                ]
            }
        },
    )
    with pytest.raises(PoolError, match=r"bundles.file_kinds\[0\]: edam:format_0000"):
        load_pools(get_model(), ConceptRegistry(), path)


def test_unknown_slot_fails(tmp_path: Path) -> None:
    path = write_pools(tmp_path, {"pools": {"Sample.flavor": ["X:1"]}})
    with pytest.raises(PoolError, match="Sample.flavor isn't a slot"):
        load_pools(get_model(), ConceptRegistry(), path)


def test_unresolved_concept_is_reported_not_raised(tmp_path: Path) -> None:
    path = write_pools(tmp_path, {"pools": {"Sample.sample_type": ["UBERON:9999999"]}})
    registry = ConceptRegistry()
    load_pools(get_model(), registry, path)
    assert registry.missing() == {"UBERON:9999999": {"pool:Sample.sample_type": 1}}
