"""Settings from config/settings.yaml (DESIGN §4, §5, §11)."""

import os
import re
import shlex
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ruamel.yaml import YAML

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
SCHEMA_PATH = PROJECT_ROOT / "data" / "common_access_model.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IdSettings(_Strict):
    alphabet: str
    length: int = Field(gt=0)
    local_prefixes: dict[str, str]
    doi_classes: list[str]
    doi_prefix: str
    doi_length: int = Field(gt=0)
    external_id_base: str

    @field_validator("alphabet")
    @classmethod
    def _unique_alphabet(cls, value: str) -> str:
        if len(set(value)) != len(value) or len(value) < 2:
            raise ValueError("alphabet needs at least two distinct characters")
        return value

    @field_validator("local_prefixes")
    @classmethod
    def _three_letter_prefixes(cls, value: dict[str, str]) -> dict[str, str]:
        bad = {k: v for k, v in value.items() if not re.fullmatch(r"[a-z]{3}", v)}
        if bad:
            raise ValueError(f"local prefixes must be 3 lowercase letters: {bad}")
        return value

    def global_id_regex(self, prefix: str | None = None) -> re.Pattern[str]:
        """Regex for a GlobalID, optionally for one prefix."""
        head = re.escape(prefix) if prefix else "[a-z]{2}"
        return re.compile(rf"^{head}-[{re.escape(self.alphabet)}]{{{self.length}}}$")


class DatabaseSettings(_Strict):
    url_template: str
    schema_name: str = Field(alias="schema")
    pg_dump: list[str]
    psql: list[str]
    restrict_key: str

    def pg_dump_cmd(self) -> list[str]:
        """The pg_dump command; CAM_PG_DUMP overrides it (e.g. in CI, without Docker)."""
        override = os.environ.get("CAM_PG_DUMP")
        return shlex.split(override) if override else list(self.pg_dump)

    def psql_cmd(self) -> list[str]:
        """The psql command; CAM_PSQL overrides it."""
        override = os.environ.get("CAM_PSQL")
        return shlex.split(override) if override else list(self.psql)

    def url(self, profile: str) -> str:
        """Database URL for a profile; CAM_PG_URL overrides it."""
        return os.environ.get("CAM_PG_URL") or self.url_template.format(profile=profile)


class TableSettings(_Strict):
    exclude: list[str]
    empty: list[str]


class ConceptSettings(_Strict):
    coded_uriorcurie_slots: list[str]


class DriftSettings(_Strict):
    skip_columns: dict[str, str]


class ProfileSettings(_Strict):
    seed: str


class FakerSettings(_Strict):
    locale: str


class Settings(_Strict):
    ids: IdSettings
    database: DatabaseSettings
    tables: TableSettings
    concepts: ConceptSettings
    drift: DriftSettings
    natural_keys: dict[str, list[list[str]]]
    profiles: dict[str, ProfileSettings]
    faker: FakerSettings

    def seed(self, profile: str) -> str:
        try:
            return self.profiles[profile].seed
        except KeyError:
            raise KeyError(
                f"unknown profile {profile!r}; known: {sorted(self.profiles)}"
            ) from None


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    with path.open() as fh:
        data = YAML(typ="safe").load(fh)
    return Settings.model_validate(data)


@cache
def get_settings() -> Settings:
    return load_settings()
