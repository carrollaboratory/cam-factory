from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cam_testdata.build import Build
from cam_testdata.factories import all_factories
from cam_testdata.factories.base import ABSENT, PRESENT, link, pk_of
from cam_testdata.factories.biospecimen import (
    AliquotFactory,
    BiospecimenCollectionFactory,
    SampleFactory,
)
from cam_testdata.factories.clinical import EncounterFactory, SubjectAssertionFactory
from cam_testdata.factories.family import make_family
from cam_testdata.factories.files import FileFactory
from cam_testdata.factories.study import (
    AccessPolicyFactory,
    DOIFactory,
    InvestigatorFactory,
    StudyFactory,
    attach_doi,
)
from cam_testdata.factories.subject import DemographicsFactory, SubjectFactory

DOMAIN_MODULES = tuple(
    f"cam_testdata.factories.{m}"
    for m in ("study", "subject", "family", "clinical", "biospecimen", "files")
)
ENTITY_FACTORIES = [f for f in all_factories() if f.__module__ in DOMAIN_MODULES]


def count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.parametrize("factory_class", ENTITY_FACTORIES, ids=lambda f: f.__name__)
def test_each_factory_writes_one_valid_row(
    session: Session, factory_class: Any
) -> None:
    build = Build("test")
    with build.active():
        obj = factory_class()
    build.write(session)
    model = factory_class._meta.model
    assert session.get(model, pk_of(obj)) is not None
    assert count(session, model) == 1


def test_scoping_is_inherited(session: Session) -> None:
    build = Build("test")
    with build.active():
        sample = SampleFactory()
        aliquot = AliquotFactory(sample=sample)
    build.write(session)
    assert aliquot.study_id == sample.study_id is not None
    assert aliquot.access_policy_id == sample.access_policy_id is not None


def test_ids_follow_handles_and_pins() -> None:
    build = Build("test")
    with build.active():
        study = StudyFactory(handle="test/Study/s1", pinned_id="sd-7hwpqzc2yr")
        subject = SubjectFactory(handle="test/Subject/a", scope=study)
        again = Build("test")
    with again.active():
        same = SubjectFactory(handle="test/Subject/a", scope=study)
    assert study.study_id == "sd-7hwpqzc2yr"
    assert (
        subject.subject_id.startswith("pt-") and subject.subject_id == same.subject_id
    )


def test_default_external_id_is_handle_uri(session: Session) -> None:
    from common_access_model.datamodel.common_access_model_sqla import SubjectExternalId

    build = Build("test")
    with build.active():
        subject = SubjectFactory(handle="test/Subject/x")
        explicit = SubjectFactory(
            handle="test/Subject/y", external_id=["https://example.org/other"]
        )
    build.write(session)
    rows = dict(
        session.execute(
            select(SubjectExternalId.Subject_subject_id, SubjectExternalId.external_id)
        ).all()
    )
    assert rows[subject.subject_id] == "https://example.org/cam-testdata/test/Subject/x"
    assert rows[explicit.subject_id] == "https://example.org/other"


def test_study_doi_cycle(session: Session) -> None:
    build = Build("test")
    with build.active():
        study = StudyFactory()
        doi = DOIFactory(scope=study)
        attach_doi(study, doi)
    build.write(session)
    session.refresh(study)
    assert study.do_id == doi.do_id and doi.do_id.startswith(
        "https://doi.org/10.5072/cam-testdata."
    )


def test_self_reference_parents_first(session: Session) -> None:
    build = Build("test")
    with build.active():
        # PK order would put the child first; the Build must still insert the parent first.
        blood = SampleFactory(handle="test/Sample/zz-blood")
        child = SampleFactory(handle="test/Sample/aa-dna", parent=blood)
        parent_study = StudyFactory()
        StudyFactory(parent=parent_study)
    build.write(session)
    assert child.parent_sample_id == blood.sample_id
    assert child.biospecimen_collection_id == blood.biospecimen_collection_id
    assert child.subject_id == blood.subject_id
    assert child.sample_type == "OBI:0001051" and blood.sample_type == "UBERON:0000178"


def test_age_at_collection_converts_days_to_years(session: Session) -> None:
    build = Build("test")
    with build.active():
        encounter = EncounterFactory(age_at_event=1826)
        collection = BiospecimenCollectionFactory(encounter=encounter)
    build.write(session)
    assert collection.age_at_collection == 5.0


