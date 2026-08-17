"""
TBox-driven query expansion — the payoff the ontology layer exists for.

`scripts/load_ontology_tbox.py` makes the ontology queryable; this module makes
the *retriever* use it. The chain is the one Phase 4 of the TBox plan describes:

    user term -> FIBO/BIAN concept -> subclasses -> grounded tables -> SQL

The value is entirely in the middle step. Tier 4's `TIER4_INTENT_QUERY_MAP` has
four hand-written intents (collateral / deposit / AML / default); the TBox has
ten concepts. A prompt about "organizations" or "loan applications" classifies
to INTENT_DEFAULT and gets a generic party count, because no branch exists for
it. Expansion reaches those concepts through the ontology instead of through a
hardcoded map, and — because it walks `SUBCLASS_OF` — a prompt about "parties"
also pulls in Individual and Organization without anyone enumerating that
relationship a second time. It is *additive*: the curated per-intent aggregates
are better answers where they apply, so they are not replaced.

Two deliberate design choices, both about keeping this trustworthy:

**Matching happens in Python, not in Cypher.** `fetch_concepts()` runs one
parameterless query that returns the whole TBox (ten rows — it is a schema, not
data), and matching runs against that in-process. So no user text is ever
interpolated into or bound through a graph query for this feature, and the
matching rules are pure functions that `tests/test_ontology_expansion.py` can
assert on with no database at all.

**Graph content is never authoritative for SQL.** `build_grounded_sql()` takes
an `allowed_tables` mapping sourced from `information_schema` and drops any
table not in it, then composes the statement with `psycopg2.sql.Identifier`
rather than string formatting. Table names arrive here from Neo4j, and a
knowledge graph is not a trust boundary — anything that can write a node
property must not thereby be able to shape SQL.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from scripts._sql_identifier import validate_identifier

try:  # psycopg2 is absent in the syntax-only CI job; the pure helpers still import.
    from psycopg2 import sql as _pgsql
except ImportError:  # pragma: no cover - exercised only where psycopg2 is missing
    _pgsql = None


# One parameterless read of the entire TBox, including the bridges the loader
# built. `head(...)` on the table/cube paths because a concept classifies
# exactly one KnowledgeEntityType by construction; a list would only push the
# "which one?" decision to every caller.
TBOX_FETCH_CYPHER = """
MATCH (c:OntologyClass)
RETURN c.curie AS concept,
       coalesce(c.label, '') AS label,
       coalesce(c.comment, '') AS definition,
       c.uri AS uri,
       [(c)<-[:SUBCLASS_OF*]-(s) | s.curie] AS subclasses,
       [(c)-[:DEFINED_BY]->(e) | e.curie] AS grounded_in,
       head([(c)-[:CLASSIFIES]->(:KnowledgeEntityType)
              <-[:INSTANTIATES_GRAPH]-(:SemanticCube)
              <-[:DERIVES_SEMANTICS_TO]-(t) | t.fqn]) AS source_table,
       head([(c)-[:CLASSIFIES]->(:KnowledgeEntityType)
              <-[:INSTANTIATES_GRAPH]-(cu) | cu.name]) AS semantic_cube
ORDER BY concept
"""

# Allowlist source for build_grounded_sql(). Deliberately reads the live
# catalog rather than trusting the graph or a checked-in list: a table that was
# dropped must stop being queryable here without anyone remembering to edit a
# constant. Also reports which tables carry the SCD2 activity flag, since the
# `ref_*` lookups do not and a blanket `WHERE md_is_active` would fail on them.
ALLOWED_TABLES_SQL = """
SELECT table_name,
       bool_or(column_name = 'md_is_active') AS has_active_flag
