// ============================================================================
// Neo4j Knowledge Graph Schema DDL: Constraints & Indexes
// ============================================================================
// Committed, versioned Cypher DDL -- the analogue of supabase/migrations/*.sql
// for the graph database. Previously these 7 uniqueness constraints existed
// only as a hardcoded Python list inside scripts/build_knowledge_graph.py
// (buried in application/pipeline code, not reviewable as schema on its
// own), and there was no full-text index anywhere despite the platform
// advertising "hybrid retrieval" -- see item 10 in Part 5 ("Missing
// capabilities") of the hardening plan.
//
// Applied by scripts/build_knowledge_graph.py (which reads and executes this
// file rather than hardcoding these statements), but can also be applied
// directly, e.g. via cypher-shell:
//   cat neo4j/schema/constraints_and_indexes.cypher | cypher-shell -u neo4j -p <password>
//
// Every statement is `IF NOT EXISTS` and therefore idempotent -- safe to
// re-run. Verified live: Neo4j 5's IF NOT EXISTS checks *schema equivalence*
// (same label + property + constraint/index type), not name equality, so
// introducing these explicit names does not conflict with or duplicate the
// auto-named constraints (`constraint_<hex>`) a pre-Phase-3 graph build may
// already have created for the same schema.
//
// NOTE: `MATCH (n) DETACH DELETE n` (the graph wipe in build_knowledge_graph.py)
// deletes nodes and relationships only -- constraints and indexes are schema,
// not data, and persist across a wipe. This file is safe to re-apply on every
// pipeline run for exactly that reason.
// ============================================================================

// ----------------------------------------------------------------------------
// Uniqueness constraints (also each backed by an auto-created range index --
// this is what previously made lookups like `MATCH (p:Party {party_id: $id})`
// fast: without one, every such lookup would be a full label scan).
// ----------------------------------------------------------------------------
CREATE CONSTRAINT party_id_unique IF NOT EXISTS FOR (p:Party) REQUIRE p.party_id IS UNIQUE;
CREATE CONSTRAINT customer_id_unique IF NOT EXISTS FOR (c:Customer) REQUIRE c.party_role_customer_id IS UNIQUE;
CREATE CONSTRAINT deposit_account_id_unique IF NOT EXISTS FOR (a:DepositAccount) REQUIRE a.deposit_account_id IS UNIQUE;
CREATE CONSTRAINT loan_agreement_id_unique IF NOT EXISTS FOR (l:LoanAgreement) REQUIRE l.loan_agreement_id IS UNIQUE;
CREATE CONSTRAINT ref_country_code_unique IF NOT EXISTS FOR (rc:RefCountry) REQUIRE rc.code IS UNIQUE;
CREATE CONSTRAINT ref_currency_code_unique IF NOT EXISTS FOR (rcur:RefCurrency) REQUIRE rcur.code IS UNIQUE;
CREATE CONSTRAINT ref_industry_code_unique IF NOT EXISTS FOR (rind:RefIndustry) REQUIRE rind.code IS UNIQUE;

// ----------------------------------------------------------------------------
// Full-text indexes -- previously entirely absent. Without one, the only way
// to find a party was an exact match on a UUID or business key; a natural-
// language question like "find accounts for a customer named Schmidt" had no
// way to resolve "Schmidt" to a node at all. Modern declarative `CREATE
// FULLTEXT INDEX` syntax (Neo4j 5+) rather than the older
// `db.index.fulltext.createNodeIndex(...)` procedure it superseded -- both
// build the same underlying Lucene-backed index; the declarative form is
// Neo4j's own current recommendation and is what `SHOW INDEXES` reports
// consistently alongside the range indexes above.
//
// Each index spans multiple labels with a shared property list; a label
// missing one of the listed properties simply isn't indexed on that property
// for that label (e.g. RefCountry has no `title`, so it's only searchable via
// `name`) -- this is standard full-text-index behavior, not a workaround.
// ----------------------------------------------------------------------------

// Search parties (people and organizations) by name.
CREATE FULLTEXT INDEX party_name_fulltext IF NOT EXISTS
FOR (n:Individual|Organization)
ON EACH [n.first_name, n.last_name, n.legal_name];

// Search reference/lookup entities (countries, currencies, industries) by
// name -- e.g. resolving "gambling" to the matching NACE industry title
// before traversing OPERATES_IN_INDUSTRY, instead of requiring the exact code.
CREATE FULLTEXT INDEX reference_name_fulltext IF NOT EXISTS
FOR (n:RefCountry|RefCurrency|RefIndustry)
ON EACH [n.name, n.title];
