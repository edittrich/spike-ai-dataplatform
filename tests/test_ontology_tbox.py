"""
Tests for scripts/load_ontology_tbox.py -- the TBox (ontology) layer.

The parse half is fully offline: `parse_tbox()` deliberately has no Neo4j
dependency, so the axiom counts, the object/datatype split and the
domain/range edge distinction are all checked in CI with no database. The
live half (that the TBox actually lands in the graph and is traversable)
skips cleanly when no Neo4j is reachable, matching
tests/test_postgres_readonly_role.py.

The expected counts below come from a real rdflib parse of the committed TTL,
not from reading it by eye -- an earlier grep-based count of the same file
reported 11 classes where there are 10.
"""

import os

import pytest

from scripts.load_ontology_tbox import ONTOLOGY_TTL_PATH, TBOX_LABELS, build_statements, parse_tbox

# ontology/financial_platform_ontology.ttl as committed.
EXPECTED = {
    "classes": 10,
    "properties": 10,          # 5 object + 5 datatype
    "subclass_of": 3,
    "domains": 10,
    "ranges": 5,               # object properties only -- datatype ranges are literals
    "defined_by": 9,           # 8 grounded classes, one of which (fin:Customer) has two
    "external_concepts": 9,
}


@pytest.fixture(scope="module")
def tbox():
    return parse_tbox()


def test_ontology_file_exists():
    assert os.path.exists(ONTOLOGY_TTL_PATH), f"missing ontology TTL at {ONTOLOGY_TTL_PATH}"


@pytest.mark.parametrize("key,expected", sorted(EXPECTED.items()))
def test_axiom_counts(tbox, key, expected):
    """Anti-vacuity guard as much as a parity check: if the parse silently
    returned nothing, every other assertion here would pass trivially."""
    assert len(tbox[key]) == expected, (
        f"{key}: expected {expected}, got {len(tbox[key])}. If the ontology genuinely "
        f"changed, update EXPECTED -- but confirm the change was intended first."
    )


def test_tbox_contains_no_individuals():
    """The defining property of a TBox. If individuals ever appear here they
    would be instance data entering a store with no RBAC, via a path that
    bypasses build_knowledge_graph.py's PII decisions entirely."""
    from rdflib import OWL, RDF, Graph

    graph = Graph()
    graph.parse(ONTOLOGY_TTL_PATH, format="turtle")
    individuals = list(graph.subjects(RDF.type, OWL.NamedIndividual))
    assert individuals == [], f"TBox must contain no individuals, found {individuals}"


def test_object_and_datatype_properties_are_split(tbox):
    kinds = {p["kind"] for p in tbox["properties"]}
    assert kinds == {"object", "datatype"}
    assert sum(1 for p in tbox["properties"] if p["kind"] == "object") == 5
    assert sum(1 for p in tbox["properties"] if p["kind"] == "datatype") == 5


def test_datatype_ranges_are_literals_not_edges(tbox):
    """A datatype property's range (xsd:decimal, xsd:boolean, ...) has no node
    to point at, so it must be stored on the term and must never appear as a
    RANGE edge -- otherwise the loader would MATCH a class that doesn't exist
    and silently drop the property."""
    datatype_props = [p for p in tbox["properties"] if p["kind"] == "datatype"]
    assert all(p["range_literal"] for p in datatype_props), "datatype range not captured"
    assert {p["range_literal"] for p in datatype_props} <= {
        "xsd:string", "xsd:decimal", "xsd:boolean"
    }
    ranged = {r["prop"] for r in tbox["ranges"]}
    assert not ranged & {p["uri"] for p in datatype_props}, (
        "a datatype property produced a RANGE edge; it has no target class"
    )


def test_known_hierarchy_is_present(tbox):
    """Spot-check the actual content rather than only its shape."""
    pairs = {(c["child"].rsplit("#", 1)[-1], c["parent"].rsplit("#", 1)[-1]) for c in tbox["subclass_of"]}
    assert ("Individual", "Party") in pairs
    assert ("Organization", "Party") in pairs
    assert ("Customer", "PartyRole") in pairs


def test_customer_has_both_groundings(tbox):
    """fin:Customer is grounded in both BIAN and FIBO -- a deliberate dual
    grounding the TTL calls out explicitly. A parser that took only the first
    object of rdfs:isDefinedBy would silently drop one."""
    customer = [d for d in tbox["defined_by"] if d["cls"].endswith("#Customer")]
    assert len(customer) == 2, f"expected 2 groundings for fin:Customer, got {len(customer)}"


def test_curies_are_resolved(tbox):
    """Full URIs are the identity; CURIEs are what make the graph readable."""
    by_uri = {c["uri"]: c for c in tbox["classes"]}
    party = next(c for u, c in by_uri.items() if u.endswith("#Party"))
    assert party["curie"] == "fin:Party"
    assert party["label"] == "Party Supertype"


