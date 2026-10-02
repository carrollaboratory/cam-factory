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
