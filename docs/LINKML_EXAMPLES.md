# Copying the tiny examples into the LinkML model repo

`just tiny` writes `output/tiny/examples/<Class>-001.yaml`: one instance per
class, in the layout the LinkML project cookiecutter uses for example data. Every
file passes `linkml-validate` (JSON Schema, closed) and the model's pydantic
classes as part of the build.

## Steps

1. Rebuild tiny against the model version you're targeting, and confirm nothing drifted:

   ```sh
   just tiny
   uv run cam-testdata check-drift -p tiny
   ```

2. In the common-access-model repo, copy the files into the valid-examples
   directory (in cookiecutter projects that's `tests/data/valid/`; use whatever
   the repo's `examples/valid/`-style folder is):

   ```sh
   cp ../cam-factory/output/tiny/examples/*.yaml tests/data/valid/
   ```

   File names follow LinkML's convention, `<ClassName>-<name>.yaml`, so the test
   runner infers the target class from the name.

3. Run the model repo's example tests (e.g. `just test` / `make test-examples`),
   or validate directly:

   ```sh
   linkml-validate -s src/common_access_model/schema/common_access_model.yaml \
       -C Subject tests/data/valid/Subject-001.yaml
   ```

## Notes

- Examples refer to other records by ID (a Sample's `subject_id`, a Study's
  `access_policy_id`). Those records may not be the `-001` instance of their
  class. Single-file validation checks shape and enum values, not cross-file
  references.
- Classes without a LinkML identifier (Investigator, Publication, HashDigest)
  appear inlined where they're used, e.g. Study's `principal_investigator` and
  File's `hash`. They also get their own example file.
- For a fuller set, `output/tiny/yaml/<Class>.yaml` holds every tiny instance of
  each class as a list. Validate those with `-C <Class>`, since the schema has no
  container class (MODEL_ISSUES #18).
- Don't edit the copied files to fix a validation problem. Fix the scenario or
  the model and regenerate.
