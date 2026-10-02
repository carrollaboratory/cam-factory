#!/usr/bin/env python3
"""Fill terminology gaps: look up specific codes and write Vocabulary/Concept content.

Reads data/vocab_gaps.yaml, where each top-level entry is a vocabulary (the
Vocabulary columns), plus a `source` saying where to look the codes up and a
list of `codes` (curies). Writes data/additional_vocab_content.yaml in the same
shape as data/vocab_content.yaml (codes become a list of Concept rows; `source`
is dropped).

Sources:

    source: OLS                          # shorthand for {type: ols}
    source: {type: ols, ontology: duo}   # OLS4 API; ontology defaults to the prefix, lowercased
    source: https://.../camo.json        # type inferred from the extension
    source: {url: https://.../kin.owl}   # remote file, cached in --cache-dir
    source: {path: data/onto/kin.owl}    # local file
    source: {type: owl, url: https://.../download?id=1}   # explicit type when there's no useful extension
    source: {url: https://.../x.owl, format: functional}  # force an OWL syntax instead of sniffing it
    source: manual                       # nothing to look up (e.g. UCUM); give display/definition per code:
    codes:
    - {curie: ucum:ng/uL, display: nanogram per microliter}

GitHub files must use the raw URL (raw.githubusercontent.com/...); a
github.com/.../blob/... link returns the HTML page, not the file.

File types: .json (OBO Graphs JSON); .owl / .ofn / .rdf / .xml / .ttl / .nt.
A .owl file's syntax is sniffed from its content: OWL functional syntax
(e.g. KIN) is read by a small built-in parser that only extracts annotations;
RDF/XML and Turtle go through rdflib. OWL/XML and Manchester syntax aren't
supported.

A code's IRI is the vocabulary's `vocabulary_uri` + the curie's local part,
e.g. KIN:KIN_027 -> http://purl.org/ga4gh/kin.owl#KIN_027.

Usage:
    uv run python scripts/follow_up_codes.py
    uv run python scripts/follow_up_codes.py --only KIN --only DUO
"""

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from common_access_model.datamodel.common_access_model_sqla import Concept
from ruamel.yaml import YAML
from sqlalchemy import inspect

OLS_API = "https://www.ebi.ac.uk/ols4/api"
USER_AGENT = "cam-testdata-follow-up-codes/1.0"

# Extension -> syntax; None means sniff the file's content.
RDF_FORMATS = {".owl": None, ".ofn": "functional", ".rdf": "xml", ".xml": "xml", ".ttl": "turtle", ".nt": "nt"}

# Predicates tried in order for a term's definition.
DEFINITION_PREDICATES = [
    "http://purl.obolibrary.org/obo/IAO_0000115",
    "http://www.w3.org/2004/02/skos/core#definition",
    "http://purl.org/dc/terms/description",
    "http://purl.org/dc/elements/1.1/description",
]
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
OWL_DEPRECATED = "http://www.w3.org/2002/07/owl#deprecated"

CONCEPT_COLUMNS = [c.key for c in inspect(Concept).mapper.column_attrs]

yaml = YAML()
yaml.width = 4096  # keep long definitions on one line


@dataclass
class Term:
    label: str | None
    definition: str | None
    obsolete: bool = False


@dataclass
class SourceSpec:
    type: str  # "ols" | "manual" | "json" | "rdf"
    location: str | None = None  # url or path for file sources
    ontology: str | None = None  # OLS ontology id
    rdf_format: str | None = None


class GapError(Exception):
    pass


def parse_source(prefix: str, raw: Any) -> SourceSpec:
    """Normalize the `source` value of one vocab_gaps entry."""
    if raw is None:
        raise GapError(f"{prefix}: no `source` given")
    if isinstance(raw, str):
        raw = {"type": raw.lower()} if raw.lower() in ("ols", "manual") else {"url": raw}
    if not isinstance(raw, dict):
        raise GapError(f"{prefix}: `source` must be a string or a mapping, got {raw!r}")

    location = raw.get("url") or raw.get("path")
    kind = (raw.get("type") or "").lower()
    if kind == "ols":
        return SourceSpec("ols", ontology=raw.get("ontology") or prefix.lower())
    if kind == "manual":
        return SourceSpec("manual")
    if "github.com/" in (location or "") and "/blob/" in (location or ""):
        raise GapError(f"{prefix}: {location} is a GitHub page, not the file; use the raw.githubusercontent.com URL")
    if not location:
        raise GapError(f"{prefix}: file source needs `url` or `path`")

    suffix = Path(urllib.parse.urlparse(location).path).suffix.lower()
    if kind == "json" or (not kind and suffix == ".json"):
        return SourceSpec("json", location=location)
    if kind in ("owl", "rdf") or (not kind and suffix in RDF_FORMATS):
        return SourceSpec("rdf", location=location, rdf_format=raw.get("format") or RDF_FORMATS.get(suffix))
    raise GapError(f"{prefix}: can't tell the source type of {location!r}; add `type: json | owl | ols`")


