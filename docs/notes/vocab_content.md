# vocab_content.yaml — structure, mapping, prefix report

Inspected 2026-10-01 (TODO 0.3). Answers Q5.

## Structure and mapping

Top level is a mapping keyed by vocabulary prefix (the key always equals
`vocabulary_prefix`). Each entry holds the `Vocabulary` columns plus a
`codes:` list of `Concept` rows. Field names match the SQLAlchemy columns
exactly, so loading is a direct column copy:

| YAML | Table.column | Notes |
|---|---|---|
| `<key>.vocabulary_prefix` | `Vocabulary.vocabulary_prefix` (PK) | |
| `<key>.name`, `description` | `Vocabulary.name`, `.description` | |
| `<key>.vocabulary_uri` | `Vocabulary.vocabulary_uri` (NOT NULL) | present for all 17 |
| `<key>.fhir_system` | `Vocabulary.fhir_system` (NOT NULL) | present for all 17 |
| `<key>.vocabulary_id`, `version`, `vocabulary_source` | same names | mostly null |
| `<key>.codes[].concept_curie` | `Concept.concept_curie` (PK) | |
| `<key>.codes[].vocabulary_prefix` | `Concept.vocabulary_prefix` → Vocabulary | always equals the parent key |
| `<key>.codes[].concept_code` | `Concept.concept_code` (NOT NULL) | always the curie's local part |
| `<key>.codes[].display`, `definition`, `concept_id` | same names | display always set |

Structural checks all pass: 1017 concepts, no duplicate curies, every curie
prefix equals its `vocabulary_prefix`, every code equals the curie's local
part, every concept has a display.

Load with `YAML(typ="safe")`: some codes look numeric, and the safe loader
keeps the quoted ones as strings. The loader should still `str()` every
`concept_code` defensively.

## Concepts per vocabulary

| Prefix | Concepts | Declared in schema? |
|---|---:|---|
| MONDO | 427 | yes |
| HP | 420 | yes (the `np` issue is fixed; no `np:` curies remain) |
| snomedct | 34 | yes |
| MAXO | 34 | no |
| loinc | 22 | yes |
| NCIT | 19 | yes |
| mesh | 17 | yes |
| ucum | 14 | no |
| cdcrec | 9 | **case mismatch**: schema declares `CDCREC` |
| v3-rolecode | 5 | no |
| meddra | 4 | no |
| administrative-gender | 4 | no |
| v3-nullflavor | 3 | no; schema declares the same system as `hl7_null` |
| specimen-status | 2 | no |
| condition-ver-status | 1 | no |
| OMIT | 1 | no |
| SYMP | 1 | no |

Undeclared prefixes are fine as Concept content (the Vocabulary row supplies
the URI and FHIR system); they only matter if a schema slot emits them.

## Problems for the user

1. **`cdcrec` vs `CDCREC`.** `EnumRace` and `EnumEthnicity` use `CDCREC:2054-5`
   etc., and `Demographics.race` / `.ethnicity` are FKs to `Concept`. The 9
   concepts here are `cdcrec:…`, so none of them match and every
   race/ethnicity value would fall back to the enum permissible value
   (resolution step 3) under a second `CDCREC` vocabulary. Likely the same
   cause as the HPO issue (`data/vocabulary_meta.yaml`). The fix is upstream;
   the generator won't case-fold.
2. **Enum prefixes with no Vocabulary entry.** The schema's enums use these
   prefixes, but `vocab_content.yaml` has no vocabulary for them: `CAMO` (also
   undeclared in the schema), `CHMO`, `DUO`, `KIN`, `MS`, `NCBITaxon`, `OBI`,
   `edam`. Concepts can come from enum PVs, but `Vocabulary` needs
   `vocabulary_uri` and `fhir_system` (both NOT NULL). URIs can come from the
   schema prefixes (except CAMO); **FHIR system URLs need a source.**
   `data/oldseeds/prefix_fhir_systems.csv` only has `DBGAP`. TODO 2.3 will
   scaffold `config/vocabularies_extra.yaml` with the schema URIs and leave
   `fhir_system` for the user to fill in.
3. **Malformed curies**: `snomedct:Cardiac pacemaker in situ (finding)` (a
   display, not a code), `loinc:Hemoglobin-level-at-birth` and `mesh:Other`
   (not real codes). They load fine, but they aren't resolvable terms; fix
   upstream or leave them out of concept pools.
4. **Concepts the tiny scenario needs that no input has**: blood and DNA
   `sample_type`, a DNA concentration unit (e.g. `ucum:ng/uL`), and
   `processing` / `storage_method` values. These go through `missing-concepts`
   (2.5) once it exists.
5. Minor: `SYMP.fhir_system` uses `https://` where every other OBO system
   uses `http://`.

## Model issues found here (→ MODEL_ISSUES)

- The schema's `edam` prefix is `http://edamontology.org` with no trailing `/`,
  so `edam:format_1196` expands to `http://edamontology.orgformat_1196`.
- `CAMO` is still undeclared (DESIGN §12.1), and so is UCUM (`ucum`).
