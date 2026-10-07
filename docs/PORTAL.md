# Portal handoff: CAM test warehouse

What the Portal team needs to load and query the generated data. The data is
fully synthetic: no real people, studies or samples.

## Getting it

- **tiny** (~330 rows) and **small** (~2,100 rows): in this repo under
  `output/<profile>/`, and as release archives (`cam-testdata-<profile>-<model version>.tar.gz`).
- **portal** (~75,000 rows, 5 studies, ~1,700 subjects, full reference
  vocabulary): release archive only.

Each archive holds `sql/`, `csv/`, `yaml/`, `id_map.csv` and `manifest.json`.
The manifest records the CAM model version the data was built with.

## Loading

```sh
createdb cam_portal
psql -d cam_portal -v ON_ERROR_STOP=1 -f sql/cam_portal.sql          # COPY
# or, for loaders without COPY:
psql -d cam_portal -v ON_ERROR_STOP=1 -f sql/cam_portal_inserts.sql  # INSERTs
```

Both are full `pg_dump`s (PostgreSQL 18) of schema **`cam`**: tables, native
enum types, primary and foreign keys, and data. Constraints are added after the
data, which is what makes the Study ↔ DOI FK cycle loadable. Add `cam` to your
`search_path` or qualify names (`cam."Study"`).

## Quoting

Table names are mixed case (`"Study"`, `"FamilyMembership"`, `"Demographics_race"`),
and so are join-table owner columns (`"Study_study_id"`, `"File_file_id"`).
**Always double-quote identifiers.** Unquoted `select * from study` won't find
the table.

## Schema overview

77 tables in `cam`:

- **24 entity tables**:
  - Study and access: AccessPolicy, Study, StudyMetadata, VirtualBiorepository, DOI, Investigator, Publication
  - Participants: Subject, Demographics, Family, FamilyMembership, FamilyRelationship
  - Clinical: EncounterDefinition, ActivityDefinition, Encounter, SubjectAssertion
  - Biospecimens: BiospecimenCollection, Sample, Aliquot
  - Data: File, HashDigest, Assay, Dataset
  - Linking: Person (one individual across studies)
- **48 join tables** for multivalued slots, named `<Class>_<slot>`:
  - `*_external_id` on every record (external IDs are URIs)
  - entity links: `Study_principal_investigator`, `File_subject_id`, `Assay_file_id`, …
  - coded values: `Demographics_race`, `SubjectAssertion_concept`, `StudyMetadata_study_design`, …
- **5 reference tables**: `Vocabulary`, `Concept` (every coded value used
  resolves to a Concept row with a display string), and `Synonym`,
  `ConceptRelationship`, `DeprecatedConcept` (empty).

Most records carry `study_id` and `access_policy_id` (the Record mixin), and
children always share their parent's study. Typical paths:

```
Study ─< Subject ─< Encounter ─< BiospecimenCollection ─< Sample ─< Aliquot
           │  └─< SubjectAssertion (optionally via Encounter)  └─ parent_sample_id (derived DNA)
           ├── Demographics (1:1 for Participants)
           └─< FamilyMembership >─ Family;  FamilyRelationship (member <relation> subject)
File >─< Subject / Sample (File_subject_id, File_sample_id);  Assay >─< Subject / Sample / File
Dataset >─< File, Publication;  Study.do_id / Dataset.do_id -> DOI
```

`Sample.subject_id` links a sample straight to its subject (it always matches
the collection's encounter subject).

### Coded columns

Three mechanisms, all resolvable to `cam."Concept"`:

1. FK to `Concept.concept_curie` (e.g. `Subject.subject_type`, `Demographics.sex`, `Demographics_race`)
2. Native PG enums whose values are curies (e.g. `AccessPolicy.data_use_permission`, `File.format`, `Assay.assay_type`)
3. Plain text curies (`Sample.sample_type`, `Sample_processing`, `Sample_storage_method`, `Subject.organism_type`)

Join `Concept` on the curie to get a display string. `Study_program` holds full
URIs (e.g. `https://www.nih.gov/include-project`), not curies.

### Units

`age_*` columns are integer **days**, except `BiospecimenCollection.age_at_collection`,
which is decimal **years** (= the encounter's `age_at_event` / 365.25, rounded to 2 places).

## IDs and FHIR resources

GlobalIDs look like `pt-0u4gl52nuc`: a 2-letter prefix naming the FHIR
resource, a hyphen, and 10 characters of `[0-9a-z]`. `manifest.json` →
`fhir_counts_by_prefix` gives the expected resource count per prefix.

| Prefix | FHIR resource | CAM table.column |
|---|---|---|
| `co` | Consent | AccessPolicy.access_policy_id |
| `sd` | ResearchStudy | Study.study_id |
| `or` | Organization | VirtualBiorepository.vbr_id |
| `pt` | Patient | Subject.subject_id |
| `gr` | Group | Family.family_id |
| `fm` | FamilyMemberHistory | FamilyRelationship.family_relationship_id |
| `ob` | Observation | SubjectAssertion.assertion_id (all assertions here) |
| `de` / `ms` | Device / MedicationStatement | SubjectAssertion.assertion_id (not generated yet) |
| `bs` | Specimen | Sample.sample_id |
| `en` | Encounter | Encounter.encounter_id |
| `pd` | PlanDefinition | EncounterDefinition.encounter_definition_id |
| `ad` | ActivityDefinition | ActivityDefinition.activity_definition_id |
| `dr` | DocumentReference | File.file_id |
| `di` | DiagnosticReport | Assay.assay_id |
| `ls` | List | Dataset.dataset_id |
| `pn` | Person | Person.person_id |

Demographics and StudyMetadata reuse their parent's ID. Non-global IDs:
FamilyMembership `fmb-…`, BiospecimenCollection `bsc-…`, Aliquot `alq-…`; DOIs
are resolver URIs with the DataCite test prefix, `https://doi.org/10.5072/cam-testdata.…`. Investigator,
Publication and HashDigest have integer keys.

## Known model issues that affect queries

Full list with status: [MODEL_ISSUES.md](MODEL_ISSUES.md).

- No unique constraints or indexes beyond primary keys (#19). Index FK columns
  yourself for larger loads.
- Record-mixin `study_id` / `access_policy_id` are nullable in the DDL (#21);
  they're always set in this data.
- `Sample.biospecimen_collection_id` and `BiospecimenCollection.encounter_id`
  are nullable by design (#20); always set here.
- `File.size` is a 32-bit `INTEGER` (#23), so sizes here stay under ~2.1 GB.
- An investigator can be linked from studies other than its own (#24).
- A Person (#25) belongs to an umbrella "Farm" study (`study_code` FARM) that
  holds no subjects; its `Person_subject_id` rows point at Subjects in real
  studies. A Person may list just one Subject (the others' studies aren't
  ingested yet).
- There's no Condition class (#22): diagnoses and observations are all `ob`
  SubjectAssertions with a present/absent value concept.
- The Study ↔ DOI FK cycle (#5) means you can't insert either row first with
  both FKs set; load the full dump rather than data-only.
