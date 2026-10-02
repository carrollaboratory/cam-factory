"""Integrity rules R1-R12 (DESIGN §6.2). One function per rule; each returns the
offending rows as Violations, and a clean database returns an empty list.

Rules are driven by the schema (Record classes, parent FKs, required multivalued
slots, coded columns, units) and settings (natural keys). The few class names
that appear here are the ones a rule is defined by (e.g. R3: StudyMetadata).
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import (
    Column,
    Connection,
    Enum,
    String,
    Table,
    exists,
    func,
    literal,
    or_,
    select,
)

from cam_testdata import db
from cam_testdata.concepts import is_uri
from cam_testdata.factories.biospecimen import days_to_years
from cam_testdata.schema_introspect import ColumnStorage, JoinStorage, Model, get_model

PARTICIPANT = "CAMO:0000024"  # EnumSubjectType "Participant" (R3, R8)
SCOPE_COLUMNS = ("study_id", "access_policy_id")
# FKs between Record tables that legitimately cross studies (R1).
CROSS_STUDY_FKS = {("Study", "parent_study")}
# Records that may be linked from any study: one investigator can serve several
# studies (MODEL_ISSUES #24; the Record mixin on Investigator is likely an error).
CROSS_STUDY_TARGETS = {"Investigator"}
AGE_UNITS = {"d", "a"}  # UCUM day / year


@dataclass(frozen=True)
class Violation:
    table: str
    key: str
    detail: str


Rule = Callable[[Connection, Model], list[Violation]]


# ----- helpers -------------------------------------------------------------------


def _t(model: Model, name: str) -> Table:
    table: Table = model.metadata.tables[name]
    return table


def _pk(table: Table) -> Column:  # type: ignore[type-arg]
    cols = list(table.primary_key.columns)
    if len(cols) != 1:
        raise ValueError(f"{table.name} has a composite key")
    return cols[0]


def _record_classes(model: Model) -> list[str]:
    return [
        c
        for c in model.table_classes
        if "Record" in model.sv.class_ancestors(c) and c != "Record"
    ]


def _rows(conn: Connection, stmt, table: str, detail: str) -> list[Violation]:  # type: ignore[no-untyped-def]
    return [
        Violation(table, str(r[0]), detail.format(*r[1:])) for r in conn.execute(stmt)
    ]


# ----- R1 Record scoping ---------------------------------------------------------------


def r1_record_scoping(conn: Connection, model: Model) -> list[Violation]:
    """Record rows have study_id and access_policy_id; children share their parent's study."""
    out: list[Violation] = []
    records = _record_classes(model)
    record_tables = {_t(model, c) for c in records}
    for cls in records:
        table = _t(model, cls)
        for col in SCOPE_COLUMNS:
            if col in table.c:
                stmt = (
                    select(_pk(table))
                    .where(table.c[col].is_(None))
                    .order_by(_pk(table))
                )
                out += _rows(conn, stmt, cls, f"{col} is NULL")

    # FK columns from a Record table to another Record table
    for child in sorted(record_tables, key=lambda t: t.name):
        for fk in sorted(child.foreign_keys, key=lambda f: f.parent.name):
            parent = fk.column.table
            fk_col = fk.parent
            if parent not in record_tables or fk_col.name in SCOPE_COLUMNS:
                continue
            if (child.name, fk_col.name) in CROSS_STUDY_FKS:
                continue
            p = parent.alias("parent") if parent is child else parent
            stmt = (
                select(_pk(child), fk_col, child.c.study_id, p.c.study_id)
                .join(p, fk_col == p.c[fk.column.name])
                .where(child.c.study_id.is_distinct_from(p.c.study_id))
                .order_by(_pk(child))
            )
            out += _rows(
                conn,
                stmt,
                child.name,
                f"{fk_col.name}={{0}}: study {{1}} != parent's {{2}}",
            )

    # join tables linking two Record tables (File_subject_id, Study_contact, ...)
    for cls in records:
        for slot, s in model.slots(cls).items():
            if not s.multivalued or slot == "external_id":
                continue
            store = model.storage(cls, slot)
            if not isinstance(store, JoinStorage):
                continue
            target_fk = next(iter(store.value_column.foreign_keys), None)
            if target_fk is None or target_fk.column.table not in record_tables:
                continue
            if target_fk.column.table.name in CROSS_STUDY_TARGETS:
                continue
            owner, target = _t(model, cls), target_fk.column.table.alias("target")
            stmt = (
                select(
                    store.owner_column,
                    store.value_column,
                    owner.c.study_id,
                    target.c.study_id,
                )
                .join(owner, store.owner_column == _pk(owner))
                .join(target, store.value_column == target.c[target_fk.column.name])
                .where(owner.c.study_id.is_distinct_from(target.c.study_id))
            )
            out += _rows(
                conn, stmt, store.table.name, f"{slot}={{0}}: study {{1}} != {{2}}"
            )
    return out


