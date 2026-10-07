"""Coverage features (DESIGN §8.3): the edge cases a scenario exists to exercise.

Each feature is a query returning the keys of the rows that show it. The
manifest maps keys to handles; for tiny every feature must be non-empty.
"""

from collections.abc import Callable

from sqlalchemy import Connection, Table, exists, func, select

from cam_testdata import db
from cam_testdata.factories.base import ABSENT, PRESENT

NON_PARTICIPANT = "CAMO:0000025"
UNKNOWN = "snomedct:261665006"
DEAD = "snomedct:419099009"
UNAVAILABLE = "snomedct:103329007"

Feature = Callable[[Connection], list[str]]


def _t(name: str) -> Table:
    return db.metadata().tables[name]


def _keys(conn: Connection, stmt) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted({str(k) for k in conn.execute(stmt).scalars()})


def child_study(conn: Connection) -> list[str]:
    s = _t("Study")
    return _keys(conn, select(s.c.study_id).where(s.c.parent_study.is_not(None)))


def study_doi_cycle(conn: Connection) -> list[str]:
    s = _t("Study")
    return _keys(conn, select(s.c.study_id).where(s.c.do_id.is_not(None)))


def non_participant_without_demographics(conn: Connection) -> list[str]:
    s, d = _t("Subject"), _t("Demographics")
    return _keys(
        conn,
        select(s.c.subject_id).where(
            s.c.subject_type == NON_PARTICIPANT,
            ~exists().where(d.c.subject_id == s.c.subject_id),
        ),
    )


def multiple_races(conn: Connection) -> list[str]:
    r = _t("Demographics_race")
    return _keys(
        conn,
        select(r.c.Demographics_subject_id)
        .group_by(r.c.Demographics_subject_id)
        .having(func.count() > 1),
    )


def unknown_sex(conn: Connection) -> list[str]:
    d = _t("Demographics")
    return _keys(conn, select(d.c.subject_id).where(d.c.sex == UNKNOWN))


def unknown_ethnicity(conn: Connection) -> list[str]:
    d = _t("Demographics")
    return _keys(conn, select(d.c.subject_id).where(d.c.ethnicity == UNKNOWN))


def deceased_subject(conn: Connection) -> list[str]:
    d = _t("Demographics")
    return _keys(conn, select(d.c.subject_id).where(d.c.vital_status == DEAD))


def family_with_relationships(conn: Connection) -> list[str]:
    m, r = _t("FamilyMembership"), _t("FamilyRelationship")
    return _keys(
        conn,
        select(m.c.family_id)
        .join(r, r.c.subject_id == m.c.subject_id)
        .group_by(m.c.family_id)
        .having(func.count(func.distinct(r.c.family_relationship_id)) >= 3),
    )


def encounter_without_definition(conn: Connection) -> list[str]:
    e = _t("Encounter")
    return _keys(
        conn, select(e.c.encounter_id).where(e.c.encounter_definition_id.is_(None))
    )


def assertion_without_encounter(conn: Connection) -> list[str]:
    a = _t("SubjectAssertion")
    return _keys(conn, select(a.c.assertion_id).where(a.c.encounter_id.is_(None)))


def _value_concept(conn: Connection, curie: str) -> list[str]:
    v = _t("SubjectAssertion_value_concept")
    return _keys(
        conn,
        select(v.c.SubjectAssertion_assertion_id).where(
            v.c.value_concept_concept_curie == curie
        ),
    )


def condition_present(conn: Connection) -> list[str]:
    return _value_concept(conn, PRESENT)


def condition_absent(conn: Connection) -> list[str]:
    return _value_concept(conn, ABSENT)


def numeric_assertion_ucum(conn: Connection) -> list[str]:
    a = _t("SubjectAssertion")
    return _keys(
        conn,
        select(a.c.assertion_id).where(
            a.c.value_number.is_not(None), a.c.value_unit.like("ucum:%")
        ),
    )


