# cam-testdata

Deterministic, referentially correct test data for the
[Common Access Model](https://github.com/include-dcc/common-access-model) (CAM).
Factories write into a real PostgreSQL schema built from the model's SQLAlchemy
DDL, so the database enforces every key and enum. Everything else is exported
from that database. The same inputs always produce the same bytes, so diffs in
git mean something.

All people, studies and values are fictional (farm-themed: M00M00, MeowMeow, …).
Investigators have Faker names and `example.org` emails.

## What you get

Each profile builds into `output/<profile>/`:

| Artifact | For | Notes |
|---|---|---|
| `csv/<Table>.csv` | dbt staging / FHIR pipeline (seeds) | one file per DDL table, exact table name |
| `sql/cam_<profile>.sql` | Portal team: a loadable warehouse | full `pg_dump` of schema `cam` (COPY) |
| `sql/cam_<profile>_inserts.sql` | loaders without `COPY` support | same dump with `--column-inserts` |
| `yaml/<Class>.yaml` | LinkML model repo, review | one list of instances per class; validates against the schema |
| `examples/<Class>-001.yaml` | LinkML repo examples (tiny only) | one instance per file (see [docs/LINKML_EXAMPLES.md](docs/LINKML_EXAMPLES.md)) |
| `id_map.csv` | tracing rows by hand | `handle, table, id, external_id` |
| `manifest.json` | provenance, dbt assertions | model version, schema hash, row counts, expected FHIR resource counts by ID prefix, coverage features, artifact hashes |

| Profile | Size | Where |
|---|---|---|
| `tiny` | ~350 rows, every edge case once | committed; cast of characters in [docs/SCENARIO_TINY.md](docs/SCENARIO_TINY.md) |
| `small` | ~2,100 rows | committed, and published as a release archive |
| `portal` | ~75,000 rows, full reference vocabulary | gitignored; release archive only |

## Quick start

Requires Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), [just](https://just.systems/) and Docker.

```sh
just setup        # uv sync + start Postgres (Docker) and create the databases
just tiny         # build output/tiny (and docs/SCENARIO_TINY.md)
just check        # lint + tests + rebuild tiny; fails if output/tiny changed
```

Other commands:

```sh
just small | just portal            # build the scaled profiles
just verify-sql tiny                # reload each SQL dump into a scratch DB; byte-compare CSVs
just dist small                     # reproducible dist/cam-testdata-small-<model version>.tar.gz
uv run cam-testdata validate -p tiny          # integrity rules R1-R12 against a built DB
uv run cam-testdata missing-concepts -p tiny  # curies no input provides
uv run cam-testdata check-drift -p tiny       # what changed in the model since this build
```

### Postgres

`just pg-up` runs Postgres 18.6 (image pinned by digest: dump headers record the
version) in a container named `cam-testdata-pg`, with
trust auth on `127.0.0.1:5432` only, and creates `cam_testdata_{tiny,small,portal,test}`.
Tables and enum types live in schema `cam`. `just pg-down` stops it (data
persists in a volume); `just pg-destroy` removes it.

`pg_dump` and `psql` run inside the container (`just psql <db>`,
`just pg-dump <db>`), so they always match the server. Environment overrides:
`CAM_PG_URL` (database URL), `CAM_PG_DUMP` and `CAM_PSQL` (commands, e.g. in
CI where the client is installed on the runner).

## Using the artifacts

### Load the SQL dump

```sh
createdb mydb
psql -d mydb -v ON_ERROR_STOP=1 -f output/tiny/sql/cam_tiny.sql
```

The dump creates schema `cam` with all tables, enum types, keys and data. It's
a full dump on purpose: the model has an FK cycle (`Study.do_id` ↔
`DOI.study_id`), and a full dump adds constraints after the data. A data-only
dump can't be loaded into an existing schema with that cycle populated.

### Use the CSVs (e.g. as dbt seeds)

- File name = exact table name, mixed case included (`Study.csv`,
  `Demographics_race.csv`, `StudyMetadata_study_design.csv`).
- Header = the table's columns in DDL order; some are mixed case
  (`Study_study_id`). **Quote identifiers** wherever you refer to them.
- Rows are sorted by primary key. UTF-8, `\n` line endings, RFC 4180 quoting.
- An empty field means NULL. No text column ever holds an empty string (rule R12),
  so empty is never ambiguous.
- Every column is text-like or numeric; codes keep their leading zeros
  (`0000024`). If your loader infers types, declare the column types (for dbt:
  `column_types` with `quote_columns: true`).

## Identifiers

Four kinds, deliberately different:

| | Example | What it is |
|---|---|---|
| **handle** | `tiny/Subject/trio1-proband` | Stable readable key: `<profile>/<Class>/<key>`. Never in the data; drives everything below. |
| **CAM id** | `pt-0u4gl52nuc` | The record's ID. GlobalIDs are `<2-letter prefix>-<10 chars of [0-9a-z]>`, the prefix from the slot's type (`ptGlobalID` → `pt`, FHIR Patient). Minted as a hash of the profile seed and the handle, so adding records never changes existing IDs. Some are pinned (`sd-7hwpqzc2yr`). Non-global IDs: `fmb-`/`bsc-`/`alq-` + hash; DOIs `https://doi.org/10.5072/cam-testdata.<hash>`. |
| **external_id** | `https://example.org/cam-testdata/tiny/Subject/trio1-proband` | A URI; defaults to the handle under `example.org` unless the scenario gives real-looking ones. |
| **surrogate integer PK** | `Investigator.id = 717169176` | SQL-only keys for classes without a LinkML identifier (Investigator, Publication, HashDigest). Also minted from the handle; sequences are moved past them. |

`output/<profile>/id_map.csv` maps every handle to its table, ID and first external ID.

## Editing the tiny scenario

`scenarios/tiny.yaml` is the source of truth for tiny: plain data in LinkML
slot names, using fixture-local keys.

```yaml
records:
  Subject:
    - key: trio1-proband
      study_id: s1                 # entity slots take keys
      subject_type: CAMO:0000024   # Concept / enum / uriorcurie slots take curies
  Demographics:
    - key: trio1-proband           # one-to-one classes use the parent's key
      race: [CDCREC:2054-5, CDCREC:2106-3]   # multivalued -> list
```

- Omitted fields are filled by the factories (filler text, hashes, computed ages and counts).
- `study_id`/`access_policy_id` are inherited from the parent record; an explicit
  value that disagrees is an error. Top-level records (Subject, Family, File, …) need `study_id`.
- `id:` pins an ID (validated against the class's format and prefix).
- Errors name the record: `Encounter[e1].subject_id: required (no parent to inherit it from)`.

Then `just tiny`. The build fails if any integrity rule breaks, any coverage
feature (one per edge case, `validate/coverage.py`) disappears, or any YAML
fails LinkML validation. Keep tiny tiny: add records only for a new edge case,
and add a coverage feature for it.

The scaled profiles are generated from `config/profiles/{small,portal}.yaml`
(counts, family mix, probabilities). Every choice is seeded by the record's own
handle, so raising a count only adds records.

## Adding a missing concept

Concepts come only from `data/vocab_content.yaml`, `data/additional_vocab_content.yaml`,
or the schema's enum values. Nothing is bulk-downloaded.

1. `uv run cam-testdata missing-concepts -p tiny` writes
   `output/tiny/missing_concepts.csv` and `output/tiny/vocab_gaps_stub.yaml`.
2. Merge the stub into `data/vocab_gaps.yaml`: fill in `fhir_system` and a
   `source` (`OLS`, an OBO-JSON / OWL / Turtle file URL, or `manual`).
3. `uv run python scripts/follow_up_codes.py` looks the codes up and writes
   `data/additional_vocab_content.yaml`.
4. Rebuild.

## Releases

`small` and `portal` are published as GitHub release archives. To cut one,
create and push a tag named `data-v<model version>` (for example
`data-v0.2.1`). `.github/workflows/release.yml` then:

1. Checks that the committed outputs match the installed model (`check-drift`).
2. Rebuilds small, which must reproduce the committed `output/small` byte for byte.
3. Builds portal and runs `verify-sql` on both.
4. Creates a **draft** release with both archives, `SHA256SUMS`, and notes
   generated from the manifests.

Review the draft and publish it. To build the archives locally instead, run
`just dist small` / `just dist portal`.

## Validation

Every build checks, before exporting anything:

- **Integrity rules R1–R12** (`validate/integrity.py`): study scoping, required
  multivalued slots, one-to-one tables, specimen lineage, family coherence,
  linkage consistency, ages, participant counts, concept coverage, ID formats,
  natural keys, no empty strings.
- **LinkML + pydantic** validation of every YAML file.
- **Coverage features** (tiny must show all of them).

Tests run against a real Postgres database (`cam_testdata_test`), and include a
determinism test (two builds into two databases are byte-identical) and SQL ↔
CSV round trips.

## When the model changes

Bump the model in `pyproject.toml`, `uv sync`, `just update-cam`, repoint the
`data/common_access_model.yaml` symlink, then:

```sh
uv run cam-testdata check-drift -p tiny   # tables/columns/enums added or removed
```

Update the factories, the skip list, and `scenarios/tiny.yaml`; rebuild tiny
and small; review the data diff. Model problems found along the way are
tracked in [docs/MODEL_ISSUES.md](docs/MODEL_ISSUES.md).

## Layout

```
config/            settings, concept pools, scaled profiles
data/              model schema (symlink), vocabulary inputs, vocab gaps
scenarios/         tiny.yaml
scripts/           vocabulary tooling (follow_up_codes.py, collect_concepts.py)
src/cam_testdata/  factories, build, loader, scaled scenarios, exports, validation, CLI
docs/              DESIGN.md, MODEL_ISSUES.md, SCENARIO_TINY.md, PORTAL.md, notes/
output/            generated (never edit by hand)
```

The full specification is [docs/DESIGN.md](docs/DESIGN.md).
