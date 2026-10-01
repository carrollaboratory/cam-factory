"""Command-line interface. Commands are added as TODO.md phases land."""

from importlib.metadata import version

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Deterministic test data generator for the Common Access Model."""


@app.command("version")
def show_version() -> None:
    """Print the cam-testdata and common-access-model versions."""
    typer.echo(f"cam-testdata {version('cam-testdata')}")
    typer.echo(f"common-access-model {version('common-access-model')}")
