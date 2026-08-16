#!/usr/bin/env python3
"""
===============================================================================
Ontology TBox Loader (W3C Turtle -> Neo4j)
===============================================================================
Loads the platform's terminological layer -- `ontology/financial_platform_ontology.ttl`
-- into Neo4j as a queryable graph: classes, their subclass hierarchy, object and
datatype properties with domain/range, and the FIBO/BIAN URIs each local class is
grounded in.

Why this exists: that TTL is a genuine TBox (verified by parse -- 10 `owl:Class`,
5 `owl:ObjectProperty`, 5 `owl:DatatypeProperty`, 3 `rdfs:subClassOf`, 10
`rdfs:domain`, 10 `rdfs:range`, 9 `rdfs:isDefinedBy`, and *zero* individuals),
but until now it was the one artifact in the platform with nowhere queryable to
live -- read only to be re-exported as a file. Meanwhile the same database
already holds the ABox (instance data) and the lineage sub-graph. This makes the
ontology a first-class layer alongside them.

TBox and ABox share one database by necessity, not by choice: Neo4j Community
permits exactly one user database (verified live -- `CREATE DATABASE` returns
`Neo.ClientError.Statement.UnsupportedAdministrationCommand`). They are kept
apart by label convention instead:

    TBox  :OntologyClass  :OntologyProperty  :ExternalConcept
    ABox  :Party :Customer :DepositAccount ...  (see build_knowledge_graph.ABOX_LABELS)

`build_knowledge_graph.py`'s reload is scoped to `ABOX_LABELS` precisely so it
cannot delete what this script writes. Before that fix it ran an unconditional
`MATCH (n) DETACH DELETE n`, which would have erased this layer on every graph
rebuild.

REASONING SCOPE -- deliberately none. Neo4j is a labeled property graph, not an
RDF/OWL store: it stores exactly what is written and derives nothing. Transitive
subsumption is answered operationally by `-[:SUBCLASS_OF*]->` (graph
reachability), not by logical entailment. That is sufficient here because this
TBox uses only RDFS-level constructs -- there is no `owl:disjointWith`, no
cardinality restriction, and no property characteristic (`owl:TransitiveProperty`
and friends) anywhere in it, so nothing present requires a reasoner.

The usual bridge for real OWL semantics would be the neosemantics (n10s) plugin,
which is not an option here and deliberately so: this platform installs no Neo4j
plugins (APOC was removed on purpose), and `scripts/ai_safety_guardrails.py`
blocks `CALL` in Cypher -- which is exactly how n10s procedures are invoked.
Using it would mean reversing two security decisions for a capability this
ontology does not need. If entailment is ever required, run a reasoner over the
TTL offline and materialize the inferred axioms here as ordinary edges; Neo4j
stays storage and the reasoning happens outside, with no plugin and no guardrail
change.

Idempotent: every write is a `MERGE` on `uri`, and the TBox labels are cleared
first so a removed axiom doesn't linger. Safe to re-run, and order-independent
relative to `build_knowledge_graph.py`.
===============================================================================
"""

import os
import sys
from collections import Counter

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _neo4j_conn reads NEO4J_* env config at import time, so it must be imported
# after load_env() -- see its module docstring.
from scripts._neo4j_conn import get_driver, run_write  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ONTOLOGY_TTL_PATH = os.path.join(REPO_ROOT, "ontology", "financial_platform_ontology.ttl")

# Cleared and rewritten on every run. Mirrors build_knowledge_graph.ABOX_LABELS
# in intent: an explicit allowlist, so this loader can never reach outside its
# own layer. tests/test_graph_wipe_scope.py asserts these never overlap.
TBOX_LABELS = ["OntologyClass", "OntologyProperty", "ExternalConcept"]


def _curie(graph, uri) -> str:
    """Prefixed form (`fin:Party`, `fibo-party:Party`) for human-readable output
    and for joining against other layers that record concepts by CURIE. Falls
    back to the full URI when no prefix is bound."""
    try:
        return graph.namespace_manager.normalizeUri(uri).strip("<>")
    except Exception:  # noqa: BLE001 -- normalizeUri is best-effort cosmetics
        return str(uri)


def parse_tbox(path: str = ONTOLOGY_TTL_PATH) -> dict:
    """Parses the TTL into plain dicts/lists ready for Cypher `UNWIND`.

    Returns classes, properties, and the three edge sets. Kept free of any
    Neo4j dependency so it can be unit-tested offline with no database.
    """
    from rdflib import OWL, RDF, RDFS, Graph

    graph = Graph()
    graph.parse(path, format="turtle")

    def _lit(subject, predicate):
        value = graph.value(subject, predicate)
        return str(value) if value is not None else None

    classes, subclass_of, defined_by, external = [], [], [], {}

    for uri in graph.subjects(RDF.type, OWL.Class):
        classes.append({
            "uri": str(uri),
            "curie": _curie(graph, uri),
            "label": _lit(uri, RDFS.label),
            "comment": _lit(uri, RDFS.comment),
        })
        for parent in graph.objects(uri, RDFS.subClassOf):
            subclass_of.append({"child": str(uri), "parent": str(parent)})
        # A class may carry several groundings -- fin:Customer is grounded in
        # both bian:CustomerRole and fibo-partyrole:Customer, which is a genuine
        # dual grounding rather than a contradiction (see the TTL's own comment).
        for target in graph.objects(uri, RDFS.isDefinedBy):
            defined_by.append({"cls": str(uri), "concept": str(target)})
            external[str(target)] = {"uri": str(target), "curie": _curie(graph, target)}

    properties, domains, ranges = [], [], []

    for kind, rdf_type in (("object", OWL.ObjectProperty), ("datatype", OWL.DatatypeProperty)):
        for uri in graph.subjects(RDF.type, rdf_type):
            range_value = graph.value(uri, RDFS.range)
            # An object property's range is another class, so it becomes an
            # edge. A datatype property's range is a literal type (xsd:decimal,
            # xsd:boolean, ...) with no node to point at, so it is stored as a
            # property on the term itself.
            properties.append({
                "uri": str(uri),
                "curie": _curie(graph, uri),
                "label": _lit(uri, RDFS.label),
                "kind": kind,
                "range_literal": _curie(graph, range_value) if (kind == "datatype" and range_value is not None) else None,
            })
            for target in graph.objects(uri, RDFS.domain):
                domains.append({"prop": str(uri), "cls": str(target)})
            if kind == "object" and range_value is not None:
                ranges.append({"prop": str(uri), "cls": str(range_value)})

    return {
        "classes": classes,
        "properties": properties,
        "external_concepts": list(external.values()),
        "subclass_of": subclass_of,
        "domains": domains,
        "ranges": ranges,
        "defined_by": defined_by,
    }