def fetch_file(location: str, cache_dir: Path, refresh: bool) -> Path:
    """Return a local path for a url (downloading into the cache) or a path."""
    if not location.startswith(("http://", "https://")):
        path = Path(location)
        if not path.exists():
            raise GapError(f"source file not found: {path}")
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / (Path(urllib.parse.urlparse(location).path).name or "download")
    if dest.exists() and not refresh:
        print(f"  using cached {dest}", file=sys.stderr)
        return dest

    print(f"  downloading {location} -> {dest}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", location, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    tmp.rename(dest)  # only appears under its final name once complete
    return dest


def lookup_json(path: Path, iris: list[str]) -> dict[str, Term]:
    """OBO Graphs JSON (e.g. camo.json)."""
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    nodes = {n["id"]: n for g in data.get("graphs", []) for n in g.get("nodes", [])}

    found = {}
    for iri in iris:
        node = nodes.get(iri)
        if node is None:
            continue
        meta = node.get("meta", {})
        props = {p.get("pred"): p.get("val") for p in meta.get("basicPropertyValues", [])}
        definition = (meta.get("definition") or {}).get("val")
        if definition is None:
            definition = next((props[p] for p in DEFINITION_PREDICATES if p in props), None)
        found[iri] = Term(
            label=node.get("lbl"),
            definition=definition,
            obsolete=bool(meta.get("deprecated")),
        )
    return found


def sniff_rdf_format(path: Path) -> str:
    """Guess an ontology file's syntax from its first meaningful text."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        head = fh.read(4096)
    text = "\n".join(line for line in head.splitlines() if not line.lstrip().startswith("#")).lstrip()
    if text.startswith(("Prefix(", "Ontology(")):
        return "functional"
    if text.startswith("@prefix") or text.startswith("@base") or text.lower().startswith("prefix "):
        return "turtle"
    if text.startswith("<"):
        if "<Ontology" in head and 'xmlns="http://www.w3.org/2002/07/owl#"' in head:
            return "owlxml"
        return "xml"
    raise GapError(f"can't tell the syntax of {path}; set `source.format`")


# Annotations collected from a file: iri -> predicate iri -> [(value, language)]
Annotations = dict[str, dict[str, list[tuple[str, str | None]]]]


def terms_from_annotations(annotations: Annotations, iris: list[str]) -> dict[str, Term]:
    def first(values: list[tuple[str, str | None]]) -> str | None:
        # Prefer English or untagged literals, then sort for a stable choice.
        ranked = sorted(values, key=lambda v: (v[1] not in (None, "en"), v[0]))
        return ranked[0][0] if ranked else None

    found = {}
    for iri in iris:
        props = annotations.get(iri)
        if props is None:
            continue
        definition = None
        for predicate in DEFINITION_PREDICATES:
            definition = first(props.get(predicate, []))
            if definition:
                break
        found[iri] = Term(
            label=first(props.get(RDFS_LABEL, [])),
            definition=definition,
            obsolete=first(props.get(OWL_DEPRECATED, [])) == "true",
        )
    return found


def lookup_rdf(path: Path, rdf_format: str, iris: list[str]) -> dict[str, Term]:
    """RDF/XML, Turtle, N-Triples via rdflib."""
    from rdflib import Graph, Literal, URIRef

    print(f"  parsing {path} ({rdf_format})", file=sys.stderr)
    graph = Graph()
    graph.parse(path, format=rdf_format)

    annotations: Annotations = {}
    for iri in iris:
        subject = URIRef(iri)
        if (subject, None, None) not in graph:
            continue
        props = annotations.setdefault(iri, {})
        for predicate, obj in graph.predicate_objects(subject):
            if isinstance(obj, Literal):
                props.setdefault(str(predicate), []).append((str(obj), obj.language))
    return terms_from_annotations(annotations, iris)


FUNCTIONAL_TOKEN = re.compile(
    r"""\s+|\#[^\n]*                     # whitespace, comments
    |(?P<open>\()|(?P<close>\))
    |(?P<iri><[^>]*>)
    |(?P<literal>"(?:[^"\\]|\\.)*")(?:@(?P<lang>[A-Za-z0-9-]+)|\^\^(?P<dtype><[^>]*>|[^\s()]+))?
    |(?P<word>[^\s()"<>]+)""",
    re.VERBOSE,
)


def parse_functional(text: str) -> list:
    """Parse OWL functional syntax into nested lists of tokens.

    Tokens are ("iri", value), ("lit", value, lang), or ("word", value);
    expressions are [name, *args].
    """
    stack: list[list] = [[]]
    for m in FUNCTIONAL_TOKEN.finditer(text):
        if m.group("open"):
            current = stack[-1]
            name = current.pop() if current and current[-1][0] == "word" else ("word", "")
            stack.append([name[1]])
        elif m.group("close"):
            done = stack.pop()
            stack[-1].append(done)
        elif m.group("iri"):
            stack[-1].append(("iri", m.group("iri")[1:-1]))
        elif m.group("literal"):
            raw = m.group("literal")[1:-1]
            value = re.sub(r'\\(["\\])', r"\1", raw)
            stack[-1].append(("lit", value, m.group("lang")))
        elif m.group("word"):
            stack[-1].append(("word", m.group("word")))
    if len(stack) != 1:
        raise GapError("unbalanced parentheses in OWL functional syntax")
    return stack[0]


def lookup_functional(path: Path, iris: list[str]) -> dict[str, Term]:
    """OWL functional syntax: only Prefix declarations and AnnotationAssertions are read."""
    print(f"  parsing {path} (OWL functional syntax)", file=sys.stderr)
    tree = parse_functional(path.read_text(encoding="utf-8"))

    prefixes: dict[str, str] = {}
    assertions: list[list] = []
    for expr in tree:
        if not isinstance(expr, list):
            continue
        if expr[0] == "Prefix":
            # Prefix(rdfs:=<...>) tokenizes as the word "rdfs:=" followed by the iri
            words = [t for t in expr[1:] if isinstance(t, tuple)]
            name = next((t[1] for t in words if t[0] == "word"), "")
            iri = next((t[1] for t in words if t[0] == "iri"), None)
            if iri is not None:
                prefixes[name.rstrip("=").rstrip(":")] = iri
        elif expr[0] == "Ontology":
            assertions.extend(e for e in expr[1:] if isinstance(e, list) and e[0] == "AnnotationAssertion")

    def expand(token: tuple) -> str | None:
        if token[0] == "iri":
            return token[1]
        if token[0] == "word" and ":" in token[1]:
            prefix, _, local = token[1].partition(":")
            if prefix in prefixes:
                return prefixes[prefix] + local
        return None

    annotations: Annotations = {}
    for expr in assertions:
        # AnnotationAssertion(Annotation(...)* property subject value)
        args = [a for a in expr[1:] if not isinstance(a, list)]
        if len(args) != 3:
            continue
        predicate, subject, value = expand(args[0]), expand(args[1]), args[2]
        if predicate is None or subject is None or value[0] != "lit":
            continue
        annotations.setdefault(subject, {}).setdefault(predicate, []).append((value[1], value[2]))
    return terms_from_annotations(annotations, iris)


def lookup_ols(ontology: str, iris: list[str]) -> dict[str, Term]:
    """OLS4 term lookup, one request per IRI."""
    found = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        resp = client.get(f"{OLS_API}/ontologies/{ontology}")
        if resp.status_code == 404:
            raise GapError(f"OLS has no ontology {ontology!r}; set `source.ontology` or use a file source")
        resp.raise_for_status()

        for iri in iris:
            encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
            resp = client.get(f"{OLS_API}/ontologies/{ontology}/terms/{encoded}")
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            term = resp.json()
            descriptions = term.get("description") or []
            found[iri] = Term(
                label=term.get("label"),
                definition=descriptions[0] if descriptions else None,
                obsolete=bool(term.get("is_obsolete")),
            )
    return found


def resolve_entry(prefix: str, entry: dict, cache_dir: Path, refresh: bool) -> tuple[dict, list[str]]:
    """Return (vocabulary dict with Concept rows, list of problems)."""
    spec = parse_source(prefix, entry.get("source"))
    vocabulary_prefix = entry.get("vocabulary_prefix") or prefix
    vocabulary_uri = entry.get("vocabulary_uri")
    if not vocabulary_uri:
        raise GapError(f"{prefix}: `vocabulary_uri` is needed to build term IRIs")

    # A code is a curie string, or (for manual sources) {curie, display, definition}.
    manual_terms: dict[str, Term] = {}
    curies = []
    for code in entry.get("codes") or []:
        if isinstance(code, dict):
            curie = str(code.get("curie") or code.get("concept_curie") or "")
            manual_terms[curie] = Term(label=code.get("display"), definition=code.get("definition"))
        else:
            curie = str(code)
        curies.append(curie)
    iri_by_curie = {}
    problems = []
    for curie in curies:
        curie_prefix, sep, local = curie.partition(":")
        if not sep or not local:
            problems.append(f"{curie}: not a curie")
        elif curie_prefix != vocabulary_prefix:
            problems.append(f"{curie}: prefix doesn't match vocabulary_prefix {vocabulary_prefix!r}")
        else:
            iri_by_curie[curie] = vocabulary_uri + local

    iris = list(iri_by_curie.values())
    if spec.type == "manual":
        print(f"{prefix}: manual, {len(iris)} codes", file=sys.stderr)
        terms = {iri_by_curie[c]: t for c, t in manual_terms.items() if c in iri_by_curie}
    elif spec.type == "ols":
        print(f"{prefix}: OLS ontology {spec.ontology!r}, {len(iris)} codes", file=sys.stderr)
        terms = lookup_ols(spec.ontology or prefix.lower(), iris)
    else:
        print(f"{prefix}: {spec.location}, {len(iris)} codes", file=sys.stderr)
        path = fetch_file(spec.location or "", cache_dir, refresh)
        if spec.type == "json":
            terms = lookup_json(path, iris)
        else:
            rdf_format = spec.rdf_format or sniff_rdf_format(path)
            if rdf_format == "functional":
                terms = lookup_functional(path, iris)
            elif rdf_format == "owlxml":
                raise GapError(f"{path} is OWL/XML, which isn't supported; convert it to RDF/XML or functional syntax")
            else:
                terms = lookup_rdf(path, rdf_format, iris)

    codes = []
    for curie, iri in iri_by_curie.items():
        term = terms.get(iri)
        if term is None:
            problems.append(f"{curie}: not found ({iri})")
            continue
        if term.obsolete:
            problems.append(f"{curie}: obsolete in the source (kept)")
        if not term.label:
            problems.append(f"{curie}: no label in the source (kept, display empty)")
        concept = dict.fromkeys(CONCEPT_COLUMNS)
        concept.update(
            concept_curie=curie,
            vocabulary_prefix=vocabulary_prefix,
            concept_code=curie.partition(":")[2],
            display=term.label,
            definition=term.definition,
        )
        codes.append(concept)

    vocabulary = {k: v for k, v in entry.items() if k not in ("source", "codes")}
    vocabulary["codes"] = codes
    return vocabulary, problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill terminology gaps needed during data simulation")
    parser.add_argument("--gaps", default="data/vocab_gaps.yaml", help="vocabularies, sources, and codes to look up")
    parser.add_argument("--output", default="data/additional_vocab_content.yaml", help="where to write the results")
    parser.add_argument("--cache-dir", default="data/onto", help="where downloaded ontology files are kept")
    parser.add_argument("--refresh", action="store_true", help="re-download cached ontology files")
    parser.add_argument("--only", action="append", metavar="PREFIX", help="only these vocabularies (repeatable)")
    args = parser.parse_args()

    with Path(args.gaps).open("rt") as fh:
        gap_config = yaml.load(fh) or {}

    output_path = Path(args.output)
    output: dict = {}
    if args.only and output_path.exists():
        # Partial run: keep the other vocabularies from the previous output.
        with output_path.open("rt") as fh:
            output = dict(yaml.load(fh) or {})

    all_problems: dict[str, list[str]] = {}
    for prefix, entry in gap_config.items():
        if args.only and prefix not in args.only:
            continue
        try:
            output[prefix], problems = resolve_entry(prefix, entry, Path(args.cache_dir), args.refresh)
        except (GapError, httpx.HTTPError) as exc:
            all_problems[prefix] = [f"skipped: {exc}"]
            continue
        if problems:
            all_problems[prefix] = problems

    with output_path.open("wt") as fh:
        yaml.dump(output, fh)
    print(f"Wrote {', '.join(output) or 'nothing'} to {output_path}", file=sys.stderr)

    for prefix, problems in all_problems.items():
        print(f"\n{prefix}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    return 1 if any("not found" in p or p.startswith("skipped") for ps in all_problems.values() for p in ps) else 0


if __name__ == "__main__":
    sys.exit(main())
