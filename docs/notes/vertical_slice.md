# Vertical slice findings (TODO 1.6)

Run 2026-10-02 against Postgres 18.6 (Docker) and model build
`0.2.0.post4.dev0+5253ae3`. Throwaway code (not committed). The prototype
CSV exporter is ~20 lines and worth reusing for 5.2.

Rows: `Vocabulary` (DUO) → `Concept` `DUO:0000042` → `AccessPolicy` → `Study`
(pinned `sd-7hwpqzc2yr`) → `Investigator` (explicit int id) → `Study_program`,
`Study_principal_investigator`; then a second run adding a `DOI` to close the
Study ↔ DOI cycle. Values deliberately included an apostrophe, double quotes,
commas, an embedded newline, non-ASCII text, a leading-zero code, and an empty
string next to NULLs.

Pipeline: build → CSV → `pg_dump` (via `docker exec`) → load into a scratch DB
→ CSV again → byte-compare.

## What held up

- **Schema placement**: all tables and the enum types land in `cam`, none in
  `public`, before and after a reload.
- **`create_all` with the Study ↔ DOI cycle** works (SQLAlchemy adds those FKs
  separately).
- **CSV**: Python `csv` with `lineterminator="\n"` gives RFC 4180 output.
  Quotes are doubled, the embedded newline is quoted, UTF-8 survives, and
  `0000042` keeps its leading zeros (all columns are text).
- **Full dump round trip**: the full dump, in both COPY and `--column-inserts`
  form, reloads into an empty database and re-exports byte-identical CSVs,
  **including with the Study ↔ DOI cycle populated**. The Investigator
  sequence continues from max(id)+1 after `fix_sequences`.
- **Dump stability**: the only volatile lines are `\restrict <random>` /
  `\unrestrict <random>`. With a fixed `--restrict-key` (pg_dump 18 supports
  it), two dumps of one DB, and dumps of two separate builds, are
  byte-identical. The `Dumped from/by version 18.6` lines only change when the
  image changes, which is a real change worth seeing in a diff, so keep them.
- `docker exec … pg_dump` works for export; `docker exec -i … psql` reads a
  dump from stdin for import.

## Problems found

1. **The ORM won't order inserts across plain FKs.** The generated model has
   FKs without `relationship()`s for many links (e.g. `Concept.vocabulary_prefix`
   → `Vocabulary`). SQLAlchemy's unit of work only orders by relationships, so
   one flush of mixed objects failed with an FK violation. *Consequence:* the
   scenario loader must insert table by table in FK order (sorted from
   metadata, with the Study ↔ DOI cycle handled explicitly) and flush after
   each step. DESIGN §8.2 already gives the loader this job; factories must not
   rely on `SubFactory` or relationships for ordering.
2. **CSV can't tell `''` from NULL.** Both are written as an empty field, so an
   empty string in the DB becomes NULL for anyone loading the CSV (dbt seeds
   included), while the SQL dump keeps `''`. *Proposal:* never generate empty
   strings. Factories and the loader normalize `''` to NULL, and an integrity
   rule (R12) fails the build if any text column holds `''`.
3. **The data-only dump can't be loaded once the cycle has data.** `pg_dump
   --data-only` warns about circular FKs (Study ↔ DOI, plus the self-referencing
   tables), and loading it into a schema that already has its FKs fails on
   `DOI_study_id_fkey`. The usual fixes don't fit: `--disable-triggers` needs
   superuser on the loading side, and the model's FKs aren't `DEFERRABLE`.
   *Proposal:* replace `sql/cam_<profile>_data.sql` (data-only, inserts) with
   `sql/cam_<profile>_inserts.sql`: a **full** dump with `--column-inserts`.
   It still serves loaders that can't handle `COPY`, creates the schema itself,
   adds constraints after the data, and reloads correctly with the cycle
   (verified).

## Settings to add

- `database.restrict_key: camtestdata`: passed as `--restrict-key` so dumps
  are byte-stable.

## Not covered

- dbt seed loading (deferred, Q10).
- Dump size: an almost-empty database dumps to ~7,200 lines, mostly enum type
  definitions (`EnumAssayType` alone has 1,803 values). That's stable, so it
  isn't a diff problem.
