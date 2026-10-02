"""factory_boy factories, one module per domain area (DESIGN §3.2)."""

from typing import Any


def all_factories() -> list[Any]:
    """Every model factory. The drift check treats a column as produced only if a
    factory here declares it explicitly (even if its default is None)."""
    from cam_testdata.factories import (
        biospecimen,
        clinical,
        family,
        files,
        study,
        subject,
    )
    from cam_testdata.factories.associations import all_association_factories
    from cam_testdata.factories.base import BaseFactory
    from cam_testdata.factories.reference import ConceptFactory, VocabularyFactory

    entity = [
        obj
        for module in (study, subject, family, clinical, biospecimen, files)
        for name, obj in sorted(vars(module).items())
        if name.endswith("Factory")
        and isinstance(obj, type)
        and issubclass(obj, BaseFactory)
        and not obj._meta.abstract
        and obj.__module__ == module.__name__
    ]
    return [VocabularyFactory, ConceptFactory, *entity, *all_association_factories()]