# ----- R2 Required multivalued slots ----------------------------------------------------


def r2_required_multivalued(conn: Connection, model: Model) -> list[Violation]:
    out: list[Violation] = []
    for cls in model.table_classes:
        for slot, store in model.required_storage(cls, multivalued=True).items():
            assert isinstance(store, JoinStorage)
            owner = _t(model, cls)
            stmt = (
                select(_pk(owner))
                .where(~exists().where(store.owner_column == _pk(owner)))
                .order_by(_pk(owner))
            )
            out += _rows(
                conn, stmt, cls, f"required {slot} has no rows in {store.table.name}"
            )
    return out


# ----- R3 One-to-one tables -------------------------------------------------------------


def r3_one_to_one(conn: Connection, model: Model) -> list[Violation]:
    study, meta = _t(model, "Study"), _t(model, "StudyMetadata")
    subject, demo = _t(model, "Subject"), _t(model, "Demographics")
    out = _rows(
        conn,
        select(study.c.study_id).where(
            ~exists().where(meta.c.study_id == study.c.study_id)
        ),
        "Study",
        "no StudyMetadata",
    )
    out += _rows(
        conn,
        select(subject.c.subject_id).where(
            subject.c.subject_type == PARTICIPANT,
            ~exists().where(demo.c.subject_id == subject.c.subject_id),
        ),
        "Subject",
        "Participant without Demographics",
    )
    return out


# ----- R4 Specimen lineage ----------------------------------------------------------------


def r4_specimen_lineage(conn: Connection, model: Model) -> list[Violation]:
    sample, coll = _t(model, "Sample"), _t(model, "BiospecimenCollection")
    parent = sample.alias("parent")
    out = _rows(
        conn,
        select(sample.c.sample_id).where(sample.c.biospecimen_collection_id.is_(None)),
        "Sample",
        "no biospecimen_collection_id",
    )
    out += _rows(
        conn,
        select(coll.c.biospecimen_collection_id).where(coll.c.encounter_id.is_(None)),
        "BiospecimenCollection",
        "no encounter_id",
    )
    out += _rows(
        conn,
        select(sample.c.sample_id, parent.c.sample_id)
        .join(parent, sample.c.parent_sample_id == parent.c.sample_id)
        .where(
            or_(
                sample.c.biospecimen_collection_id.is_distinct_from(
                    parent.c.biospecimen_collection_id
                ),
                sample.c.subject_id.is_distinct_from(parent.c.subject_id),
            )
        ),
        "Sample",
        "derived from {0} but collection or subject differs",
    )
    return out


# ----- R5 Family coherence ------------------------------------------------------------------


def r5_family_coherence(conn: Connection, model: Model) -> list[Violation]:
    rel, mem = _t(model, "FamilyRelationship"), _t(model, "FamilyMembership")
    a, b = mem.alias("a"), mem.alias("b")
    same_family = (
        select(literal(1))
        .select_from(a.join(b, a.c.family_id == b.c.family_id))
        .where(
            a.c.subject_id == rel.c.family_member_id, b.c.subject_id == rel.c.subject_id
        )
        .exists()
    )
    pk = rel.c.family_relationship_id
    out = _rows(
        conn,
        select(pk).where(rel.c.family_member_id == rel.c.subject_id),
        rel.name,
        "self-relationship",
    )
    out += _rows(
        conn,
        select(pk).where(~same_family),
        rel.name,
        "ends aren't members of one Family",
    )
    return out


# ----- R6 Linkage consistency ------------------------------------------------------------------