def test_assertion_traits(session: Session) -> None:
    from common_access_model.datamodel.common_access_model_sqla import (
        SubjectAssertionConcept,
        SubjectAssertionValueConcept,
    )

    build = Build("test")
    with build.active():
        subject = SubjectFactory()
        present = SubjectAssertionFactory(
            subject=subject, present=True, concept=["HP:0000821"]
        )
        absent = SubjectAssertionFactory(
            subject=subject, absent=True, concept=["HP:0000821"]
        )
        measured = SubjectAssertionFactory(subject=subject, measurement=True)
    build.write(session)
    values = dict(
        session.execute(
            select(
                SubjectAssertionValueConcept.SubjectAssertion_assertion_id,
                SubjectAssertionValueConcept.value_concept_concept_curie,
            )
        ).all()
    )
    assert values == {present.assertion_id: PRESENT, absent.assertion_id: ABSENT}
    assert present.assertion_id.startswith("ob-")
    assert measured.value_number is not None and measured.value_unit.startswith("ucum:")
    concepts = session.scalars(
        select(SubjectAssertionConcept.concept_concept_curie).where(
            SubjectAssertionConcept.SubjectAssertion_assertion_id
            == measured.assertion_id
        )
    ).all()
    assert concepts and concepts[0].startswith("loinc:")


def test_file_hashes_are_real_digests(session: Session) -> None:
    import hashlib

    from common_access_model.datamodel.common_access_model_sqla import HashDigest

    build = Build("test")
    with build.active():
        f = FileFactory(handle="test/File/f1", hash=["MS:1000568", "MS:1000569"])
    build.write(session)
    digests = dict(
        session.execute(select(HashDigest.hash_type, HashDigest.hash_value)).all()
    )
    expected = f"{build.seed}|test/File/f1".encode()
    assert digests == {
        "MS:1000568": hashlib.md5(expected).hexdigest(),
        "MS:1000569": hashlib.sha1(expected).hexdigest(),
    }
    assert f.filename.startswith("f1.")


def test_make_family_trio(session: Session) -> None:
    from common_access_model.datamodel.common_access_model_sqla import (
        FamilyMembership,
        FamilyRelationship,
    )

    build = Build("test")
    with build.active():
        study = StudyFactory()
        unit = make_family("trio", study, "trio1")
    build.write(session)
    assert count(session, FamilyMembership) == 3
    rels = session.execute(
        select(
            FamilyRelationship.family_member_id,
            FamilyRelationship.relation,
            FamilyRelationship.subject_id,
        )
    ).all()
    assert unit.mother and unit.father
    assert set(rels) == {
        (unit.mother.subject_id, "KIN:027", unit.proband.subject_id),
        (unit.father.subject_id, "KIN:028", unit.proband.subject_id),
    }


def test_filler_does_not_shift_when_records_are_added() -> None:
    a = Build("test")
    with a.active():
        alone = InvestigatorFactory(handle="test/Investigator/pi")
    b = Build("test")
    with b.active():
        for i in range(5):
            InvestigatorFactory(handle=f"test/Investigator/other-{i}")
        crowded = InvestigatorFactory(handle="test/Investigator/pi")
    assert (alone.name, alone.email, alone.id) == (
        crowded.name,
        crowded.email,
        crowded.id,
    )
    assert alone.email.endswith("@example.org")


def test_empty_strings_become_null() -> None:
    build = Build("test")
    with build.active():
        ap = AccessPolicyFactory(access_description="", website="")
    assert ap.access_description is None and ap.website is None


def test_link_requires_a_join_table() -> None:
    build = Build("test")
    with build.active(), pytest.raises(TypeError, match="join table"):
        link(SubjectFactory(), "subject_type", ["CAMO:0000024"])


def test_demographics_race_list(session: Session) -> None:
    from common_access_model.datamodel.common_access_model_sqla import DemographicsRace

    build = Build("test")
    with build.active():
        d = DemographicsFactory(race=["CDCREC:2054-5", "CDCREC:2106-3"])
        default = DemographicsFactory()
    build.write(session)
    races = session.execute(
        select(
            DemographicsRace.Demographics_subject_id,
            DemographicsRace.race_concept_curie,
        )
    ).all()
    assert sorted(r for s, r in races if s == d.subject_id) == [
        "CDCREC:2054-5",
        "CDCREC:2106-3",
    ]
    assert [r for s, r in races if s == default.subject_id] == ["snomedct:261665006"]
