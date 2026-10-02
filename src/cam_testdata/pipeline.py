"""`cam-testdata build`: reset -> scenario -> write -> validate -> export -> manifest (DESIGN §3).

A failing validation aborts before anything is exported.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from cam_testdata import db
from cam_testdata.build import Build
from cam_testdata.export import (
    csv_export,
    manifest,
    scenario_doc,
    sql_export,
    yaml_export,
)
from cam_testdata.scenarios.loader import load_scenario
from cam_testdata.settings import PROJECT_ROOT, get_settings
from cam_testdata.validate.coverage import run_features
from cam_testdata.validate.integrity import run_all
from cam_testdata.validate.linkml_check import validate_yaml_file

SCENARIOS = {"tiny": PROJECT_ROOT / "scenarios" / "tiny.yaml"}
REQUIRE_ALL_FEATURES = {"tiny"}
GENERATED_DIRS = ("csv", "yaml", "examples", "sql")


class BuildFailed(RuntimeError):
    pass


@dataclass
class BuildResult:
    out_dir: Path
    row_counts: dict[str, int]
    artifacts: list[Path]


def run_build(
    profile: str,
    out_dir: Path | None = None,
    db_profile: str | None = None,
    scenario_doc_path: Path | None = None,
    full_reference: bool = False,
) -> BuildResult:
    """Build `profile` into database cam_testdata_<db_profile> (default: the profile)."""
    settings = get_settings()
    db_profile = db_profile or profile
    out_dir = out_dir or PROJECT_ROOT / "output" / profile
    if profile not in SCENARIOS:
        raise BuildFailed(
            f"no scenario for profile {profile!r} yet (scaled profiles arrive in Phase 6)"
        )

    build = Build(profile)
    load_scenario(build, SCENARIOS[profile])

    engine = db.make_engine(db_profile)
    try:
        db.reset(engine)
        db.create_tables(engine)
        # keep objects readable after commit: id_map reads their IDs afterwards
        with Session(engine, expire_on_commit=False) as session:
            build.write(session, full_reference=full_reference)
            session.commit()

        with engine.connect() as conn:
            failures = {rule: v for rule, v in run_all(conn).items() if v}
            if failures:
                summary = "; ".join(
                    f"{r}: {len(v)} (e.g. {v[0].table} {v[0].key}: {v[0].detail})"
                    for r, v in failures.items()
                )
                raise BuildFailed(f"integrity rules failed: {summary}")
            features = run_features(conn)
            missing = [f for f, keys in features.items() if not keys]
            if profile in REQUIRE_ALL_FEATURES and missing:
                raise BuildFailed(
                    f"coverage features missing from {profile}: {missing}"
                )

            for sub in GENERATED_DIRS:
                shutil.rmtree(out_dir / sub, ignore_errors=True)
            artifacts = csv_export.export_csv(conn, out_dir / "csv", settings)
            examples = out_dir / "examples" if profile == "tiny" else None
            artifacts += yaml_export.export_yaml(
                conn, build.model, out_dir / "yaml", examples
            )
            problems = [
                p
                for path in sorted((out_dir / "yaml").glob("*.yaml"))
                for p in validate_yaml_file(path)
            ]
            if problems:
                first = problems[0]
                raise BuildFailed(
                    f"{len(problems)} LinkML/pydantic problems, e.g. {first.cls}[{first.index}] {first.source}: {first.message}"
                )

            id_rows = manifest.id_map_rows(build, conn, build.model)
            artifacts.append(manifest.write_id_map(id_rows, out_dir / "id_map.csv"))
            artifacts += sql_export.export_sql(
                profile, out_dir / "sql", settings, dbname=f"cam_testdata_{db_profile}"
            )

            data = manifest.build_manifest(
                build=build,
                conn=conn,
                model=build.model,
                out_dir=out_dir,
                artifacts=artifacts,
                features=features,
                id_rows=id_rows,
                pg_dump_version=sql_export.pg_dump_version(settings),
            )
            manifest.write_manifest(data, out_dir / "manifest.json")
            if scenario_doc_path is not None:
                text = scenario_doc.render(
                    conn,
                    profile,
                    id_rows,
                    data["fhir_counts_by_prefix"],
                    data["coverage_features"],
                    data["row_counts"],
                )
                scenario_doc_path.write_text(text, encoding="utf-8", newline="")
    finally:
        engine.dispose()
    return BuildResult(out_dir, data["row_counts"], artifacts)
