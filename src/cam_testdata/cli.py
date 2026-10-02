"""Command-line interface. Commands are added as TODO.md phases land."""

from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from cam_testdata.settings import PROJECT_ROOT

app = typer.Typer(no_args_is_help=True, add_completion=False)

Profile = Annotated[str, typer.Option("--profile", "-p", help="tiny | small | portal")]
OutDir = Annotated[Path | None, typer.Option(help="default: output/<profile>")]


@app.callback()
def main() -> None:
    """Deterministic test data generator for the Common Access Model."""


@app.command("version")
def show_version() -> None:
    """Print the cam-testdata and common-access-model versions."""
    typer.echo(f"cam-testdata {version('cam-testdata')}")
    typer.echo(f"common-access-model {version('common-access-model')}")


@app.command("missing-concepts")
def missing_concepts(profile: Profile = "tiny", out_dir: OutDir = None) -> None:
    """Report curies and vocabularies the profile needs that no input provides."""
    from cam_testdata.concepts import ConceptRegistry
    from cam_testdata.missing import find_missing, write_report
    from cam_testdata.schema_introspect import get_model

    model = get_model()
    registry = ConceptRegistry(model)
    report = find_missing(model, registry, profile)
    csv_path, stub_path = write_report(
        model, registry, report, out_dir or PROJECT_ROOT / "output" / profile
    )
    for curie, uses in sorted(report.concepts.items()):
        typer.echo(f"missing concept {curie}: {', '.join(sorted(uses))}")
    for prefix in report.vocabularies:
        typer.echo(f"missing vocabulary {prefix}")
    typer.echo(f"wrote {csv_path} and {stub_path}")
    if not report.ok:
        raise typer.Exit(1)


@app.command("validate")
def validate(profile: Profile = "tiny", limit: int = 5) -> None:
    """Run integrity rules R1-R12 against the profile's database."""
    from cam_testdata import db
    from cam_testdata.validate.integrity import run_all

    engine = db.make_engine(profile)
    with engine.connect() as conn:
        results = run_all(conn)
    failed = 0
    for rule, violations in results.items():
        status = "ok" if not violations else f"FAIL ({len(violations)})"
        typer.echo(f"{rule:<4} {status}")
        for v in violations[:limit]:
            typer.echo(f"     {v.table} {v.key}: {v.detail}")
        if len(violations) > limit:
            typer.echo(f"     ... {len(violations) - limit} more")
        failed += bool(violations)
    if failed:
        raise typer.Exit(1)


@app.command("build")
def build(
    profile: Profile = "tiny", out_dir: OutDir = None, full_reference: bool = False
) -> None:
    """Build a profile: reset its DB, load the scenario, validate, export, write the manifest."""
    from cam_testdata.pipeline import BuildFailed, run_build

    doc = (
        PROJECT_ROOT / "docs" / "SCENARIO_TINY.md"
        if profile == "tiny" and out_dir is None
        else None
    )
    try:
        result = run_build(
            profile,
            out_dir=out_dir,
            scenario_doc_path=doc,
            full_reference=full_reference,
        )
    except BuildFailed as exc:
        typer.echo(f"build failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    total = sum(result.row_counts.values())
    typer.echo(
        f"built {profile}: {total} rows, {len(result.artifacts)} artifacts in {result.out_dir}"
    )


@app.command("verify-sql")
def verify_sql_command(profile: Profile = "tiny", out_dir: OutDir = None) -> None:
    """Load each SQL dump into a scratch DB and byte-compare its CSV export with output/<profile>/csv."""
    from cam_testdata.validate.roundtrip import verify_sql

    results = verify_sql(profile, out_dir or PROJECT_ROOT / "output" / profile)
    bad = {dump: tables for dump, tables in results.items() if tables}
    for dump, tables in results.items():
        typer.echo(f"{dump}: {'ok' if not tables else 'differs: ' + ', '.join(tables)}")
    if bad or not results:
        raise typer.Exit(1)
