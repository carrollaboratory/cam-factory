import pytest

from cam_testdata.schema_introspect import ColumnStorage, JoinStorage, Model, get_model


@pytest.fixture(scope="module")
def model() -> Model:
    return get_model()


# DESIGN §5.1
EXPECTED_GLOBAL_IDS = {
    "AccessPolicy": ("access_policy_id", ("co",)),
    "Study": ("study_id", ("sd",)),
    "VirtualBiorepository": ("vbr_id", ("or",)),
    "Subject": ("subject_id", ("pt",)),
    "Family": ("family_id", ("gr",)),
    "FamilyRelationship": ("family_relationship_id", ("fm",)),
    "SubjectAssertion": ("assertion_id", ("ob", "de", "ms")),
    "Sample": ("sample_id", ("bs",)),
    "Encounter": ("encounter_id", ("en",)),
    "EncounterDefinition": ("encounter_definition_id", ("pd",)),
    "ActivityDefinition": ("activity_definition_id", ("ad",)),
    "File": ("file_id", ("dr",)),
    "Assay": ("assay_id", ("di",)),
    "Dataset": ("dataset_id", ("ls",)),
    "Person": ("person_id", ("pn",)),
}


def test_global_id_prefixes_match_design(model: Model) -> None:
    assert model.global_id_prefixes() == EXPECTED_GLOBAL_IDS


def test_every_table_class_has_an_id_scheme(model: Model) -> None:
    kinds = {cls: model.id_spec(cls).kind for cls in model.table_classes}
    assert kinds["Demographics"] == kinds["StudyMetadata"] == "parent"
    assert kinds["DOI"] == "doi"
    assert {
        kinds[c] for c in ("FamilyMembership", "BiospecimenCollection", "Aliquot")
    } == {"local"}
    assert {kinds[c] for c in ("Investigator", "Publication", "HashDigest")} == {"int"}
    assert kinds["Concept"] == kinds["Vocabulary"] == "reference"


def test_demographics_race_resolves_to_join_table(model: Model) -> None:
    store = model.storage("Demographics", "race")
    assert isinstance(store, JoinStorage)
    assert store.table.name == "Demographics_race"
    assert store.owner_column.name == "Demographics_subject_id"
    assert store.value_column.name == "race_concept_curie"


def test_entity_list_resolves_through_secondary_table(model: Model) -> None:
    store = model.storage("Study", "principal_investigator")
    assert isinstance(store, JoinStorage)
    assert (store.table.name, store.owner_column.name, store.value_column.name) == (
        "Study_principal_investigator",
        "Study_study_id",
        "principal_investigator_id",
    )
    store = model.storage("Assay", "file_id")
    assert isinstance(store, JoinStorage)
    assert store.value_column.name == "file_id_file_id"


def test_single_valued_slot_is_a_column(model: Model) -> None:
    store = model.storage("Subject", "subject_type")
    assert isinstance(store, ColumnStorage)
    assert (store.table.name, store.column.name) == ("Subject", "subject_type")


def test_every_multivalued_slot_with_sql_storage_resolves(model: Model) -> None:
    for cls in model.table_classes:
        for name, slot in model.slots(cls).items():
            if (
                slot.multivalued and name != "hash"
            ):  # File.hash is an inlined object list
                assert isinstance(model.storage(cls, name), JoinStorage), (
                    f"{cls}.{name}"
                )


def test_required_multivalued_slots(model: Model) -> None:
    tables = {
        f"{cls}.{slot}": store.table.name
        for cls in model.table_classes
        for slot, store in model.required_storage(cls, multivalued=True).items()
    }
    assert tables == {
        "Demographics.race": "Demographics_race",
        "Study.program": "Study_program",
        "Study.principal_investigator": "Study_principal_investigator",
        "Study.contact": "Study_contact",
        "StudyMetadata.participant_lifespan_stage": "StudyMetadata_participant_lifespan_stage",
        "StudyMetadata.study_design": "StudyMetadata_study_design",
        "StudyMetadata.clinical_data_source_type": "StudyMetadata_clinical_data_source_type",
        "StudyMetadata.data_category": "StudyMetadata_data_category",
        "StudyMetadata.research_domain": "StudyMetadata_research_domain",
        "VirtualBiorepository.contact": "VirtualBiorepository_contact",
        "Person.subject_id": "Person_subject_id",
    }


def test_range_kinds(model: Model) -> None:
    assert model.range_info("Encounter", "subject_id").kind == "entity"
    assert model.range_info("Encounter", "subject_id").target == "Subject"
    info = model.range_info("Demographics", "sex")
    assert info.kind == "concept" and info.enums == ("EnumSex", "EnumUnknownOther")
    assert model.range_info("AccessPolicy", "data_use_permission").kind == "enum"
    info = model.range_info("Study", "program")
    assert info.kind == "uriorcurie" and info.enums == ("EnumProgram",)
    assert model.range_info("Study", "study_title").kind == "literal"


def test_concept_ranged_slots_are_concept_fks_in_sql(model: Model) -> None:
    concept_fk = {
        (c.cls, c.slot) for c in model.curie_columns if c.kind == "concept_fk"
    }
    for cls in model.table_classes:
        if cls in ("Concept", "Vocabulary"):
            continue
        for name in model.slots(cls):
            if model.range_info(cls, name).kind == "concept":
                assert (cls, name) in concept_fk, f"{cls}.{name}"


def test_curie_columns_cover_all_three_mechanisms(model: Model) -> None:
    by_key = {(c.table, c.column): c.kind for c in model.curie_columns}
    assert by_key[("Demographics_race", "race_concept_curie")] == "concept_fk"
    assert by_key[("AccessPolicy", "data_use_permission")] == "enum"
    assert (
        by_key[("StudyMetadata_clinical_data_source_type", "clinical_data_source_type")]
        == "enum"
    )
    assert by_key[("Sample_processing", "processing")] == "uriorcurie"
    assert by_key[("Sample", "sample_type")] == "uriorcurie"
    assert ("Study_external_id", "external_id") not in by_key
    assert ("Study_program", "program") not in by_key


def test_units_come_from_the_schema(model: Model) -> None:
    assert model.slot_unit("Encounter", "age_at_event") == "d"
    assert model.slot_unit("BiospecimenCollection", "age_at_collection") == "a"
    assert model.slot_unit("Study", "study_title") is None


def test_permissible_value_lookup(model: Model) -> None:
    pv = model.find_permissible_value("CAMO:0000024")
    assert pv is not None and pv.title == "Participant"
    assert model.find_permissible_value("KIN:028") is not None  # EnumFamilyRelation
    assert model.find_permissible_value("NOPE:1") is None
