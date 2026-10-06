# CAM Test Data Generator — Design

Status: draft for implementation by an agent (see `AGENTS.md`, `TODO.md`).
Model version at time of writing: `common_access_model` 0.2.0.

## 1. Purpose

Produce small, deterministic, referentially correct example data for the Common
Access Model (CAM), in three interchangeable shapes:

| Consumer | Needs | Artifact |
|---|---|---|
| dbt staging → JSONB/FHIR pipeline | per-table seeds, small enough to trace by hand | `output/<profile>/csv/*.csv` (dbt yml helpers deferred, Q10) |
| Portal team | a loadable warehouse in the real DDL | `output/<profile>/sql/cam_<profile>.sql` (pg_dump) |
| LinkML model repo | example instances that validate against the schema | `output/<profile>/yaml/<Class>.yaml` and `output/tiny/examples/<Class>-NNN.yaml` |

The data is mostly static. It is regenerated only when (a) the model changes or
(b) a bigger profile is needed. Every run with the same inputs must produce
byte-identical outputs so diffs in git are meaningful.

Non-goals: minting real global IDs, producing FHIR JSON (that is the dbt
pipeline's job), loading all of SNOMED, simulating realistic statistics.

## 2. Inputs

| Input | Location | Notes |
|---|---|---|
| LinkML schema (monolith) | `data/common_access_model.yaml` (symlink to versioned file) | Read with `linkml_runtime.SchemaView` for enums, required slots, class→slot shape, ID types |
| SQLAlchemy model | `common_access_model.datamodel.common_access_model_sqla` (installed dependency) | The DDL source of truth; factories bind to these classes |
| Pydantic model | `common_access_model.datamodel.*pydantic*` (discover exact module) | Optional fast validation of YAML output |
| Real concept/vocab content | `data/vocab_content.yaml` | Top-level key per vocabulary prefix holding `Vocabulary` columns plus a `codes:` list of `Concept` columns. Built by the user with `scripts/collect_concepts.py` from INCLUDE harmony CSVs (`scripts/pull_harmony_data.py`) and `data/vocabulary_meta.yaml`. Treated as an input; the generator never regenerates it |
| User-supplied extra concepts | `data/vocab_gaps.yaml` → `data/additional_vocab_content.yaml` | The user lists vocabularies (with `fhir_system`) and codes in `vocab_gaps.yaml`; `scripts/follow_up_codes.py` looks the codes up (OLS, OWL, OBO JSON, or manual) and writes `additional_vocab_content.yaml` in the same shape as `vocab_content.yaml` |
| Tiny scenario | `scenarios/tiny.yaml` | Hand-authored, declarative description of the tiny dataset (§8.2) |
| Old hand-made seeds | `data/oldseeds/*.csv` | Reference for realistic values and naming; diffed against current DDL in Phase 0. `harmony.csv` (code mappings) and `prefix_fhir_systems.csv` (prefix → FHIR system) are not table seeds. Personal data in them (real names, emails) must never be copied into outputs |

## 3. Architecture

```
                      ┌────────────────────────┐
schema YAML ─────────▶│ schema_introspect      │  enums, required slots,
SQLA metadata ───────▶│ (SchemaView + metadata)│  ID prefixes, table registry
                      └──────────┬─────────────┘
vocab_content.yaml ─┐            │
additional_vocab_ ───┤          │
   content.yaml       ├▶ concepts ─┤  ConceptRegistry (resolve / fallback / report)
enum PV titles ─────┘            │
                                 ▼
tiny.yaml / profile YAML ──▶ scenario (tiny: declarative loader | scaled: config-driven)
                                 │  uses
                                 ▼
                      factories (factory_boy) → Build (collect, then ordered write)
                                 │  flush into
                                 ▼
                      PostgreSQL  (db per profile, schema "cam")   ◀── source of truth for a build
                                 │
                 ┌───────────────┼──────────────────┬───────────────┐
                 ▼               ▼                  ▼               ▼
            integrity checks  CSV export       YAML export      pg_dump SQL
            (SQL queries)     (per table)      (per class)      (+ manifest.json)
```

Build command: `cam-testdata build --profile tiny` (wrapped by `just tiny`).
One run = reset DB → load reference data → run scenario → commit → validate →
export all artifacts → write manifest. A failing validation aborts before export.

### 3.1 Why Postgres is the build target and YAML is the committed review format

The factories write through SQLAlchemy into Postgres, so the real constraints
(PKs, FKs, NOT NULL, native enum types) are enforced by the database itself,
not by our code. Everything else is exported from the database. The YAML is the
human-reviewable, LinkML-shaped view; CSV and SQL are table-shaped views of the
same rows.

Two kinds of YAML exist and must not be confused:

- `scenarios/tiny.yaml` is **authored**: short, uses fixture-local keys, omits
  anything the factories fill in (§8.2). To reproduce a bug in tiny, edit it and
  rebuild; no factory code changes needed.
- `output/<profile>/yaml/` is **exported**: full LinkML instances with real IDs,
  generated from the database.

Optional later phase: `cam-testdata load-yaml` rebuilds the DB from *exported*
LinkML YAML (e.g. instances someone edited in the model repo).

### 3.2 Project layout

```
cam-testdata/
├── AGENTS.md  CLAUDE.md  TODO.md  justfile  pyproject.toml
├── docs/DESIGN.md  docs/SCENARIO_TINY.md  docs/MODEL_ISSUES.md
├── config/
│   ├── settings.yaml            # id alphabet/length, db url template, schema name
│   ├── concept_pools.yaml       # slot/enum -> curated curies to draw from
│   └── profiles/{tiny,small,portal}.yaml
├── data/                        # inputs (see §2)
├── src/cam_testdata/
│   ├── cli.py                   # typer: build, export, validate, missing-concepts, check-drift, load-yaml
│   ├── settings.py
│   ├── ids.py                   # deterministic GlobalID + local ID minting
│   ├── schema_introspect.py
│   ├── concepts.py              # ConceptRegistry
│   ├── db.py                    # engine, reset, create tables, sequence fix-up
│   ├── factories/{base,reference,study,subject,family,clinical,biospecimen,files}.py
│   ├── scenarios/{loader,scaled}.py   # loader: declarative scenario YAML → factories
│   ├── export/{csv_export,yaml_export,sql_export,manifest}.py
│   └── validate/{integrity,required,concept_coverage,coverage,linkml_check,roundtrip}.py
├── scenarios/tiny.yaml          # authored tiny scenario (§8.2)
├── output/
│   ├── tiny/   {csv/, yaml/, examples/, sql/, id_map.csv, manifest.json}
│   ├── small/  (same; also published as a release artifact)
│   └── portal/ (gitignored; release artifact only; see §9)
└── tests/
```

## 4. Database handling

- Postgres runs in a local Docker container (`just pg-up`; image `postgres:18.6` pinned by digest, since
  the SQL dump headers record the server version,
  `POSTGRES_HOST_AUTH_METHOD=trust`, published on `127.0.0.1` only). `pg-up`
  creates `cam_testdata_{tiny,small,portal,test}` if missing.
- One database per profile: `cam_testdata_<profile>`, URL
  `postgresql://postgres@localhost:5432/cam_testdata_<profile>`. URL template in
  `config/settings.yaml`, overridable by env `CAM_PG_URL`.
- `pg_dump` and `psql` are not assumed on the host. Their commands are settings
  (default: `docker exec <container> pg_dump …`), so the client always matches
  the server version.
- All tables live in schema `cam`. Set it with connection option
  `options=-csearch_path=cam` so that both tables and the native PG enum types
  that SQLAlchemy's `Enum(..., name=...)` creates land in `cam`. Verify this in
  Phase 1 (enum types must not end up in `public`).
- Reset with `DROP SCHEMA IF EXISTS cam CASCADE; CREATE SCHEMA cam;` rather than
  `metadata.drop_all()`, because the model contains FK cycles (§5.3).
- Create tables with `metadata.create_all(engine, tables=<registry>)`. The
  registry excludes `Any`, `Record`, `Record_external_id` by default (the
  abstract mixin was emitted as a table; see MODEL_ISSUES). This is a setting,
  not hard-coded.
- Tables use mixed-case names (`"Study"`, `"Demographics_race"`) and some columns
  are mixed-case (`"Study_study_id"`). Every hand-written SQL string must quote
  identifiers. Prefer SQLAlchemy Core expressions over raw SQL.
- Integer autoincrement PKs (`Investigator`, `Publication`, `HashDigest`,
  `Synonym`, `DeprecatedConcept`, `ConceptRelationship`) get explicit,
  deterministic values from the factories. After loading, run `setval` on each
  sequence to `max(id)` so anyone inserting new rows later does not collide.

## 5. Identifiers

### 5.1 Global IDs (`*GlobalID` types)

Format: `<2-char prefix>-<10 chars of [0-9a-z]>`, e.g. `pt-3c9n2ear2w`
(regex `^[a-z]{2}-[0-9a-z]{10}$`; confirmed against real IDs, Q1). The prefix
is the first two letters of the slot's range type name (`ptGlobalID` → `pt`);
derive this mapping from SchemaView, don't hard-code it. The schema's
`*GlobalID` types declare no `pattern`, so the regex lives in
`config/settings.yaml`.

| Class | ID slot | Prefix (FHIR resource) |
|---|---|---|
| AccessPolicy | access_policy_id | co (Consent) |
| Study | study_id | sd (ResearchStudy) |
| VirtualBiorepository | vbr_id | or (Organization) |
| Subject | subject_id | pt (Patient) |
| Family | family_id | gr (Group) |
| FamilyRelationship | family_relationship_id | fm (FamilyMemberHistory) |
| SubjectAssertion | assertion_id | ob (Observation). The type allows `de` / `ms` too; not simulated yet (Q8) |
| Sample | sample_id | bs (Specimen) |
| Encounter | encounter_id | en (Encounter) |
| EncounterDefinition | encounter_definition_id | pd (PlanDefinition) |
| ActivityDefinition | activity_definition_id | ad (ActivityDefinition) |
| File | file_id | dr (DocumentReference) |
| Assay | assay_id | di (DiagnosticReport) |
| Dataset | dataset_id | ls (List) |

Demographics and StudyMetadata reuse their parent's ID (`subject_id`, `study_id`).

Minting is deterministic and does **not** use the `nanoid` library (it draws from
`os.urandom` and cannot be seeded). Instead:

```
id = prefix + "-" + encode(sha256(f"{profile_seed}|{handle}"), alphabet, size)
```

where `handle` is a stable, human-readable key such as
`tiny/subject/trio1-proband` or `small/study2/subject/0017`. Consequences:
adding a record never changes the IDs of existing records, and IDs are stable
across runs. `alphabet` and `size` come from `config/settings.yaml` and must
match the production minting service (open question Q1). Mint through a
registry that raises on any collision.

**Explicit overrides.** A record may pin its ID (the `id:` field in scenario
YAML, §8.2), e.g. to reuse an ID that existing dbt tests or old seeds already
reference (`sd-7hwpqzc2yr`). Pinned IDs go through the same registry: they
must match the format regex and the expected prefix, and they collide like any
other ID.

**Integer PKs** (`Investigator.id`, `Publication.id`, `HashDigest.id`, …) are
deterministic too: an explicit `id` if given, otherwise `ids.mint_int(table,
handle)`, collision-checked per table.

### 5.2 Non-global string IDs

`DOI.do_id`, `FamilyMembership.family_membership_id`,
`BiospecimenCollection.biospecimen_collection_id`, `Aliquot.aliquot_id` are plain
strings (Q2). DOIs use the DataCite test prefix plus a hashed suffix,
`10.5072/cam-testdata.<8 chars of [0-9a-z]>`, the same shape as the fake
`10.1738/2024.99p6kxef` in the old seeds. The others use the same hashing scheme
with a 3-letter local prefix (`fmb-`, `bsc-`, `alq-`) so they can never be
mistaken for global IDs.

### 5.3 Human traceability

Random-looking IDs are hard to follow by hand, so every record that carries the
`Record` mixin gets one `external_id`. External IDs are URIs, so the default is
derived from the record's handle under the reserved `example.org` domain:
`https://example.org/cam-testdata/<profile>/<Class>/<key>`, e.g.
`https://example.org/cam-testdata/tiny/Subject/trio1-proband`. A record that
lists its own `external_id` values in the scenario uses those instead (e.g.
S1's dbGaP study URL). In addition, `output/<profile>/id_map.csv` lists
`handle, table, id, external_id` for every row.

## 6. Referential and semantic correctness

### 6.1 Enforced by Postgres

PK uniqueness, NOT NULL, FK existence, and enum membership (native PG enums).
The FK graph contains cycles that the scenario code must respect:

- `Study.do_id → DOI` and `DOI.study_id → Study`: insert Study with `do_id`
  NULL, flush, insert DOI, then set `Study.do_id`, flush.
- `Study.parent_study`, `Sample.parent_sample_id`: self-references; insert parents first.

Join tables have no cycles of their own; they insert after both parents.

`pg_dump` output handles cycles because it adds FK constraints after the data.

### 6.2 Enforced by our validators (fail the build)

Implemented as SQL queries in `validate/integrity.py`, each returning offending
rows. Each rule has an ID so failures are easy to reference.

- **R1 Record scoping**: every `Record`-mixin row has non-null `study_id` and
  `access_policy_id`. A child's `study_id` equals its parent chain's
  (Encounter→Subject, BiospecimenCollection→Encounter, Sample→BiospecimenCollection,
  Aliquot→Sample, SubjectAssertion→Subject, FamilyMembership→Family, etc.).
  Join-table links between Record tables stay within one study too, except
  links to Investigator: one investigator can serve several studies
  (MODEL_ISSUES #24). `Study.parent_study` naturally crosses studies.
- **R2 Required multivalued slots** (generic, from SchemaView): every
  required+multivalued slot has ≥1 row in its join table (e.g. `Study_program`,
  `Study_principal_investigator`, `Study_contact`, `Demographics_race`,
  `StudyMetadata_study_design`, `StudyMetadata_research_domain`,
  `StudyMetadata_data_category`, `StudyMetadata_participant_lifespan_stage`,
  `StudyMetadata_clinical_data_source_type`).
- **R3 One-to-one tables**: exactly one `StudyMetadata` per Study; exactly one
  `Demographics` per Subject whose `subject_type` is Participant.
- **R4 Specimen lineage**: in the data we generate, every
  `Sample.biospecimen_collection_id` and `BiospecimenCollection.encounter_id`
  is set. Both are nullable in the model (MODEL_ISSUES #20), but we don't
  generate orphans. A derived sample shares its parent's collection and subject.
- **R5 Family coherence**: both ends of every `FamilyRelationship` are members of
  the same Family via `FamilyMembership`; no self-relationships.
- **R6 Linkage consistency**: if a File or Assay links a Sample, it also links
  that Sample's Subject. If a SubjectAssertion has an `encounter_id`, the
  Encounter's subject equals the assertion's subject. `Sample.subject_id`
  equals the subject of its collection's encounter.
- **R7 Ages**: units come from each slot's `unit.ucum_code` in the schema (Q3),
  never assumed. Today every `age_*` slot is integer days (`d`) except
  `BiospecimenCollection.age_at_collection`, which is decimal years (`a`, float).
  All ages ≥ 0; `age_at_event` ≤ `age_at_last_vital_status` when both are set;
  `age_at_resolution` ≥ `age_at_event`; `age_at_collection` equals its
  Encounter's `age_at_event` converted to years (`round(days / 365.25, 2)`, the
  same function the factory uses).
- **R8 Participant count**: `StudyMetadata.actual_number_of_participants` equals
  the count of Participant subjects in that study.
- **R9 Concept coverage**: every curie emitted anywhere (FK columns, enum columns,
  join tables, `sample_type`, `processing`, `storage_method`, `organism_type`)
  exists in `Concept`, and every `Concept.vocabulary_prefix` exists in `Vocabulary`.
  FK columns are already enforced by Postgres; R9 extends coverage to enum and
  uriorcurie columns so dbt can always join for a display string. Full URIs
  (e.g. `Study_program` values from the "preferred" `EnumProgram`) are exempt;
  only curies must resolve.
- **R10 GlobalID prefixes**: every value in a `*GlobalID` column (PKs and the FK
  columns that point at them) matches the ID format and carries the prefix
  derived from its range type (§5.1). For `any_of` slots (SubjectAssertion),
  the prefix is one of the allowed set. Local IDs (`fmb-`, `bsc-`, `alq-`) and
  DOIs are checked against their formats too. This checks what is in the
  database, including pinned IDs, not just what `ids.py` minted.

- **R11 Natural keys** (the model has no unique constraints, MODEL_ISSUES #19):
  no two rows share a natural key. Initial set: `FamilyMembership`
  (`family_id`, `subject_id`); `FamilyRelationship` (`family_member_id`,
  `relation`, `subject_id`); `File_hash` at most one digest per hash type per
  file; `HashDigest` (`hash_type`, `hash_value`). The set lives in
  `config/settings.yaml` (`natural_keys`) so it can grow without code changes.
- **R12 No empty strings**: no text column holds `''`. CSV can't tell `''` from
  NULL, so an empty string would load as NULL from the CSV but stay `''` from
  the SQL dump. Factories and the loader normalize `''` to NULL.

## 7. Concepts and vocabularies

`ConceptRegistry` resolves a curie in this order:

1. `data/vocab_content.yaml` (real content, source=`vocab_content`)
2. `data/additional_vocab_content.yaml` (user-pulled via `vocab_gaps.yaml`, source=`extra`)
3. The enum permissible value in the schema, which has `title` and often
   `description` (source=`linkml_enum`). This covers most enum curies without
   downloading anything.
4. Otherwise: recorded as missing.

`cam-testdata missing-concepts --profile X` runs the scenario in dry-run mode and
writes `output/X/missing_concepts.csv` (curie, used_by table.column, count) and
`output/X/vocab_gaps_stub.yaml` (missing codes grouped by prefix, in
`vocab_gaps.yaml` format) so the user can pull exactly those terms. Prefixes
with concepts but no Vocabulary row are reported too. The build fails on any
missing curie or vocabulary.

Only concepts actually used by the profile (plus their vocabularies) are loaded
into `Concept`, which keeps the tiny seed readable. A `--full-reference` flag
loads everything from `vocab_content.yaml` for the portal profile.

`config/concept_pools.yaml` limits large enums to a small realistic set, e.g. a
handful of assay types (WGS, RNA-seq, methylation array), file formats (CRAM,
VCF, FASTQ, TSV), and collection methods. Every pooled curie is checked against
the enum's permissible values at startup, which catches model drift. Scaled
profiles draw from the same pools and should reuse tiny's curies where
possible, so the terminology set only grows when a profile needs new coverage.

Pools aren't only for enums:

- **`family_role`** (range `Concept`, `EnumFamilyRole` is only a suggestion):
  restricted to the enum's terms plus the family-member terms the user added
  to `data/vocab_gaps.yaml`. Don't add others.
- **Measurements**: (concept, unit) pairs for numeric SubjectAssertions, e.g.
  height `loinc:8302-2` / `ucum:cm`, weight `loinc:29463-7` / `ucum:kg`, BMI
  `loinc:39156-5` / `ucum:kg/m2` (all in vocab_content).
- **Open-ended Sample slots** (`sample_type`, `processing`, `storage_method`):
  the codes listed in `docs/notes/model_inventory.md`.

Malformed curies in the input (e.g. `loinc:Hemoglobin-level-at-birth`) are
left alone and never pooled. They came from production harmony files and are
reported upstream by the user.

Concept prefixes must match the schema's declared prefixes exactly (case
included), and every `Concept.vocabulary_prefix` must match a
`Vocabulary.vocabulary_prefix` exactly. Mismatches in input data (e.g. a
vocabulary filed under the wrong prefix) are reported, not patched silently.

Vocabularies that the schema uses but does not declare as prefixes (CAMO, and UCUM
for units) need `Vocabulary` rows; source them from `vocab_content.yaml` if
present, otherwise from a small `config/vocabularies_extra.yaml`.

## 8. Factories and scenarios

- One factory per mapped class. Factories don't touch the session: they create
  transient objects that the active `Build` (`build.py`) collects. `Build.write()`
  resolves every coded value, loads only the used Vocabulary/Concept rows, then
  inserts table by table in FK order (self-referencing tables parent-first, the
  Study ↔ DOI cycle per §6.1) and fixes sequences. The scenario runner owns
  commit. The ORM can't order these inserts itself because many FKs have no
  `relationship()` (docs/notes/vertical_slice.md).
- Factory conventions (`factories/base.py`): a `handle` param drives the ID,
  Faker filler, pool choices and default external_id. Faker and the RNG are
  reseeded per (seed, handle, field), so adding a record never changes another
  record's values. A `scope` param supplies study_id/access_policy_id (R1).
  Many-valued slots are passed as lists under their LinkML names. Every column
  is declared, so the drift check catches new ones.
- Factories set only column values plus explicit join-table rows. Multivalued
  relationships are populated by creating the association-class rows
  (`StudyProgram`, `DemographicsRace`, …) through their own small factories.
  This keeps the mapping to CSV one-to-one and avoids surprises with
  `secondary=` relationships.
- Faker is used only for filler text (descriptions, names, bibliographic
  references). Seed with `factory.random.reseed_random(seed)` and a fixed locale.
  Values that matter to the pipeline (curies, ages, links) are chosen explicitly
  by the scenario or from `concept_pools.yaml` with the seeded RNG.
- **tiny** is a hand-authored story (§8.1) written as data in
  `scenarios/tiny.yaml` (format in §8.2) and fed through the same factories by
  `scenarios/loader.py`. No random sampling. Its "cast" is documented in
  `docs/SCENARIO_TINY.md`, which is regenerated from `id_map.csv` so it never
  goes stale.
- **small / portal** (`scenarios/scaled.py`) are driven by
  `config/profiles/*.yaml`: number of studies, subjects per study, family
  structure mix (trio / duo / singleton), probabilities and Poisson means for
  encounters, assertions, samples, files, and assays per subject.

### 8.1 Tiny scenario (target ≈220 non-reference rows, about a third of them `*_external_id`)

Designed so every FHIR mapping path and every nullable/edge branch is exercised
at least once.

- **Program**: INCLUDE.
- **Access policies (2)**: controlled (DS, disease limitation Down syndrome, one
  modifier) and open (GRU).
- **Study S1 "Trio study"** (controlled): StudyMetadata, DOI, 1 Publication,
  2 Investigators (PI, contact), 1 VirtualBiorepository, external IDs.
- **Study S2** (open), `parent_study = S1`, minimal metadata.
- **Subjects (5)**: S1 proband (female, two races), mother, father (ethnicity
  unknown), sibling as a Non-Participant with no Demographics; S2 one
  participant (sex unknown, deceased).
- **Family (1)**: 4 memberships (proband role on the proband), 3 relationships
  (mother→proband, father→proband, sibling→proband).
- **Definitions**: 2 EncounterDefinitions, 3 ActivityDefinitions (clinical
  assessment, blood draw, WGS) linked via the join table.
- **Encounters (5)**: proband 2, mother 1, father 1, S2 participant 1.
- **SubjectAssertions (~7)**: proband Down syndrome (present), a congenital heart
  phenotype (present), a phenotype with `value_concept` absent, a numeric
  measurement with `value_number` + `value_unit` (UCUM); mother 1; S2 participant
  1 condition with `age_at_resolution`. At least one assertion without an encounter.
  All assertions are `ob` (Q8) Observations: a concept being asserted plus an
  observed value (present/absent concept, or a number with a unit).
- **Biospecimens**: 3 collections (trio blood draws) → 3 blood samples → 3 derived
  DNA samples (`parent_sample_id`) → ~7 aliquots (one unavailable).
- **Files (5)**: 3 CRAM (one per DNA sample), 1 joint VCF linked to all 3
  subjects and samples, 1 clinical TSV linked to subjects only. Each has MD5; one
  also has SHA-1. Hash values are the real digest of a deterministic string.
- **Assays (3)**: WGS per DNA sample, linked to sample, subject, and CRAM.
- **Dataset (1)**: S1 files, DOI, publication.

`manifest.json` includes expected FHIR resource counts by ID prefix, which the
dbt project can assert against directly.

### 8.2 Scenario YAML format

The tiny scenario is data, not code. Draft format (to be confirmed at
CHECKPOINT A):

```yaml
scenario: tiny
records:                         # top-level keys are LinkML class names
  AccessPolicy:
    - key: ap-controlled
      data_use_permission: DUO:0000007        # disease specific research
      ...
  Study:
    - key: s1
      id: sd-7hwpqzc2yr          # optional pin (§5.1); otherwise minted from handle
      study_title: Trio study
      access_policy_id: ap-controlled         # class-ranged slot → key
      program: [https://www.nih.gov/include-project]
      principal_investigator: [pi-1]          # multivalued → list; no join tables
  Subject:
    - key: trio1-proband
      study_id: s1
      subject_type: CAMO:0000024              # Concept-ranged slot → curie
  Demographics:
    - key: trio1-proband                      # one-to-one: shares the parent's key
      sex: snomedct:248152002
      race: [CDCREC:2054-5, CDCREC:2106-3]
  Sample:
    - key: trio1-proband-dna
      parent_sample_id: trio1-proband-blood
      # biospecimen_collection_id omitted → inherited from parent sample (R4)
```

Rules:

- **Slot names are LinkML slot names**, validated against SchemaView; an
  unknown class or slot is an error. Join tables never appear.
- **Values by range.** Slots whose range is an entity class take keys from the
  same file. Slots ranged to `Concept`, enums, or `uriorcurie` take literal
  curies/URIs. Everything else is a literal.
- **Keys and handles.** `key` is required and unique per class; the handle is
  `<profile>/<Class>/<key>`. `external_id` defaults to the handle's URI form
  (§5.3) unless given.
- **Scoping is inherited.** `study_id` and `access_policy_id` may be omitted
  when the record has an R1 scoping parent; they are copied from it, and an
  explicit value that disagrees is an error. `access_policy_id` otherwise
  defaults to the record's study's policy.
- **Omitted means "factory decides".** YAML values override factory defaults.
  Omitted required fields, filler text, and computed fields (hash values,
  `age_at_collection` per R7, `actual_number_of_participants` per R8) come from
  the factories.
- **Order doesn't matter.** The loader inserts in FK dependency order from SQLA
  metadata and handles the known cycles (§6.1) by deferred update.
- **Errors name the record**: `Sample[trio1-proband-dna].parent_sample_id:
  unknown key 'trio1-probnd-blood'`.

Extra scenario files (e.g. edge-case packs) can use the same format.

### 8.3 Coverage features

Each edge case the tiny scenario exists to exercise is a named check in
`validate/coverage.py`: a query that returns the rows exhibiting it. Examples:
`derived_sample`, `assertion_without_encounter`, `non_participant_without_demographics`,
`numeric_assertion_ucum`, `condition_absent`, `deceased_subject`,
`unavailable_aliquot`, `file_multi_subject`, `file_with_two_hashes`,
`child_study`, `study_doi_cycle`. One feature per bullet in §8.1.

The manifest records each feature with the handles that satisfy it. For tiny,
every feature must be non-empty, so a scenario edit can't silently drop
coverage. The list becomes the coverage section of `SCENARIO_TINY.md`. Scaled
profiles report features but don't require them.

## 9. Outputs

All written under `output/<profile>/`, sorted and formatted for stable diffs.

**CSV** (`csv/<TableName>.csv`): one file per DDL table, file name is the exact
table name, header is SQLAlchemy column order, rows sorted by PK, NULL written as
empty, UTF-8, `\n` line endings, RFC 4180 quoting.

**dbt helpers** (`dbt/`), deferred (Q10). This project generates data;
testing with a real dbt ingest is a later discussion. Notes for when it comes back,
generated from the SQLAlchemy metadata:
- `seeds.yml` with `+quote_columns: true` and `column_types` for every column,
  so every `Text` column stays `text`. Without this, agate infers codes like
  `0000024` as integers and drops leading zeros.
- `sources.yml` with `quoting: {identifier: true}` and a `schema` driven by a var,
  so the same staging models run against seeds or against the pg_dump-loaded
  `cam` schema.

**YAML** (`yaml/<ClassName>.yaml`): a list of instances per LinkML class, shaped
by the schema (multivalued slots inlined as lists of IDs/curies, join tables
folded back in, keys ordered by the class's slot order, nulls omitted). Built
generically from SchemaView induced slots, so it follows model changes. Also
`examples/<ClassName>-001.yaml` (tiny only): one instance per file in the layout
the LinkML project cookiecutter uses for `examples/valid/`, ready to copy into
the model repo.

**SQL** (`sql/cam_<profile>.sql`): `pg_dump --schema=cam --no-owner
--no-privileges` in plain format (COPY), plus `sql/cam_<profile>_inserts.sql`:
the same full dump with `--column-inserts`, for loaders that can't handle
`COPY`. Both are full dumps on purpose. A data-only dump can't be loaded into an
existing schema once the Study ↔ DOI cycle has data, and the model's FKs
aren't deferrable (docs/notes/vertical_slice.md). `pg_dump` 18 emits a random
`\restrict` key; pass the fixed `database.restrict_key` setting as
`--restrict-key` so dumps are byte-stable. Keep the `Dumped from/by version`
lines: they only change when the Postgres image does.

**Manifest** (`manifest.json`): profile, seed, model version and schema file
sha256, package versions (SQLAlchemy, factory_boy, Faker, linkml), `pg_dump` version,
row count per table, expected FHIR counts by prefix, coverage features with
their handles (§8.3), sha256 of each artifact.
`cam-testdata check-drift` compares the manifest with the current installed model
and exits non-zero if regeneration is needed. The generator's own git commit is
deliberately left out: tiny and small outputs are committed, so a per-commit
value would change every build and `just check` could never pass. `model.shape` snapshots every table's
columns and each enum's value count and hash; `cam-testdata check-drift`
compares it with the installed model to list table, column and enum changes.
Profiles that set `record_build_time` (portal only, since its output isn't
committed) also record `build_seconds`.

**Git policy**: tiny and small outputs are committed. Small and portal are
also published as compressed release artifacts (Q6) so other projects can use
them without cloning this repo; portal is gitignored. `just dist <profile>`
writes `dist/cam-testdata-<profile>-<model version>.tar.gz` with the
profile's full output directory (manifest included), built reproducibly
(sorted entries, fixed mtimes and owners, gzip mtime 0). The user creates the
release and uploads the archives.

## 10. Validation of outputs

- Integrity rules R1–R12 against the database (§6.2).
- YAML: validate each class file with `linkml-validate` (or the Python API if
  top-level lists aren't accepted), and instantiate the pydantic models as a
  second check.
- CSV ↔ DB: row counts per table equal the manifest.
- SQL ↔ CSV round trip (`validate/roundtrip.py`, `just verify-sql`): load the
  dump into a scratch database, re-export CSV with the same exporter, and
  byte-compare with `output/<profile>/csv/`. This catches type and quoting drift
  between the two artifacts, not just missing rows.
- Coverage features (§8.3): all non-empty for tiny.
- Drift test: every table and column in the SQLAlchemy metadata is either
  produced by a factory or listed in an explicit skip list. A new column in the
  model fails the test instead of silently producing all-NULL data.

## 11. Decisions

Former open questions, now answered. There are no open questions right now;
add new ones here as `Q11`, `Q12`, ….

| # | Question | Decision |
|---|---|---|
| Q1 | GlobalID alphabet and length | 10 chars, lowercase `[0-9a-z]`; prefix from the type name (§5.1). Confirmed against real IDs |
| Q2 | Non-global string IDs | DOI `10.5072/cam-testdata.<hash>`; `fmb-` / `bsc-` / `alq-` + hash for the others (§5.2) |
| Q3 | Units of `age_*` fields | Per slot, from the schema's `unit.ucum_code` (§6.2 R7) |
| Q4 | `Any` / `Record` / `Record_external_id` tables | LinkML SQL-generator artifacts; skipped, no data |
| Q5 | Structure of `vocab_content.yaml` | See §2 |
| Q6 | Which outputs are release artifacts | small and portal (portal not committed; tiny and small committed) |
| Q7 | Postgres version for dumps | 18.6, pinned by digest in the justfile and CI; `pg_dump` runs in the container |
| Q8 | SubjectAssertion ID prefix | `ob` only. `de` (Device) and `ms` (MedicationStatement) are deferred until the expected data is clearer |
| Q9 | Package name | `cam-testdata` (repo name is the user's call) |
| Q10 | dbt | Out of scope for now: no dbt dependency, no dbt yml or seed test |

## 12. Model observations

Tracked in `docs/MODEL_ISSUES.md`, with each issue's upstream status and the
workaround used here.