def build_statements(tbox: dict) -> list:
    """Turns a parsed TBox into `(cypher, params)` pairs.

    Batched with `UNWIND` rather than one statement per term: the ABox loaders
    issue a round trip per row, which is the reason a full graph rebuild takes
    as long as it does. Trivial at 40-odd terms, but there is no reason to
    repeat the slower pattern in new code.
    """
    statements = [
        (f"MATCH (n:{label}) DETACH DELETE n", {}) for label in TBOX_LABELS
    ]
    statements += [
        ("""UNWIND $rows AS r
            MERGE (c:OntologyClass {uri: r.uri})
            SET c.curie = r.curie, c.label = r.label, c.comment = r.comment""",
         {"rows": tbox["classes"]}),
        ("""UNWIND $rows AS r
            MERGE (p:OntologyProperty {uri: r.uri})
            SET p.curie = r.curie, p.label = r.label, p.kind = r.kind,
                p.range_literal = r.range_literal""",
         {"rows": tbox["properties"]}),
        ("""UNWIND $rows AS r
            MERGE (e:ExternalConcept {uri: r.uri}) SET e.curie = r.curie""",
         {"rows": tbox["external_concepts"]}),
        ("""UNWIND $rows AS r
            MATCH (child:OntologyClass {uri: r.child})
            MATCH (parent:OntologyClass {uri: r.parent})
            MERGE (child)-[:SUBCLASS_OF]->(parent)""",
         {"rows": tbox["subclass_of"]}),
        ("""UNWIND $rows AS r
            MATCH (p:OntologyProperty {uri: r.prop})
            MATCH (c:OntologyClass {uri: r.cls})
            MERGE (p)-[:DOMAIN]->(c)""",
         {"rows": tbox["domains"]}),
        ("""UNWIND $rows AS r
            MATCH (p:OntologyProperty {uri: r.prop})
            MATCH (c:OntologyClass {uri: r.cls})
            MERGE (p)-[:RANGE]->(c)""",
         {"rows": tbox["ranges"]}),
        ("""UNWIND $rows AS r
            MATCH (c:OntologyClass {uri: r.cls})
            MATCH (e:ExternalConcept {uri: r.concept})
            MERGE (c)-[:DEFINED_BY]->(e)""",
         {"rows": tbox["defined_by"]}),
    ]
    return statements


def main() -> None:
    print("🚀 Loading Ontology TBox (Turtle -> Neo4j)...")
    print("=============================================")

    if not os.path.exists(ONTOLOGY_TTL_PATH):
        print(f"❌ Ontology file not found: {ONTOLOGY_TTL_PATH}")
        sys.exit(1)

    try:
        tbox = parse_tbox()
    except ImportError:
        print("❌ rdflib is not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    counts = {k: len(v) for k, v in tbox.items()}
    print(f"📖 Parsed {os.path.relpath(ONTOLOGY_TTL_PATH, REPO_ROOT)}:")
    for key in ("classes", "properties", "external_concepts", "subclass_of", "domains", "ranges", "defined_by"):
        print(f"   • {key:<18} {counts[key]:>3}")

    if not tbox["classes"]:
        # An empty parse would otherwise wipe the TBox labels and write nothing,
        # quietly leaving the layer gone.
        print("❌ Parsed zero classes -- refusing to write an empty TBox.")
        sys.exit(1)

    kinds = Counter(p["kind"] for p in tbox["properties"])
    print(f"   ({kinds.get('object', 0)} object, {kinds.get('datatype', 0)} datatype properties)")

    driver = get_driver()
    try:
        print("\n⚡ Writing TBox to Neo4j...")
        run_write(driver, build_statements(tbox))
        with driver.session() as session:
            written = {
                label: session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
                for label in TBOX_LABELS
            }
            edges = {
                rel: session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()["c"]
                for rel in ("SUBCLASS_OF", "DOMAIN", "RANGE", "DEFINED_BY")
            }
    finally:
        driver.close()

    print("\n📊 In graph:")
    for label, n in written.items():
        print(f"   • :{label:<18} {n:>3} nodes")
    for rel, n in edges.items():
        print(f"   • :{rel:<18} {n:>3} relationships")

    print("\n✅ Ontology TBox loaded.")


if __name__ == "__main__":
    main()