FROM information_schema.columns
WHERE table_schema = 'financial'
GROUP BY table_name
ORDER BY table_name;
"""

FINANCIAL_SCHEMA = "financial"

# Cap on tables probed in one expansion. Ten concepts cannot currently exceed
# this, but the SQL is a UNION ALL whose cost grows with the term count, and an
# ontology is the kind of artifact that grows without its consumers being
# revisited.
MAX_EXPANDED_TABLES = 12

# Words carried by TBox labels that describe the *modelling*, not the business
# concept ("Party Supertype", "Organization Legal Entity"). Matching on these
# would fire on unrelated prompts, so they are dropped from the label signal.
# The URI local name is the primary signal precisely because it has none of
# this noise.
_LABEL_STOPWORDS = frozenset({
    "supertype", "subtype", "type", "entity", "record", "detail", "details",
    "data", "info", "information",
})

_WORD_RE = re.compile(r"[a-z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _singularize(token: str) -> str:
    """Crude, deliberately so. The vocabulary being matched is ten fixed
    business nouns, not open English, so 'accounts' -> 'account' and
    'parties' -> 'party' is the entire requirement. A real stemmer would be a
    dependency and a behaviour change for no measurable gain here."""
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalize_tokens(text: str) -> Set[str]:
    """Lowercase alphanumeric tokens, singularized, as a set."""
    return {_singularize(w) for w in _WORD_RE.findall((text or "").lower())}


def local_name(concept: Dict[str, Any]) -> str:
    """The class name from the URI/curie — `fin:DepositAccount` -> `DepositAccount`."""
    uri = concept.get("uri") or ""
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    if "/" in uri:
        return uri.rsplit("/", 1)[-1]
    curie = concept.get("concept") or ""
    return curie.split(":", 1)[-1] if ":" in curie else curie


def concept_terms(concept: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    """Returns (name_tokens, label_tokens) for one concept.

    `name_tokens` comes from splitting the URI local name on camel-case
    boundaries — `DepositAccount` -> {deposit, account} — and is the primary
    signal. `label_tokens` is the human label minus modelling stopwords, and
    only ever widens the match.
    """
    name_tokens = normalize_tokens(_CAMEL_BOUNDARY_RE.sub(" ", local_name(concept)))
    label_tokens = normalize_tokens(concept.get("label", "")) - _LABEL_STOPWORDS
    return name_tokens, label_tokens


def match_concepts(prompt: str, concepts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Concepts the prompt refers to, each annotated with `match_reason`.

    A concept matches when *every* token of a signal appears in the prompt —
    not any. `DepositAccount` must not fire on a prompt that merely says
    "account", because `deposit_balance` and `loan_agreement` would fire on
    the same weak evidence and the expansion would degrade into "all tables".
    """
    prompt_tokens = normalize_tokens(prompt)
    if not prompt_tokens:
        return []

    matched: List[Dict[str, Any]] = []
    for concept in concepts:
        name_tokens, label_tokens = concept_terms(concept)
        if name_tokens and name_tokens <= prompt_tokens:
            reason = "name"
        elif label_tokens and label_tokens <= prompt_tokens:
            reason = "label"
        else:
            continue
        hit = dict(concept)
        hit["match_reason"] = reason
        matched.append(hit)
    return matched