def test_build_statements_wipes_only_tbox_labels():
    """The loader must never reach outside its own layer -- the same
    discipline build_knowledge_graph.ABOX_LABELS follows."""
    from scripts.build_knowledge_graph import ABOX_LABELS

    deletes = [c for c, _ in build_statements(parse_tbox()) if "DETACH DELETE" in c]
    assert len(deletes) == len(TBOX_LABELS)
    for stmt in deletes:
        assert any(f"(n:{label})" in stmt for label in TBOX_LABELS)
        assert not any(f"(n:{label})" in stmt for label in ABOX_LABELS)


def test_refuses_to_write_an_empty_tbox():
    """A parse returning nothing must not clear the labels and write nothing,
    which would silently delete the layer."""
    stmts = build_statements(
        {k: [] for k in ("classes", "properties", "external_concepts",
                         "subclass_of", "domains", "ranges", "defined_by")}
    )
    # build_statements itself stays pure; main() is what refuses. Assert the
    # guard exists rather than that build_statements raises.
    import inspect

    from scripts import load_ontology_tbox

    assert "refusing to write an empty TBox" in inspect.getsource(load_ontology_tbox.main)
    assert stmts, "build_statements should still emit the (harmless) wipe statements"


# ---------------------------------------------------------------------------
# Live checks -- skipped when no Neo4j is reachable.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def neo4j_session():
    from scripts._dotenv_boot import load_env

    load_env()
    if not os.getenv("NEO4J_PASSWORD"):
        pytest.skip("NEO4J_PASSWORD not set -- no live graph configured")
    try:
        from neo4j import READ_ACCESS, GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
            connection_timeout=3,
        )
        driver.verify_connectivity()
    except Exception as e:  # noqa: BLE001 -- any failure means "no live graph"
        pytest.skip(f"No live Neo4j reachable: {e}")
    session = driver.session(default_access_mode=READ_ACCESS)
    yield session
    session.close()
    driver.close()


def test_tbox_is_loaded_in_graph(neo4j_session):
    n = neo4j_session.run("MATCH (c:OntologyClass) RETURN count(c) AS c").single()["c"]
    if n == 0:
        pytest.skip("TBox not loaded yet -- run: python3 scripts/load_ontology_tbox.py")
    assert n == EXPECTED["classes"]


def test_transitive_subsumption_by_reachability(neo4j_session):
    """The reachability substitute for OWL subsumption inference. fin:Customer
    is a direct subclass of fin:PartyRole; a variable-length walk is what
    answers 'all ancestors' without a reasoner."""
    if neo4j_session.run("MATCH (c:OntologyClass) RETURN count(c) AS c").single()["c"] == 0:
        pytest.skip("TBox not loaded yet")
    ancestors = neo4j_session.run(
        """MATCH (c:OntologyClass {curie: 'fin:Customer'})-[:SUBCLASS_OF*]->(a:OntologyClass)
           RETURN collect(a.curie) AS ancestors"""
    ).single()["ancestors"]
    assert "fin:PartyRole" in ancestors


def test_bridge_statements_never_touch_abox_or_lineage_nodes():
    """The bridges only MERGE edges. If a bridge statement ever created or
    deleted a node in another layer, this loader would be mutating data it
    does not own."""
    from scripts.load_ontology_tbox import build_bridge_statements

    for cypher, _params in build_bridge_statements(parse_tbox()):
        assert "DELETE" not in cypher.upper(), f"bridge statement deletes: {cypher}"
        # MERGE on a relationship pattern is fine; MERGE creating a bare node
        # in another layer is not.
        assert "MERGE (n:" not in cypher and "MERGE (k:" not in cypher, (
            f"bridge statement may create a foreign node: {cypher}"
        )


def test_instance_of_targets_only_labels_the_abox_actually_has():
    """A class with no matching ABox label (fin:PartyRole) must produce no
    INSTANCE_OF statement -- otherwise the loader emits Cypher against a label
    that does not exist, which matches nothing and hides the mismatch."""
    from scripts.build_knowledge_graph import ABOX_LABELS
    from scripts.load_ontology_tbox import build_bridge_statements

    tbox = parse_tbox()
    instance_stmts = [c for c, _ in build_bridge_statements(tbox) if "INSTANCE_OF" in c]
    local_names = {c["local_name"] for c in tbox["classes"]}
    assert "PartyRole" in local_names and "PartyRole" not in ABOX_LABELS
    assert not any("(n:PartyRole)" in c for c in instance_stmts)
    # Every emitted statement must target a real ABox label.
    for stmt in instance_stmts:
        label = stmt.split("MATCH (n:", 1)[1].split(")", 1)[0]
        assert label in ABOX_LABELS, f"INSTANCE_OF targets non-ABox label {label!r}"


