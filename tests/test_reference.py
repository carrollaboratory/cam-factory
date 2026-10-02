import pytest
from common_access_model.datamodel.common_access_model_sqla import Concept, Vocabulary
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cam_testdata import drift
from cam_testdata.concepts import ConceptRegistry
from cam_testdata.factories import all_factories
from cam_testdata.factories.reference import MissingVocabularyError, load_reference


def test_loads_only_used_concepts(session: Session) -> None:
    registry = ConceptRegistry()
    for curie in ("HP:0000821", "KIN:028", "CAMO:0000024", "DUO:0000007"):
        registry.resolve(curie, "test.column")
    vocabs, concepts = load_reference(session, registry)
    assert (vocabs, concepts) == (4, 4)
    rows = session.execute(
        select(Concept.concept_curie, Concept.display).order_by(Concept.concept_curie)
    ).all()
    assert rows[0] == ("CAMO:0000024", "Participant")
    assert session.scalar(select(func.count()).select_from(Vocabulary)) == 4


def test_missing_vocabulary_fails(session: Session) -> None:
    registry = ConceptRegistry(vocab_files=())  # no vocabulary files at all
    registry.resolve("CAMO:0000024", "Subject.subject_type")  # resolves from the enum
    with pytest.raises(MissingVocabularyError, match="CAMO"):
        load_reference(session, registry)


def test_full_reference_loads_every_input_concept(session: Session) -> None:
    registry = ConceptRegistry()
    vocabs, concepts = load_reference(session, registry, full=True)
    assert concepts == len(registry.all_concepts()) > 1000
    assert vocabs == len(registry.vocabularies_for(registry.all_concepts())[0])


def test_reference_factories_declare_every_column() -> None:
    report = drift.check(all_factories())
    assert (
        "Concept" not in report.missing_tables
        and "Vocabulary" not in report.missing_tables
    )
    assert not [
        c
        for c in report.missing_columns
        if c.split(".")[0] in ("Concept", "Vocabulary")
    ]
