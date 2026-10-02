"""Reference data: Vocabulary and Concept rows from the ConceptRegistry (TODO 2.4).

Concepts are input data, not generated, so these factories just carry the
registry's values. Every column is declared so the drift check sees it.
"""

import factory
from common_access_model.datamodel.common_access_model_sqla import Concept, Vocabulary
from sqlalchemy.orm import Session

from cam_testdata.concepts import ConceptRecord, ConceptRegistry
from cam_testdata.factories.base import BaseFactory, bind_session


class VocabularyFactory(BaseFactory):
    class Meta:
        model = Vocabulary

    vocabulary_prefix = factory.Sequence(lambda n: f"V{n}")
    name = None
    vocabulary_uri = factory.LazyAttribute(
        lambda o: f"https://example.org/vocab/{o.vocabulary_prefix}/"
    )
    vocabulary_id = None
    fhir_system = factory.LazyAttribute(
        lambda o: f"https://example.org/vocab/{o.vocabulary_prefix}"
    )
    description = None
    version = None
    vocabulary_source = None


class ConceptFactory(BaseFactory):
    class Meta:
        model = Concept

    concept_curie = factory.LazyAttribute(
        lambda o: f"{o.vocabulary_prefix}:{o.concept_code}"
    )
    concept_id = None
    vocabulary_prefix = "V0"
    concept_code = factory.Sequence(lambda n: f"{n:07d}")
    display = None
    definition = None


class MissingVocabularyError(ValueError):
    pass


def load_reference(
    session: Session, registry: ConceptRegistry, full: bool = False
) -> tuple[int, int]:
    """Insert Vocabulary then Concept rows: the concepts the build used, or all of them.

    Returns (vocabularies, concepts) inserted. Vocabularies are flushed first:
    there's no ORM relationship Concept -> Vocabulary, so the unit of work
    wouldn't order them (docs/notes/vertical_slice.md).
    """
    concepts: list[ConceptRecord] = registry.used_concepts()
    if full:
        by_curie = {c.concept_curie: c for c in registry.all_concepts()}
        by_curie.update({c.concept_curie: c for c in concepts})
        concepts = [by_curie[k] for k in sorted(by_curie)]

    vocabularies, missing = registry.vocabularies_for(concepts)
    if missing:
        raise MissingVocabularyError(
            f"concepts use prefixes with no Vocabulary entry: {missing}; add them to data/vocab_gaps.yaml"
        )

    with bind_session(session):
        for vocab in vocabularies:
            VocabularyFactory(**vocab.row())
        session.flush()
        for concept in concepts:
            ConceptFactory(**concept.row())
        session.flush()
    return len(vocabularies), len(concepts)
