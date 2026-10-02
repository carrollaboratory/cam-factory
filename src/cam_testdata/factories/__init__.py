"""factory_boy factories, one module per domain area (DESIGN §3.2). Filled in Phase 3."""

from typing import Any


def all_factories() -> list[Any]:
    """Every model factory. The drift check treats a column as produced only if a
    factory here declares it explicitly (even if its default is None)."""
    return []