def expand_subclasses(
    matched: Sequence[Dict[str, Any]], concepts: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Adds every transitive subclass of a matched concept.

    This is the step that makes the TBox worth querying rather than keeping a
    keyword->table dictionary: "parties" reaches Individual and Organization
    because the ontology says so, and adding a subclass to the TTL extends
    retrieval with no code change. Subsumption here is graph reachability
    (`SUBCLASS_OF*`, resolved by the loader), not entailment — nothing infers
    edges that were not asserted.
    """
    by_curie = {c.get("concept"): c for c in concepts}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for hit in matched:
        curie = hit.get("concept")
        if curie and curie not in seen:
            seen.add(curie)
            out.append(hit)
        for sub_curie in hit.get("subclasses") or []:
            if sub_curie in seen:
                continue
            sub = by_curie.get(sub_curie)
            if sub is None:
                # The TBox returned a subclass curie with no node of its own.
                # Skipped rather than synthesized: a half-known concept in a
                # retrieval payload is worse than an absent one.
                continue
            seen.add(sub_curie)
            entry = dict(sub)
            entry["match_reason"] = f"subclass_of:{curie}"
            out.append(entry)
    return out


def grounded_tables(expanded: Iterable[Dict[str, Any]]) -> List[str]:
    """Distinct `source_table` values, order-stable, `None`s dropped."""
    tables: List[str] = []
    for concept in expanded:
        table = concept.get("source_table")
        if table and table not in tables:
            tables.append(table)
    return tables


def _bare_name(table: str) -> Optional[str]:
    """`financial.deposit_account` -> `deposit_account`; `None` if malformed.

    The syntactic half is `_sql_identifier.validate_identifier`, the same check
    the catalog-driven pipeline scripts use before interpolating a name they
    got from OpenMetadata; `select_tables`' allowlist is the semantic half.
    That is the two-layer split `_sql_identifier`'s own module docstring
    prescribes, not a second scheme invented here.

    Returns `None` rather than a best-effort substring for anything that is not
    cleanly `name` or `financial.name`. That distinction found a real bug: a
    naive `rsplit('.', 1)[-1]` turns `financial.party; DROP TABLE x` into
    `party`, which *is* allowlisted -- so a hostile value would have been
    silently accepted as `financial.party` instead of rejected. The injected
    text never reached SQL (the statement is rebuilt from the allowlisted bare
    name, not from the input), but quietly reinterpreting a malformed name as a
    valid one is exactly the behaviour that turns a future refactor into a
    vulnerability.
    """
    if not table:
        return None
    parts = table.split(".")
    if len(parts) == 2:
        schema, name = parts
        if schema != FINANCIAL_SCHEMA:
            return None
    elif len(parts) == 1:
        name = parts[0]
    else:
        return None
    try:
        return validate_identifier(name, "table")
    except ValueError:
        return None


def select_tables(tables: Sequence[str], allowed_tables: Dict[str, bool]) -> List[str]:
    """Filters graph-supplied table names down to ones that provably exist.

    **This is the security boundary of the whole feature**, which is why it is
    a pure function of its own rather than a few lines inside the SQL builder:
    table names arrive here from Neo4j, and a knowledge graph is not a trust
    boundary — anything able to write a node property must not thereby be able
    to shape SQL. `allowed_tables` comes from `information_schema` (see
    ALLOWED_TABLES_SQL), so a name survives only by matching a real table.
    Anything else is dropped silently; there is no "pass it through and hope
    the database rejects it" path.

    Returns fully-qualified `financial.<name>` strings, de-duplicated,
    order-stable, capped at MAX_EXPANDED_TABLES.
    """
    used: List[str] = []
    for table in tables:
        bare = _bare_name(table)
        if bare is None or bare not in allowed_tables:
            continue
        qualified = f"{FINANCIAL_SCHEMA}.{bare}"
        if qualified in used:
            continue
        if len(used) >= MAX_EXPANDED_TABLES:
            break
        used.append(qualified)
    return used


def build_grounded_sql(
    tables: Sequence[str], allowed_tables: Dict[str, bool], context: Any
) -> Tuple[Optional[str], List[str]]:
    """Builds a row-count probe over the grounded tables. Returns (sql, used).

    `allowed_tables` maps bare table name -> whether it carries `md_is_active`.
    Filtering is delegated to `select_tables()` above; composition then uses
    `psycopg2.sql.Identifier` so even an already-allowlisted name is quoted by
    libpq rather than concatenated into a string.

    `context` must be a live psycopg2 connection or cursor — `quote_ident()`
    asks libpq how to quote, so there is no offline rendering path. The
    allowlist decision is separately testable without one, which is the part
    that actually matters.

    Returns `(None, [])` when nothing survives, so the caller can distinguish
    "no grounded tables" from "an empty result set".
    """
    if _pgsql is None:  # pragma: no cover - psycopg2 always present at runtime
        raise RuntimeError("psycopg2 is required to build grounded SQL")

    used = select_tables(tables, allowed_tables)
    if not used:
        return None, []

    parts = []
    for qualified in used:
        # Safe by construction: `used` comes from select_tables(), which built
        # each entry as f"{FINANCIAL_SCHEMA}.{allowlisted_bare_name}".
        bare = qualified.split(".", 1)[1]
        part = _pgsql.SQL("SELECT {label} AS source_table, COUNT(*) AS row_count FROM {tbl}").format(
            label=_pgsql.Literal(qualified),
            tbl=_pgsql.Identifier(FINANCIAL_SCHEMA, bare),
        )
        if allowed_tables[bare]:
            # Only where the column exists: the ref_* lookups have no SCD2
            # header, and an unconditional filter would make this raise on them.
            part = _pgsql.SQL("{base} WHERE md_is_active = TRUE").format(base=part)
        parts.append(part)

    statement = _pgsql.SQL(" UNION ALL ").join(parts)
    statement = _pgsql.SQL("{body} ORDER BY source_table;").format(body=statement)
    return statement.as_string(context), used


def fetch_concepts(run_cypher: Callable[[str], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Reads the whole TBox through a caller-supplied Cypher runner.

    Takes the runner as an argument so the retriever and the MCP server can
    each pass their own already-guardrailed, READ_ACCESS-scoped executor
    rather than this module opening a second Neo4j connection with different
    controls.
    """
    return run_cypher(TBOX_FETCH_CYPHER)


def expand(
    prompt: str,
    concepts: Sequence[Dict[str, Any]],
    allowed_tables: Optional[Dict[str, bool]] = None,
    context: Any = None,
) -> Dict[str, Any]:
    """Full expansion for one prompt. Pure — no I/O, given `concepts`.

    Omitting `allowed_tables`/`context` skips SQL construction and returns the
    concept reasoning alone, which is what a caller that only wants to know
    *which concepts* a prompt touches should do.
    """
    matched = match_concepts(prompt, concepts)
    expanded = expand_subclasses(matched, concepts)
    tables = grounded_tables(expanded)

    result: Dict[str, Any] = {
        "matched_concepts": [
            {"concept": m.get("concept"), "label": m.get("label"),
             "match_reason": m.get("match_reason")}
            for m in matched
        ],
        "expanded_concepts": [
            {"concept": e.get("concept"), "label": e.get("label"),
             "match_reason": e.get("match_reason"),
             "grounded_in": e.get("grounded_in") or [],
             "source_table": e.get("source_table"),
             "semantic_cube": e.get("semantic_cube")}
            for e in expanded
        ],
        "grounded_tables": tables,
    }

    if allowed_tables is not None and context is not None and tables:
        sql, used = build_grounded_sql(tables, allowed_tables, context)
        result["expansion_sql"] = sql
        result["probed_tables"] = used
    return result
