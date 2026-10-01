#!/usr/bin/env python3
"""Download the CAMO ontology (JSON/OBO Graphs format) and look up CURIEs.

Usage:
    python camo_lookup.py CAMO:0000024 CAMO:0000004
    python camo_lookup.py            # runs the built-in example

Or import:
    from camo_lookup import lookup_curies
    results = lookup_curies(["CAMO:0000024", "MS:1000568"])
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from collect_concepts import model_to_dict
from common_access_model.datamodel.common_access_model_sqla import Concept
from ruamel.yaml import YAML

CAMO_URL = "https://github.com/include-dcc/camo/releases/download/v2026-09-09/camo.json"
DATA_DIR = Path("data/onto")
DESCRIPTION_PRED = "http://purl.org/dc/terms/description"
OBO_PREFIX = "http://purl.obolibrary.org/obo/"

yaml = YAML()


def download_ontology(url: str = CAMO_URL, dest_dir: Path = DATA_DIR) -> Path:
    """Download the ontology file if it is not already present."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(url).name
    if dest.exists():
        print(f"Using existing file: {dest}", file=sys.stderr)
        return dest

    print(f"Downloading {url} -> {dest}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "camo-lookup/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    tmp.rename(dest)  # only appears under final name once fully downloaded
    return dest


def curie_to_iri(curie: str) -> str:
    """CAMO:0000024 -> http://purl.obolibrary.org/obo/CAMO_0000024"""
    prefix, _, local = curie.strip().partition(":")
    if not prefix or not local:
        raise ValueError(f"Invalid CURIE: {curie!r}")
    return f"{OBO_PREFIX}{prefix}_{local}"


def get_description(node: dict):
    """Return the dc:description value of a node, or None."""
    for bpv in node.get("meta", {}).get("basicPropertyValues", []):
        if bpv.get("pred") == DESCRIPTION_PRED:
            return bpv.get("val")
    return None


def lookup_curies(curies, path: Path | None = None) -> dict:
    """Return {curie: {"id", "lbl", "description"} or None if not found}."""
    path = path or download_ontology()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Index all nodes by IRI across all graphs
    nodes = {n["id"]: n for g in data.get("graphs", []) for n in g.get("nodes", [])}

    results = {}
    for curie in curies:
        node = nodes.get(curie_to_iri(curie))
        results[curie] = (
            None
            if node is None
            else {
                "id": node["id"],
                "lbl": node.get("lbl"),
                "description": get_description(node),
            }
        )
    return results


def load_vocab_gaps_input(gap_input: Path) -> dict:
    with gap_input.open("rt") as f:
        gap_config = yaml.load(f)
    return gap_config


def return_camo_concepts(vocabulary_uri: str, curies: str) -> dict[str, Concept]:
    concepts = {}
    for curie, info in lookup_curies(curies).items():
        print(f"\n{curie}")
        if info is None:
            print("  (not found)")
            continue

        display = info.get("description", info.get("lbl", ""))
        code = info.get("id").replace(vocabulary_uri, "")
        concepts[curie] = model_to_dict(
            Concept(
                concept_curie=curie,
                vocabulary_prefix="CAMO",
                concept_code=code,
                display=display,
            )
        )

    return concepts


def main():
    parser = argparse.ArgumentParser(
        description="fill in terminology gaps as the are needed during data simulation"
    )
    parser.add_argument(
        "--gaps",
        default="data/vocab_gaps.yaml",
        help="YAML file containing additional terms that belong in the database",
    )
    parser.add_argument(
        "--output",
        default="data/additional_vocab_content.yaml",
        help="YAML file containing those additional Vocabulary and Concept terms",
    )
    args = parser.parse_args()

    gap_config = load_vocab_gaps_input(Path(args.gaps))

    # For now, we only have CAMO:
    camo_ontology = gap_config["CAMO"]
    gap_config["CAMO"]["codes"] = return_camo_concepts(
        camo_ontology["vocabulary_uri"], camo_ontology["codes"]
    )

    print(f"Writing {', '.join(gap_config.keys())} to file, {args.output}")
    with Path(args.output).open("wt") as f:
        yaml.dump(gap_config, f)


if __name__ == "__main__":
    main()