def r6_linkage(conn: Connection, model: Model) -> list[Violation]:
    out: list[Violation] = []
    sample = _t(model, "Sample")
    for cls in ("File", "Assay"):
        s_store, p_store = (
            model.storage(cls, "sample_id"),
            model.storage(cls, "subject_id"),
        )
        assert isinstance(s_store, JoinStorage) and isinstance(p_store, JoinStorage)
        st, pt = s_store.table, p_store.table
        stmt = (
            select(s_store.owner_column, s_store.value_column)
            .join(sample, s_store.value_column == sample.c.sample_id)
            .where(
                ~exists().where(
                    pt.c[p_store.owner_column.name] == st.c[s_store.owner_column.name],
                    pt.c[p_store.value_column.name] == sample.c.subject_id,
                )
            )
        )
        out += _rows(conn, stmt, cls, "links sample {0} but not its subject")

    sa, enc = _t(model, "SubjectAssertion"), _t(model, "Encounter")
    out += _rows(
        conn,
        select(sa.c.assertion_id, sa.c.encounter_id)
        .join(enc, sa.c.encounter_id == enc.c.encounter_id)
        .where(enc.c.subject_id != sa.c.subject_id),
        "SubjectAssertion",
        "encounter {0} belongs to a different subject",
    )
    coll = _t(model, "BiospecimenCollection")
    out += _rows(
        conn,
        select(sample.c.sample_id, enc.c.subject_id)
        .join(
            coll, sample.c.biospecimen_collection_id == coll.c.biospecimen_collection_id
        )
        .join(enc, coll.c.encounter_id == enc.c.encounter_id)
        .where(sample.c.subject_id != enc.c.subject_id),
        "Sample",
        "subject differs from its collection's encounter subject {0}",
    )
    return out


# ----- R7 Ages ------------------------------------------------------------------------------------


def r7_ages(conn: Connection, model: Model) -> list[Violation]:
    out: list[Violation] = []
    for cls in model.table_classes:
        for slot in model.slots(cls):
            if model.slot_unit(cls, slot) not in AGE_UNITS:
                continue
            store = model.storage(cls, slot)
            assert isinstance(store, ColumnStorage)
            table = store.table
            out += _rows(
                conn,
                select(_pk(table), store.column).where(store.column < 0),
                cls,
                f"{slot}={{0}} < 0",
            )

    demo, sa, enc = (
        _t(model, "Demographics"),
        _t(model, "SubjectAssertion"),
        _t(model, "Encounter"),
    )
    for table, pk in ((enc, enc.c.encounter_id), (sa, sa.c.assertion_id)):
        out += _rows(
            conn,
            select(pk, table.c.age_at_event, demo.c.age_at_last_vital_status)
            .join(demo, demo.c.subject_id == table.c.subject_id)
            .where(table.c.age_at_event > demo.c.age_at_last_vital_status),
            table.name,
            "age_at_event {0} > age_at_last_vital_status {1}",
        )
    out += _rows(
        conn,
        select(sa.c.assertion_id, sa.c.age_at_resolution, sa.c.age_at_event).where(
            sa.c.age_at_resolution < sa.c.age_at_event
        ),
        sa.name,
        "age_at_resolution {0} < age_at_event {1}",
    )
    coll = _t(model, "BiospecimenCollection")
    stmt = select(
        coll.c.biospecimen_collection_id, coll.c.age_at_collection, enc.c.age_at_event
    ).join(enc, coll.c.encounter_id == enc.c.encounter_id)
    for pk, years, days in conn.execute(stmt):
        expected = days_to_years(days)
        if years != expected:
            out.append(
                Violation(
                    coll.name,
                    pk,
                    f"age_at_collection {years} != encounter {days} d = {expected} a",
                )
            )
    return out


# ----- R8 Participant count ----------------------------------------------------------------------


def r8_participant_count(conn: Connection, model: Model) -> list[Violation]:
    meta, subject = _t(model, "StudyMetadata"), _t(model, "Subject")
    counted = (
        select(func.count())
        .where(
            subject.c.study_id == meta.c.study_id, subject.c.subject_type == PARTICIPANT
        )
        .scalar_subquery()
    )
    stmt = select(meta.c.study_id, meta.c.actual_number_of_participants, counted).where(
        meta.c.actual_number_of_participants != counted
    )
    return _rows(
        conn,
        stmt,
        meta.name,
        "actual_number_of_participants {0} != {1} Participant subjects",
    )


# ----- R9 Concept coverage ----------------------------------------------------------------------


