import sys
from collections import defaultdict
from csv import DictReader
from pathlib import Path

from common_access_model.datamodel.common_access_model_sqla import Concept, Vocabulary
from rich import print
from ruamel.yaml import YAML
from sqlalchemy import inspect

VOCABULARY_META = "data/vocabulary_meta.yaml"
VOCABULARY_CONTENT = Path("data/vocab_content.yaml")

SYSTEM_ALTERNATIVES = {
    "http://loinc.org": "https://loinc.org/",
    "SNOMED": "http://snomed.info/sct",
    "SMOMED": "http://snomed.info/sct",
}

yaml = YAML()

with Path(VOCABULARY_META).open("rt") as vf:
    vocabulary_meta = yaml.load(vf)


# print(list(vocabulary_meta.keys()))

harmony_files = Path("data/harmony").glob("*.csv")

vocabularies = {}  # units => Vocabulary
vocabularies_by_prefix = {}
concepts = defaultdict(dict)  # vocab_prefix -> {curie => Concept}
concepts_by_prefix = defaultdict()


class InvalidVocabularyKeyError(Exception):
    """Exception raised when a required vocabulary key is invalid or missing."""

    def __init__(
        self,
        key: str,
        message: str = "The required key is invalid or missing from the YAML metadata.",
    ):
        self.key = key
        self.message = f"{message}: 👉 Please add the correct metadata to the file, {VOCABULARY_META}: '{self.key}'"
        super().__init__(self.message)


def model_to_dict(obj: Concept | Vocabulary):
    if type(obj) not in [Vocabulary, Concept]:
        print(obj)
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}


def get_curie(code: str, system: str):
    return code


def get_concept_by_code(code: str, display: str, system: str) -> Concept:
    vocab = get_vocabulary_by_system(system)
    curie = f"{vocab.vocabulary_prefix}:{code}"

    if curie not in concepts[vocab.vocabulary_prefix]:
        concept = Concept(
            concept_curie=curie,
            vocabulary_prefix=vocab.vocabulary_prefix,
            concept_code=code,
            display=display,
        )
        concepts[vocab.vocabulary_prefix][curie] = concept
    return concepts[vocab.vocabulary_prefix][curie]


def get_vocabulary_by_system(system_key: str) -> Vocabulary:
    system = SYSTEM_ALTERNATIVES.get(system_key, system_key)

    if system not in vocabularies:
        if system in vocabulary_meta:
            try:
                meta = vocabulary_meta[system]
            except:
                print(vocabulary_meta)
                sys.exit(1)
            vocabularies[system] = Vocabulary(**meta)
            vocabularies_by_prefix[meta["vocabulary_prefix"]] = vocabularies[system]
        else:
            if system == "ml":
                print(SYSTEM_ALTERNATIVES)
                print(system)
                print(system_key)

            raise InvalidVocabularyKeyError(system, "Unrecognized system")
    return vocabularies[system]


bad_systems = set()
for harmony_file in harmony_files:
    with harmony_file.open("rt") as f:
        reader = DictReader(f, quotechar='"', delimiter=",")
        for line in reader:
            system = line["code system"]
            try:
                # print(line)
                concept = get_concept_by_code(
                    code=line["code"],
                    display=line["display"],
                    system=system,
                )
            except InvalidVocabularyKeyError as e:
                if system not in bad_systems:
                    if system == "ml":
                        print(harmony_file)
                        print(line)
                    print(e)
                    bad_systems.add(system)

vocabulary = {}
# Write the final vocabulary data to YAML
for prefix, codes in concepts.items():
    try:
        vocab = model_to_dict(vocabularies_by_prefix[prefix])
    except KeyError:
        print(
            f"{prefix} is not present the known vocabularies set: {', '.join(vocabularies.keys())}"
        )

        continue
    vocab["codes"] = []

    for code, cnc in codes.items():
        vocab["codes"].append(model_to_dict(cnc))

    vocabulary[vocab["vocabulary_prefix"]] = vocab

with VOCABULARY_CONTENT.open("wt") as outf:
    yaml.dump(vocabulary, outf)