def test_subclass_labels_are_excluded_for_most_specific_typing():
    """fin:Party's statement must exclude nodes that also carry a subclass
    label, so a Party+Individual node is typed fin:Individual only."""
    from scripts.load_ontology_tbox import build_bridge_statements

    party = [
        c for c, _ in build_bridge_statements(parse_tbox())
        if "INSTANCE_OF" in c and "MATCH (n:Party)" in c
    ]
    assert len(party) == 1
    assert "NOT n:Individual" in party[0]
    assert "NOT n:Organization" in party[0]


def test_bridges_are_present_in_graph(neo4j_session):
    if neo4j_session.run("MATCH (c:OntologyClass) RETURN count(c) AS c").single()["c"] == 0:
        pytest.skip("TBox not loaded yet")
    classifies = neo4j_session.run(
        "MATCH ()-[r:CLASSIFIES]->() RETURN count(r) AS c"
    ).single()["c"]
    if classifies == 0:
        pytest.skip("lineage layer absent -- run scripts/sync_end_to_end_lineage.py")
    # 9 of the 10 classes map to a :KnowledgeEntityType; fin:PartyRole is an
    # abstract superclass with no corresponding entity type.
    assert classifies == 9


def test_full_cross_layer_traversal(neo4j_session):
    """The reason CLASSIFIES exists: one hop onto the lineage chain reaches
    both the source table and the Cube.js metric, without the TBox re-encoding
    either association."""
    if neo4j_session.run("MATCH ()-[r:CLASSIFIES]->() RETURN count(r) AS c").single()["c"] == 0:
        pytest.skip("lineage layer or TBox absent")
    row = neo4j_session.run(
        """MATCH (c:OntologyClass {curie: 'fin:DepositAccount'})-[:CLASSIFIES]->(k:KnowledgeEntityType)
           MATCH (cube:SemanticCube)-[:INSTANTIATES_GRAPH]->(k)
           MATCH (t:PostgreSQLTable)-[:DERIVES_SEMANTICS_TO]->(cube)
           RETURN t.fqn AS tbl, cube.name AS cube"""
    ).single()
    assert row["tbl"] == "financial.deposit_account"
    assert row["cube"] == "Cube_DepositAccount"


def test_abox_nodes_are_typed_exactly_once(neo4j_session):
    """Most-specific typing: no node carries two INSTANCE_OF edges, or the
    edge count would exceed the node count for no added information."""
    if neo4j_session.run("MATCH ()-[r:INSTANCE_OF]->() RETURN count(r) AS c").single()["c"] == 0:
        pytest.skip("TBox bridges not loaded yet")
    worst = neo4j_session.run(
        """MATCH (n)-[r:INSTANCE_OF]->() WITH n, count(r) AS c
           RETURN max(c) AS worst"""
    ).single()["worst"]
    assert worst == 1, f"a node carries {worst} INSTANCE_OF edges; typing must be most-specific"


def test_only_reference_data_is_untyped(neo4j_session):
    """The known, expected coverage gap -- asserted so it stays known. The
    ref_* lookups have no TBox class; anything else appearing here means a
    class silently stopped matching its ABox label."""
    if neo4j_session.run("MATCH ()-[r:INSTANCE_OF]->() RETURN count(r) AS c").single()["c"] == 0:
        pytest.skip("TBox bridges not loaded yet")
    from scripts.build_knowledge_graph import ABOX_LABELS

    rows = neo4j_session.run(
        """MATCH (n) WHERE any(l IN labels(n) WHERE l IN $abox)
           AND NOT (n)-[:INSTANCE_OF]->()
           RETURN DISTINCT labels(n) AS labels""",
        abox=list(ABOX_LABELS),
    ).data()
    untyped = {label for row in rows for label in row["labels"]}
    assert untyped == {"RefCountry", "RefCurrency", "RefIndustry"}, (
        f"unexpected untyped ABox labels: {sorted(untyped)}"
    )


def test_tbox_and_abox_coexist(neo4j_session):
    """The point of the label namespacing: both layers live in one database
    (Community allows only one) without colliding."""
    if neo4j_session.run("MATCH (c:OntologyClass) RETURN count(c) AS c").single()["c"] == 0:
        pytest.skip("TBox not loaded yet")
    row = neo4j_session.run(
        "MATCH (t:OntologyClass) WITH count(t) AS tbox MATCH (p:Party) RETURN tbox, count(p) AS abox"
    ).single()
    assert row["tbox"] > 0 and row["abox"] > 0
    overlap = neo4j_session.run(
        "MATCH (n:OntologyClass) WHERE n:Party RETURN count(n) AS c"
    ).single()["c"]
    assert overlap == 0, "TBox and ABox labels must never be applied to the same node"
