"""
===============================================================================
Shared data-contract loader (D2 in the hardening plan)
===============================================================================
Before this module, contracts/*.yaml's content was hand-duplicated three
times: as markdown literals inside register_openmetadata_data_contracts.py's
DATA_PRODUCTS list, a third time as a hardcoded string inside
mcp_server/financial_data_mcp_server.py's `financial://data-contracts/slas`
resource, and the YAML files themselves -- referenced by path
(`"contract_file": "contracts/...yaml"`) but never actually parsed by either
of the other two. All three were free to drift independently, and did (D2's
own writeup found three phantom columns and two contradictory
`allowed_values` sets this way).

This module is the single place that reads contracts/*.yaml and renders it
into the text those two callers need, so a contract edit only has to happen
in one place. `scripts/_schema_drift.py` (the CI drift check) reads the YAML
independently for its own purpose (validating columns/allowed_values against
the live migration SQL, not rendering markdown) and is left as-is -- the two
don't need to share code, only the two markdown-rendering call sites did.

Safe to import in `mcp_server/financial_data_mcp_server.py`: no credentials,
no import-time network/DB call (unlike `_neo4j_conn.py`/
`_openmetadata_client.py`/`_embedding_backend.py`, see CLAUDE.md's Secrets
convention section) -- just a filesystem read of contracts/*.yaml, which
`mcp_server/Dockerfile.mcp`'s `COPY . .` bakes into the sidecar image (not
excluded by `.dockerignore`).
===============================================================================
"""

import os
from typing import Any

import yaml

CONTRACTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
)

# Explicit, ordered list rather than a glob -- the order here is the order
# both callers render/iterate in, and an explicit list fails loudly (a clear
# FileNotFoundError) if a contract file is ever renamed, instead of silently
# picking up whatever *.yaml happens to be in the directory.
CONTRACT_FILES = [
    "party_customer_data_product_contract.yaml",
    "deposit_liquidity_data_product_contract.yaml",
    "loan_credit_risk_data_product_contract.yaml",
]


def load_contracts() -> list[dict[str, Any]]:
    """Parses every file in CONTRACT_FILES and returns their raw dicts, in
    that order. Each dict gets an added "_source_file" key
    ("contracts/<filename>") so a caller can match a loaded contract back to
    the `contract_file` value it already had on hand. Raises FileNotFoundError/
    yaml.YAMLError on a missing/malformed file rather than skipping it --
    a contract that fails to parse should stop the registration run, not
    silently publish a stale or incomplete data product."""
    contracts = []
    for filename in CONTRACT_FILES:
        path = os.path.join(CONTRACTS_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data["_source_file"] = f"contracts/{filename}"
        contracts.append(data)
    return contracts


def render_contract_markdown(contract: dict[str, Any]) -> str:
    """Renders one parsed contract dict into the same markdown shape
    register_openmetadata_data_contracts.py previously hand-wrote once per
    contract -- SLAs plus one bullet per `models:` table, each annotated
    with the PII classification of any column that declares one. This is
    now the only place that formatting is written."""
    sla = contract.get("sla", {})
    owner = contract.get("owner", {})
    # contract["name"] already ends in "Contract" for every file in
    # CONTRACT_FILES today (e.g. "Party & Customer Data Product Contract"),
    # so it's used as-is rather than appending the word a second time.
    lines = [
        f"### \U0001f4dc {contract.get('name', contract.get('dataset', 'Data Product'))}",
        f"**Version:** `{contract.get('version', '?')}` | **Status:** `{str(contract.get('status', '?')).upper()}`",
        f"**Domain:** {contract.get('domain', '?')} | **Owner:** {owner.get('name', '?')}",
        "",
        "#### ⏱️ Service Level Agreements (SLAs)",
        f"- **Freshness SLA:** `{sla.get('freshness', '?')}`",
        f"- **Availability SLA:** `{sla.get('availability', '?')}`",
        f"- **Retention Policy:** `{sla.get('retention', '?')}`",
        f"- **Data Quality Threshold:** `{sla.get('data_quality_score', '?')}`",
        "",
        "#### \U0001f6e1️ Schema & Quality Guarantees",
    ]
    for table_name, model in contract.get("models", {}).items():
        desc = model.get("description", "")
        pii_cols = [
            col
            for col, spec in model.get("columns", {}).items()
            if isinstance(spec, dict) and spec.get("pii_classification")
        ]
        pii_note = f" (PII: {', '.join(pii_cols)})" if pii_cols else ""
        lines.append(f"- `{table_name}`: {desc}{pii_note}")
    return "\n".join(lines) + "\n"


def render_sla_summary() -> str:
    """Renders the same per-product SLA figures
    `financial_data_mcp_server.py`'s `financial://data-contracts/slas`
    resource previously hardcoded as an independent third copy."""
    lines = ["Data Product SLAs:"]
    for contract in load_contracts():
        sla = contract.get("sla", {})
        # Strip a trailing " Contract" from the display name -- every
        # contract["name"] today already ends in "... Contract" (it's a
        # contract, after all), but this line is naming the *product* the
        # SLA applies to, matching this resource's pre-existing phrasing
        # ("Party & Customer Data Product: Freshness ...", not "... Data
        # Product Contract: Freshness ...").
        product_name = contract.get("name", "?")
        if product_name.endswith(" Contract"):
            product_name = product_name[: -len(" Contract")]
        lines.append(
            f"- {product_name}: "
            f"Freshness {sla.get('freshness', '?')}, "
            f"Availability {sla.get('availability', '?')}, "
            f"Quality Threshold {sla.get('data_quality_score', '?')}."
        )
    return "\n".join(lines) + "\n"
