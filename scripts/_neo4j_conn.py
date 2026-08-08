#!/usr/bin/env python3
"""
===============================================================================
Shared Neo4j Driver Factory
===============================================================================
Single place that reads NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD and builds a
`neo4j.GraphDatabase` driver with a connection timeout -- previously this
preamble was copy-pasted (with the credentials embedded in raw HTTP Basic-Auth
headers, or on a `cypher-shell -p` command line, in the pipeline scripts) in
4+ places across the repo. Centralizing it here means:
  - the password never appears on a subprocess command line (visible via
    `ps aux` / `/proc/*/cmdline` on any multi-user host) or is base64'd into
    an HTTP header by hand -- the driver takes credentials as a Python tuple.
  - every caller gets the same connection_timeout instead of hanging forever.
  - callers can pass Cypher `$parameters` instead of f-string-interpolating
    values into the query text, closing the injection surface described in
    the C6 finding (see CLAUDE.md / the hardening plan).

IMPORTANT for callers: NEO4J_URI/USER/PASSWORD below are read at *import
time*, so this module must be imported *after* `scripts._dotenv_boot.load_env()`
has run in the importing script -- importing it earlier silently captures
empty credentials (matches the existing convention in `_embedding_backend.py`).
===============================================================================
"""

import os

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def get_driver(connection_timeout: int = 10):
    """Returns a new neo4j.GraphDatabase driver using the shared env config.

    Callers are responsible for closing it (use as a context manager, or call
    `.close()`), matching the neo4j driver's own contract.
    """
    return GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=connection_timeout
    )


def run_write(driver, statements_and_params, database: str = "neo4j"):
    """Executes a list of (cypher_statement, parameters_dict) tuples in a
    single write session, one transaction per statement (auto-committed via
    `session.run`, matching the previous scripts' one-statement-at-a-time
    semantics). Returns nothing; raises on the first Neo4j error rather than
    swallowing it into a print() the way the old HTTP tx/commit callers did.
    """
    with driver.session(database=database) as session:
        for statement, params in statements_and_params:
            session.run(statement, params or {})