def r9_concept_coverage(conn: Connection, model: Model) -> list[Violation]:
    concept, vocab = _t(model, "Concept"), _t(model, "Vocabulary")
    known = set(conn.execute(select(concept.c.concept_curie)).scalars())
    out: list[Violation] = []
    for cc in model.curie_columns:
        column = _t(model, cc.table).c[cc.column]
        values = conn.execute(
            select(column).distinct().where(column.is_not(None)).order_by(column)
        ).scalars()
        for value in values:
            if not is_uri(str(value)) and value not in known:
                out.append(
                    Violation(cc.table, str(value), f"{cc.column}: not in Concept")
                )
    out += _rows(
        conn,
        select(concept.c.concept_curie, concept.c.vocabulary_prefix).where(
            ~exists().where(vocab.c.vocabulary_prefix == concept.c.vocabulary_prefix)
        ),
        concept.name,
        "vocabulary_prefix {0} not in Vocabulary",
    )
    return out


# ----- R10 ID formats ----------------------------------------------------------------------------


def r10_id_formats(conn: Connection, model: Model) -> list[Violation]:
    """GlobalIDs match the format and their class's prefix(es); local IDs and DOIs too."""
    ids = model.settings.ids
    out: list[Violation] = []
    for cls in model.table_classes:
        spec = model.id_spec(cls)
        if spec.kind not in ("global", "local", "doi"):
            continue
        table = _t(model, cls)
        for value in conn.execute(
            select(table.c[spec.slot]).order_by(table.c[spec.slot])
        ).scalars():
            if spec.kind == "global":
                ok = any(ids.global_id_regex(p).fullmatch(value) for p in spec.prefixes)
                want = f"a {'/'.join(spec.prefixes)} GlobalID"
            elif spec.kind == "local":
                ok = bool(
                    ids.global_id_regex(spec.prefixes[0]).fullmatch(value)
                )  # same shape, 3-letter prefix
                want = f"a {spec.prefixes[0]}- local ID"
            else:
                ok = (
                    value.startswith(ids.doi_prefix)
                    and len(value) == len(ids.doi_prefix) + ids.doi_length
                )
                want = f"a DOI under {ids.doi_prefix}"
            if not ok:
                out.append(Violation(cls, value, f"{spec.slot} isn't {want}"))
    return out


# ----- R11 Natural keys --------------------------------------------------------------------------


def r11_natural_keys(conn: Connection, model: Model) -> list[Violation]:
    out: list[Violation] = []
    for table_name, keys in sorted(model.settings.natural_keys.items()):
        table = _t(model, table_name)
        for key in keys:
            cols = [table.c[c] for c in key]
            stmt = select(*cols, func.count()).group_by(*cols).having(func.count() > 1)
            for row in conn.execute(stmt):
                out.append(
                    Violation(
                        table_name,
                        "|".join(map(str, row[:-1])),
                        f"{row[-1]} rows share ({', '.join(key)})",
                    )
                )

    store = model.storage("File", "hash")
    assert isinstance(store, JoinStorage)
    digest = _t(model, "HashDigest")
    stmt = (
        select(store.owner_column, digest.c.hash_type, func.count())
        .join(digest, store.value_column == digest.c.id)
        .group_by(store.owner_column, digest.c.hash_type)
        .having(func.count() > 1)
    )
    out += _rows(conn, stmt, "File", "{1} digests of type {0}")
    return out


# ----- R12 No empty strings ------------------------------------------------------------------------


def r12_no_empty_strings(conn: Connection, model: Model) -> list[Violation]:
    out: list[Violation] = []
    for table in db.registry_tables(model.settings):
        for column in table.columns:
            # Enum subclasses String, but native enums can't hold '' anyway
            if not isinstance(column.type, String) or isinstance(column.type, Enum):
                continue
            pk = list(table.primary_key.columns)
            key = pk[0] if len(pk) == 1 else func.concat_ws("|", *pk)
            out += _rows(
                conn,
                select(key).where(column == ""),
                table.name,
                f"{column.name} is ''",
            )
    return out


RULES: dict[str, Rule] = {
    "R1": r1_record_scoping,
    "R2": r2_required_multivalued,
    "R3": r3_one_to_one,
    "R4": r4_specimen_lineage,
    "R5": r5_family_coherence,
    "R6": r6_linkage,
    "R7": r7_ages,
    "R8": r8_participant_count,
    "R9": r9_concept_coverage,
    "R10": r10_id_formats,
    "R11": r11_natural_keys,
    "R12": r12_no_empty_strings,
}


def run_all(conn: Connection, model: Model | None = None) -> dict[str, list[Violation]]:
    model = model or get_model()
    return {rule_id: rule(conn, model) for rule_id, rule in RULES.items()}
