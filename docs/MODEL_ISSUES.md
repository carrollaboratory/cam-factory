# Model issues — common_access_model

Problems found in the model while building test data. Not fixed here (AGENTS.md
rule 3); each lists its status and how this repo works around it. Status
reflects the user's notes of 2026-10-02 and the installed release
`0.2.1` (checked 2026-10-06).

**Status key:** ✅ fixed in the installed build · 🔜 fix in progress upstream
(PR or planned) · 🟰 by design / accepted · ❓ open

## Schema and prefixes

1. ✅ **CAMO and UCUM weren't declared prefixes.** Now declared
   (`CAMO` → `http://purl.obolibrary.org/obo/CAMO_`, `ucum` →
   `https://units-of-measurement.org/`). Vocabulary rows still come from
   `data/vocab_gaps.yaml` (FHIR system).
2. 🟰 **`DUO:00000044` has 8 digits.** DUO itself defines `DUO_00000044`
   (confirmed via OLS); some DUOS uses drop a zero. We use the OLS form.
3. ✅ **KIN code styles differed.** Every KIN code is now `KIN:NNN` with
   prefix `http://purl.org/ga4gh/kin.owl#KIN_`; all 48 resolve against kin.owl.
4. ✅ **`File` listed `format` twice.** Fixed in the model.
11. 🟰 **`EnumFamilyRole` mixes vocabularies** (SNOMED Proband and Mother, plus
    `KIN:027`) and has no Father or Sibling. It's a suggested example, not a
    binding (range is `Concept`), and the modeler asked that no permissible
    values be added. *Workaround:* `family_role` draws only from the enum's
    terms plus the family-member terms in `data/vocab_gaps.yaml` (concept pool).
12. 🟰 **`EnumProgram` values are full URIs.** `program` is `uriorcurie`;
    `EnumProgram` is a "preferred" list and any valid URI is allowed.
    *Workaround:* R9 checks curies only; full URIs are exempt.
13. 🟰 **`*GlobalID` types declare no `pattern`.** *Workaround:* regex in
    `config/settings.yaml`. The user may raise it upstream.
14. 🟰 **Age units differ**: `age_at_collection` is float years (`ucum:a`), the
    other `age_*` slots are integer days (`ucum:d`). *Workaround:* R7 reads
    units per slot and converts.
15. ✅ **`edam` prefix lacked a trailing slash.** Now `http://edamontology.org/`.
16. 🟰 **No schema version in the YAML**; the package version comes from SCM
    tags. *Workaround:* `importlib.metadata.version`.
17. 🟰 **Placeholder descriptions** for `fmGlobalID`, `msGlobalID`, `pdGlobalID`:
    these prefixes haven't been requested from the minting service yet.
18. 🟰 **No `tree_root` / container class.** A file holding a list of instances
    can't be validated without saying which class they are. *Workaround:*
    `linkml-validate --target-class <Class>` per exported file.

## SQL / DDL

5. 🟰 **Circular FK `Study.do_id` ↔ `DOI.study_id`.** The DOI's study is the
    intended meaning. *Workaround:* insert Study, then DOI, then set `do_id`.
6. 🟰 **`Any`, `Record`, `Record_external_id` emitted as tables.**
    *Workaround:* excluded from DDL (Q4).
8. ✅ **`Synonym.concept_curie` / `ConceptRelationship.concept_curie` had no FK
   to `Concept`.** Both now have one. (The user is also proposing range
   `Concept` for the LinkML slot.)
10. 🟰 **`Sample.sample_type`, `processing`, `storage_method` are open-ended
    uriorcurie** (Concepts, URIs or plain curies), on purpose. *Workaround:*
    pick one or two codes each, add them through `vocab_gaps.yaml`, and R9
    checks them. Candidates are in `docs/notes/model_inventory.md`.
19. ❓ **No unique constraints or indexes** besides PKs. *Workaround:* this repo
    enforces natural keys itself (R11). The user will raise it with the modeler.
20. 🔜 **Nullable linking FKs.** Now NOT NULL: `Encounter.subject_id`,
    `SubjectAssertion.subject_id`, `Aliquot.sample_id`. Still nullable, some on
    purpose: `Sample.biospecimen_collection_id`,
    `BiospecimenCollection.encounter_id` stay nullable by design.
    *Workaround:* R4. We always set them, so we never generate orphans.
21. ✅ **Record-mixin `study_id` / `access_policy_id` were nullable.** Required
    (NOT NULL) since v0.2.1. R1 still checks them.
23. ❓ **`File.size` is a 32-bit `INTEGER`** in the DDL, so sizes over
    2,147,483,647 bytes (~2.1 GB) can't be stored, and real CRAM/BAM files are
    often tens of GB. Needs a 64-bit range (BIGINT). *Workaround:* generated sizes
    stay under 2**31.

## Semantics

24. ❓ **`Investigator` uses the `Record` mixin** (its own `study_id` /
    `access_policy_id`), but one investigator is expected to serve several
    studies (PI or contact of more than one). The user has raised it with the
    modeler; the mixin is likely an error. *Workaround:* R1 lets Study and
    VirtualBiorepository link to an investigator from another study; the
    investigator row still carries its home study's scoping.
25. ❓ **`Person` uses the `Record` mixin** (v0.2.2), so it needs a `study_id`,
    but a Person ties together Subjects in several studies (possibly across
    programs). The study is really a program-level umbrella; the ID minting
    service being study-oriented is the likely reason. *Workaround:* one
    umbrella "Farm" Study (own open access policy, required metadata, no
    subjects, no study points to it) owns every Person; R1 lets
    `Person_subject_id` cross studies; R11 keeps a Subject in at most one Person.

7. ✅ **`Sample` had no direct subject link.** New required `Sample.subject_id`.
   That makes the subject reachable two ways (directly, and via the
   collection's encounter), so R6 checks they agree.
9. ✅ **`Dataset` didn't use the `Record` mixin.** It now has `study_id`,
   `access_policy_id` and `Dataset_external_id`.
22. ❓ **No Condition class.** Diagnoses and observations are both `ob`
    SubjectAssertions, so there's no way to say "this subject has condition X"
    as distinct from "X was observed present" (or to tie a test result to a
    diagnosis). The user expects collaborators to raise it. *Workaround:* none
    needed; tiny models everything as Observations.
