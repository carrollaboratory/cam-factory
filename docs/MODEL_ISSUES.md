# Model issues — common_access_model 0.2.0

Problems found in the model while building test data. Not fixed here (AGENTS.md
rule 3); each lists how this repo works around it. Items 1–14 come from DESIGN
§12; later items were found during Phase 0 (see `docs/notes/`).

## Schema and prefixes

1. **CAMO and UCUM aren't declared prefixes.** `CAMO` curies are used in enums
   (subject type, family type, data source type, asserter type, hash type);
   UCUM is needed for `value_unit`, `quantity_unit` and the age units.
   *Workaround:* Vocabulary rows from `config/vocabularies_extra.yaml`.
2. **`EnumDataUseModifier` contains `DUO:00000044`** (8 digits); the other DUO
   codes have 7. *Workaround:* exclude it from concept pools.
3. **KIN code styles differ**: `EnumFamilyRole` uses `KIN:027`, while
   `EnumFamilyRelation` uses `KIN:KIN_027`.
4. **`File` lists the `format` slot twice** in `slots`. Induced slots and the
   SQL table have it once. *Workaround:* use `class_induced_slots`.
11. **`EnumFamilyRole` mixes vocabularies**: SNOMED for Proband and Mother, but
    `KIN:027` ("isBiologicalMotherOf", a relation) as a role. It has no Father
    or Sibling. *Workaround:* `family_role` also accepts any Concept, so tiny
    uses `NCIT:C25174` / `NCIT:C25204` from vocab_content.
12. **`EnumProgram` permissible values are full URIs**
    (`https://www.nih.gov/include-project`), not curies.
13. **`*GlobalID` types declare no `pattern`**, so the ID format can't be
    validated from the schema. *Workaround:* regex in `config/settings.yaml`.
14. **Age units are inconsistent**: `age_at_collection` is a float in years
    (`ucum:a`); every other `age_*` slot is an integer in days (`ucum:d`).
    *Workaround:* R7 reads units per slot and converts.
15. **The `edam` prefix lacks a trailing slash**: `http://edamontology.org`, so
    `edam:format_1196` expands to `http://edamontology.orgformat_1196`.
16. **No schema version.** The schema YAML has no `version:` field, and the
    package's `_version.py` reports `0.0.0`. The version is only available
    from distribution metadata. *Workaround:* `importlib.metadata.version`.
17. **Placeholder descriptions**: `fmGlobalID`, `msGlobalID`, `pdGlobalID` say
    "Dewrangle __ global ID".
18. **No `tree_root` / container class.** A list of instances can't be
    validated without naming a target class. *Workaround:* `--target-class` per file.

## SQL / DDL

5. **Circular FK between `Study.do_id` and `DOI.study_id`** (the only
   table-level cycle). *Workaround:* insert Study, then DOI, then set `do_id`.
6. **The abstract `Record` mixin and `Any` are emitted as SQL tables**
   (plus `Record_external_id`). *Workaround:* excluded from DDL (Q4).
8. **`Synonym.concept_curie` and `ConceptRelationship.concept_curie` have no FK
   to `Concept`**, while `ConceptRelationship.target_concept_curie` does.
10. **`Sample.sample_type`, `processing`, `storage_method` are uriorcurie with
    no Concept FK**, unlike most coded fields. Coded fields use three different
    mechanisms: Concept FK, native PG enum (no Concept FK), and plain text.
    *Workaround:* R9 checks all three.
19. **No unique constraints or indexes** besides PKs. For example, nothing
    stops two `FamilyMembership` rows for the same (family, subject), and FK
    columns are unindexed (a portal-scale performance issue).
20. **Linking FKs are nullable**: `Encounter.subject_id`,
    `SubjectAssertion.subject_id`, `Sample.biospecimen_collection_id`,
    `Aliquot.sample_id`, `BiospecimenCollection.encounter_id`. A NULL leaves
    the row with no path to a subject. *Workaround:* R4 (proposed extension at
    CHECKPOINT A).
21. **Record-mixin `study_id` / `access_policy_id` are nullable** on every
    table. *Workaround:* R1.

## Semantics

7. **`Sample` has no direct subject link**; the path depends on the optional
   `BiospecimenCollection.encounter_id` (see 20).
9. **`Dataset` doesn't use the `Record` mixin**, so it has no `study_id`,
   `access_policy_id` or `external_id`.
