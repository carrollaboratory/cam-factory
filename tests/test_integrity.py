"""Integrity rules (TODO 4.1/4.2): the valid dataset is clean, and each rule catches a
deliberate violation made with SQL inside the test's rolled-back transaction."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Table, delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cam_testdata import db
from cam_testdata.schema_introspect import get_model
from cam_testdata.validate.integrity import RULES, Violation, run_all
from dataset import Dataset, build_dataset


def T(name: str) -> Table:
    return db.metadata().tables[name]


@pytest.fixture
def data(session: Session) -> Iterator[Dataset]:
    dataset = build_dataset()
    dataset.build.write(session)
    yield dataset


def check(session: Session, rule: str) -> list[Violation]:
    return RULES[rule](session.connection(), get_model())


def run(session: Session, stmt: Any) -> None:
    session.execute(stmt)


def test_valid_dataset_passes_every_rule(session: Session, data: Dataset) -> None:
    results = run_all(session.connection())
    assert {rule: v for rule, v in results.items() if v} == {}


def test_r1_scope_columns_and_parent_study(session: Session, data: Dataset) -> None:
    # Since CAM v0.2.1 the DDL itself rejects NULL scoping (MODEL_ISSUES #21) ...
    with pytest.raises(IntegrityError), session.begin_nested():
        run(
            session,
            update(T("Subject"))
            .where(T("Subject").c.subject_id == data["father"].subject_id)
            .values(access_policy_id=None),
        )
    # ... so R1's job here is the parent chain
    run(
        session,
        update(T("Encounter"))
        .where(T("Encounter").c.encounter_id == data["enc"].encounter_id)
        .values(study_id=data["s2"].study_id),
    )
    details = {(v.table, v.detail.split(":")[0]) for v in check(session, "R1")}
    assert any(t == "Encounter" and d.startswith("subject_id=") for t, d in details)


def test_r1_allows_investigators_shared_across_studies(
    session: Session, data: Dataset
) -> None:
    pi = T("Study_principal_investigator")
    s1_pi = (
        session.execute(pi.select().where(pi.c.Study_study_id == data["s1"].study_id))
        .mappings()
        .one()["principal_investigator_id"]
    )
    run(
        session,
        insert(pi).values(
            Study_study_id=data["s2"].study_id, principal_investigator_id=s1_pi
        ),
    )
    assert check(session, "R1") == []


def test_r2_required_multivalued(session: Session, data: Dataset) -> None:
    run(
        session,
        delete(T("Study_program")).where(
            T("Study_program").c.Study_study_id == data["s1"].study_id
        ),
    )
    assert [v.detail for v in check(session, "R2")] == [
        "required program has no rows in Study_program"
    ]


def test_r3_participant_needs_demographics(session: Session, data: Dataset) -> None:
    run(
        session,
        update(T("Subject"))
        .where(T("Subject").c.subject_id == data["sibling"].subject_id)
        .values(subject_type="CAMO:0000024"),
    )
    violations = check(session, "R3")
    assert [(v.key, v.detail) for v in violations if v.table == "Subject"] == [
        (data["sibling"].subject_id, "Participant without Demographics")
    ]


def test_r4_lineage(session: Session, data: Dataset) -> None:
    run(
        session,
        update(T("Sample"))
        .where(T("Sample").c.sample_id == data["dna"].sample_id)
        .values(biospecimen_collection_id=data["mdna"].biospecimen_collection_id),
    )
    run(
        session,
        update(T("BiospecimenCollection"))
        .where(
            T("BiospecimenCollection").c.biospecimen_collection_id
            == data["coll"].biospecimen_collection_id
        )
        .values(encounter_id=None),
    )
    details = {v.detail.split(" ")[0] for v in check(session, "R4")}
    assert {"derived", "no"} <= details


def test_r5_family(session: Session, data: Dataset) -> None:
    rel = T("FamilyRelationship")
    first = session.execute(rel.select().limit(1)).mappings().one()
    run(
        session,
        update(rel)
        .where(rel.c.family_relationship_id == first["family_relationship_id"])
        .values(family_member_id=first["subject_id"]),
    )
    other = (
        session.execute(
            rel.select()
            .where(rel.c.family_relationship_id != first["family_relationship_id"])
            .limit(1)
        )
        .mappings()
        .one()
    )
    run(
        session,
        update(rel)
        .where(rel.c.family_relationship_id == other["family_relationship_id"])
        .values(family_member_id=data["s2p1"].subject_id),
    )
    details = sorted(v.detail for v in check(session, "R5"))
    assert (
        "self-relationship" in details
        and "ends aren't members of one Family" in details
    )


def test_r6_linkage(session: Session, data: Dataset) -> None:
    fs = T("File_subject_id")
    run(session, delete(fs).where(fs.c.File_file_id == data["cram"].file_id))
    sa = T("SubjectAssertion")
    run(
        session,
        update(sa)
        .where(
            sa.c.subject_id == data["mother"].subject_id, sa.c.encounter_id.is_(None)
        )
        .values(encounter_id=data["enc"].encounter_id),
    )
    run(
        session,
        update(T("Sample"))
        .where(T("Sample").c.sample_id == data["blood"].sample_id)
        .values(subject_id=data["mother"].subject_id),
    )
    tables = sorted({v.table for v in check(session, "R6")})
    assert tables == ["File", "Sample", "SubjectAssertion"]


def test_r7_ages(session: Session, data: Dataset) -> None:
    enc, sa, coll = T("Encounter"), T("SubjectAssertion"), T("BiospecimenCollection")
    run(
        session,
        update(enc)
        .where(enc.c.encounter_id == data["s2enc"].encounter_id)
        .values(age_at_event=26000),
    )
    run(
        session,
        update(sa)
        .where(sa.c.assertion_id == data["present"].assertion_id)
        .values(age_at_event=-1),
    )
    run(
        session,
        update(sa)
        .where(sa.c.age_at_resolution.is_not(None))
        .values(age_at_resolution=1),
    )
    run(
        session,
        update(coll)
        .where(
            coll.c.biospecimen_collection_id == data["coll"].biospecimen_collection_id
        )
        .values(age_at_collection=4.0),
    )
    details = " / ".join(v.detail for v in check(session, "R7"))
    for fragment in (
        "> age_at_last_vital_status",
        "age_at_event=-1 < 0",
        "age_at_resolution 1 <",
        "age_at_collection 4.0",
    ):
        assert fragment in details


def test_r8_participant_count(session: Session, data: Dataset) -> None:
    meta = T("StudyMetadata")
    run(
        session,
        update(meta)
        .where(meta.c.study_id == data["s1"].study_id)
        .values(actual_number_of_participants=99),
    )
    assert [v.key for v in check(session, "R8")] == [data["s1"].study_id]


def test_r9_concept_coverage(session: Session, data: Dataset) -> None:
    run(
        session,
        update(T("Sample"))
        .where(T("Sample").c.sample_id == data["dna"].sample_id)
        .values(sample_type="UBERON:9999999"),
    )
    assert [(v.table, v.key) for v in check(session, "R9")] == [
        ("Sample", "UBERON:9999999")
    ]


def test_r10_id_formats(session: Session, data: Dataset) -> None:
    s1 = data["s1"]
    run(
        session,
        insert(T("Subject")).values(
            subject_id="xx-0123456789",
            subject_type="CAMO:0000025",
            study_id=s1.study_id,
            access_policy_id=s1.access_policy_id,
        ),
    )
    run(
        session,
        insert(T("Aliquot")).values(
            aliquot_id="alq-NOPE",
            sample_id=data["dna"].sample_id,
            study_id=s1.study_id,
            access_policy_id=s1.access_policy_id,
        ),
    )
    keys = {(v.table, v.key) for v in check(session, "R10")}
    assert keys == {("Subject", "xx-0123456789"), ("Aliquot", "alq-NOPE")}


def test_r11_natural_keys(session: Session, data: Dataset) -> None:
    fm = T("FamilyMembership")
    row = session.execute(fm.select().limit(1)).mappings().one()
    run(session, insert(fm).values({**row, "family_membership_id": "fmb-0000000000"}))
    hd, fh = T("HashDigest"), T("File_hash")
    run(session, insert(hd).values(id=7, hash_type="MS:1000568", hash_value="0" * 32))
    run(session, insert(fh).values(File_file_id=data["cram"].file_id, hash_id=7))
    tables = sorted(v.table for v in check(session, "R11"))
    assert tables == ["FamilyMembership", "File"]


def test_r12_no_empty_strings(session: Session, data: Dataset) -> None:
    run(
        session,
        update(T("Study"))
        .where(T("Study").c.study_id == data["s1"].study_id)
        .values(website=""),
    )
    assert [(v.table, v.detail) for v in check(session, "R12")] == [
        ("Study", "website is ''")
    ]


def test_every_rule_has_a_negative_test() -> None:
    tested = {
        name.split("_")[1].upper()
        for name in globals()
        if name.startswith("test_r") and name[6].isdigit()
    }
    assert tested == set(RULES)
