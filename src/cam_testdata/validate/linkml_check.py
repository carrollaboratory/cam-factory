"""Validate LinkML-shaped instances (TODO 4.3): JSON Schema via linkml, then pydantic.

The YAML export (5.3) writes one list of instances per class, so validation
names the target class explicitly (MODEL_ISSUES #18: there's no tree_root).
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from common_access_model.datamodel import common_access_model_pydantic as pydantic_model
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from pydantic import ValidationError
from ruamel.yaml import YAML

from cam_testdata.settings import SCHEMA_PATH


@dataclass(frozen=True)
class InstanceProblem:
    cls: str
    index: int  # position in the file / list
    source: str  # "linkml" | "pydantic"
    message: str


@cache
def _validator() -> Validator:
    # closed=True: keys that aren't slots of the class are errors
    return Validator(
        str(SCHEMA_PATH), validation_plugins=[JsonschemaValidationPlugin(closed=True)]
    )


def validate_instances(
    cls: str, instances: list[dict[str, Any]]
) -> list[InstanceProblem]:
    problems: list[InstanceProblem] = []
    pydantic_class = getattr(pydantic_model, cls)
    for i, instance in enumerate(instances):
        report = _validator().validate(instance, cls)
        problems += [
            InstanceProblem(cls, i, "linkml", r.message) for r in report.results
        ]
        try:
            pydantic_class(**instance)
        except ValidationError as exc:
            problems += [
                InstanceProblem(
                    cls, i, "pydantic", f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                )
                for e in exc.errors()
            ]
    return problems


def validate_yaml_file(path: Path, cls: str | None = None) -> list[InstanceProblem]:
    """A per-class YAML file (a list of instances, or one instance). Class defaults to the file stem
    with any -NNN example suffix removed (Subject.yaml, Subject-001.yaml)."""
    cls = cls or path.stem.split("-")[0]
    with path.open() as fh:
        data = YAML(typ="safe").load(fh)
    instances = data if isinstance(data, list) else [data]
    return validate_instances(cls, instances)
