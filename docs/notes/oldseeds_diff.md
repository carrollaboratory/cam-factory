# Old seeds vs current DDL

Compared 2026-10-01 (TODO 0.4) against common_access_model 0.2.0.

## Column fit

Every table seed maps onto a current table with **no missing and no extra
columns**, except `research_study.csv`. Header order differs from SQLAlchemy
column order in the entity files, which doesn't matter because we export in
SQLA order.

| File | Table | Columns |
|---|---|---|
| access_policy.csv (2 rows) | AccessPolicy | exact |
| study.csv (1) | Study | exact |
| research_study.csv (1) | Study | older shape: missing `website`, `acknowledgments`, `citation_statement`, `do_id`; superseded by study.csv |
| doi.csv (1), doi_external_id.csv (1) | DOI, DOI_external_id | exact |
| investigator.csv (2) | Investigator | exact |
| publication.csv (1), publication_external_id.csv (1) | Publication, Publication_external_id | exact |
| study_contact / study_external_id / study_principal_investigator / study_program / study_publication | matching `Study_*` join tables | exact |

## Values no longer valid

- `study_program.program`: `include`, `kf`. `EnumProgram` values are now URIs
  (`https://www.nih.gov/include-project`, `https://commonfund.nih.gov/KidsFirst`).
- `access_policy.disease_limitation`: `MSH:D012919`. The column is a free
  string, so it isn't invalid, but the schema's MeSH prefix is `mesh`. Use
  `mesh:D012919` if we keep a curie there.
- `access_policy.data_use_accession`: `dbgap:phs000000` is lowercase, while
  `study_external_id` and `prefix_fhir_systems.csv` use `DBGAP`. Pick one;
  `DBGAP` matches the FHIR system mapping.
- `doi_external_id`: `DOI:DOI-ext-M00!994abf` contains `!`, which isn't a
  valid curie local part.

## Worth reusing

- **IDs** that downstream tests may reference: `sd-7hwpqzc2yr` (Study),
  `co-ajdm9fyxxz`, `co-t869rg8xx6` (AccessPolicy), all valid under the Q1
  regex. Pin them in `tiny.yaml` (DESIGN §5.1), e.g. S1 = `sd-7hwpqzc2yr` and
  the controlled/open policies. The DOI `10.1738/2024.99p6kxef` gets replaced
  by the `10.5072/cam-testdata.*` scheme (Q2).
- **Study text**: "Madamoiselle Moo's Marvelous Research Study", code `M00M00`,
  short name, description, citation, acknowledgments, website. They're clearly
  fake and recognizable, which suits S1.
- **Access policy**: `DUO:0000042` (general research use) + modifier
  `DUO:0000045` (not-for-profit use only). Both are valid PVs. This is a good
  "open" policy. The tiny "controlled" policy needs `DUO:0000007` + a disease
  limitation.
- **Study external IDs**: `DBGAP:phs000000`, `CUD:M00M00-01`. A good example
  of multiple external IDs on one record.
- Investigator IDs `12345`, `234421` and Publication `12345` are integers;
  `mint_int` replaces them unless pinned.

## Personal data (AGENTS.md rule 10)

`investigator.csv` has two real-looking people with `@vumc.org` emails. These
are **committed in git** (`data/oldseeds/` is tracked), and the repo is meant
to go public. They won't reach `output/`, since investigators are Faker names
with `example.org` emails, but the user may want to scrub them from the
repo before publishing.

## Non-seed files

- **`prefix_fhir_systems.csv`**: one row, `DBGAP` →
  `https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=`.
  That's the only FHIR-system hint here; it doesn't cover the eight enum
  prefixes missing a Vocabulary (see vocab_content.md).
- **`harmony.csv`**: 2469 rows of LinkML `gen-harmony` output (enum PV → code
  system URI + display). It's from an **older model**: `EnumRace`, `EnumSex`,
  `EnumEthnicity`, `EnumResearchDomain`, `EnumVitalStatus` and
  `EnumAvailabilityStatus` share no codes with the current enums;
  `EnumConsanguinityAssertion`, `EnumDownSyndromeStatus` and `EnumNull` no
  longer exist; EDAM and spatial-qualifier counts differ. Its `code_system`
  values are prefix URIs (`http://snomed.info/id/`), not FHIR systems. **Not
  useful as input**; the current schema's enum PVs supersede it.