def assertion_resolved(conn: Connection) -> list[str]:
    a = _t("SubjectAssertion")
    return _keys(
        conn, select(a.c.assertion_id).where(a.c.age_at_resolution.is_not(None))
    )


def derived_sample(conn: Connection) -> list[str]:
    s = _t("Sample")
    return _keys(conn, select(s.c.sample_id).where(s.c.parent_sample_id.is_not(None)))


def unavailable_aliquot(conn: Connection) -> list[str]:
    a = _t("Aliquot")
    return _keys(
        conn, select(a.c.aliquot_id).where(a.c.availability_status == UNAVAILABLE)
    )


def file_multi_subject(conn: Connection) -> list[str]:
    f = _t("File_subject_id")
    return _keys(
        conn,
        select(f.c.File_file_id).group_by(f.c.File_file_id).having(func.count() > 1),
    )


def file_subjects_only(conn: Connection) -> list[str]:
    fs, fsa = _t("File_subject_id"), _t("File_sample_id")
    return _keys(
        conn,
        select(fs.c.File_file_id).where(
            ~exists().where(fsa.c.File_file_id == fs.c.File_file_id)
        ),
    )


def file_with_two_hashes(conn: Connection) -> list[str]:
    h = _t("File_hash")
    return _keys(
        conn,
        select(h.c.File_file_id).group_by(h.c.File_file_id).having(func.count() > 1),
    )


def assay_links_subject_sample_file(conn: Connection) -> list[str]:
    a, su, sa, fi = (
        _t("Assay"),
        _t("Assay_subject_id"),
        _t("Assay_sample_id"),
        _t("Assay_file_id"),
    )
    return _keys(
        conn,
        select(a.c.assay_id).where(
            exists().where(su.c.Assay_assay_id == a.c.assay_id),
            exists().where(sa.c.Assay_assay_id == a.c.assay_id),
            exists().where(fi.c.Assay_assay_id == a.c.assay_id),
        ),
    )


def dataset_with_doi_and_publication(conn: Connection) -> list[str]:
    d, p = _t("Dataset"), _t("Dataset_publication")
    return _keys(
        conn,
        select(d.c.dataset_id).where(
            d.c.do_id.is_not(None),
            exists().where(p.c.Dataset_dataset_id == d.c.dataset_id),
        ),
    )


def person_record(conn: Connection) -> list[str]:
    """A Person linking at least one Subject (FHIR Person)."""
    p = _t("Person_subject_id")
    return _keys(conn, select(p.c.Person_person_id))


def person_across_studies(conn: Connection) -> list[str]:
    """A Person whose Subjects are in more than one study (scaled profiles)."""
    p, s = _t("Person_subject_id"), _t("Subject")
    return _keys(
        conn,
        select(p.c.Person_person_id)
        .join(s, s.c.subject_id == p.c.subject_id_subject_id)
        .group_by(p.c.Person_person_id)
        .having(func.count(func.distinct(s.c.study_id)) > 1),
    )


FEATURES: dict[str, Feature] = {
    f.__name__: f
    for f in (
        child_study,
        study_doi_cycle,
        non_participant_without_demographics,
        multiple_races,
        unknown_sex,
        unknown_ethnicity,
        deceased_subject,
        family_with_relationships,
        encounter_without_definition,
        assertion_without_encounter,
        condition_present,
        condition_absent,
        numeric_assertion_ucum,
        assertion_resolved,
        derived_sample,
        unavailable_aliquot,
        file_multi_subject,
        file_subjects_only,
        file_with_two_hashes,
        assay_links_subject_sample_file,
        dataset_with_doi_and_publication,
        person_record,
        person_across_studies,
    )
}

# Features tiny doesn't have to show (it has one Person with a single subject).
NOT_REQUIRED_IN_TINY = {"person_across_studies"}


def run_features(conn: Connection) -> dict[str, list[str]]:
    return {name: feature(conn) for name, feature in FEATURES.items()}


def missing_features(conn: Connection) -> list[str]:
    return [name for name, keys in run_features(conn).items() if not keys]
