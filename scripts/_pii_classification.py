"""
===============================================================================
Shared PII column classification (single source of truth)
===============================================================================
H2/H8 in the hardening plan both trace back to the same root cause: the
platform had *two* disagreeing ideas of what counts as PII --
`automate_openmetadata_pii_and_profiling.py`'s catalog auto-tagger classified
columns one way, and nothing else (Cube.js dimensions, MCP tool responses,
`scripts/ai_safety_guardrails.py`'s free-text redaction) agreed with or even
consulted it. These two pattern lists used to live only in
`automate_openmetadata_pii_and_profiling.py`; extracted here so every
consumer imports the same list instead of maintaining its own copy that can
drift (exactly how D2's contract-vs-schema drift and D6's PII-pattern drift
happened in the first place).

Column-name substring matching, not a database/API call -- safe to import
from anywhere, including scripts/ai_safety_guardrails.py, without triggering
any of the "reads credentials at import time" concerns _neo4j_conn.py etc.
have (see CLAUDE.md's Secrets convention section).
===============================================================================
"""

# Ordinary personal data -- identifying, but not a GDPR/CCPA "special
# category" (health, biometric, precise financial-identity, etc.).
PII_PERSONAL_PATTERNS = [
    # street_address/building_number (not address_line1/address_line2, which
    # don't exist in supabase/migrations/20260722000000_create_financial_platform_schema.sql --
    # the phantom names meant street addresses were never actually tagged).
    "first_name", "last_name", "street_address", "building_number",
    "city", "postal_code", "account_number", "target_account_number",
]

# Special-category PII -- higher sensitivity; H2's fix masks these as
# `public: false` in the corresponding Cube.js dimension (see
# tests/test_pii_cube_enforcement.py, which fails CI if a matching dimension
# is ever added/left public).
PII_SPECIAL_PATTERNS = [
    # registration_number (not tax_identifier, same phantom-column issue --
    # see contracts/party_customer_data_product_contract.yaml, which had the
    # identical mistake).
    "id_number", "date_of_birth", "registration_number",
    # H2/H8: named explicitly in the hardening plan as columns the contract/
    # redactor disagreed about; both added here as the single fix for that
    # disagreement. `gender` is a protected characteristic under most
    # data-protection regimes (GDPR Art. 9-equivalent), so it belongs in
    # SpecialCategory alongside DOB, not PII_PERSONAL_PATTERNS. `party_bk`
    # is `financial.party`'s business-key identifier -- not personal data in
    # the GDPR sense by itself, but H8 named it explicitly as an
    # under-covered identifier, and it is 1:1 with a real natural person for
    # INDIVIDUAL party rows, so it's treated the same as an ID number here.
    "gender", "party_bk",
]

# Subset of PII_SPECIAL_PATTERNS that H2's fix also masks as a Cube.js
# dimension (`public: false`) -- deliberately narrower than the full list
# above. `party_bk` is excluded here on purpose: it's `financial.party`'s
# business-key identifier, playing the same "legitimate join/lookup key"
# role the already-public `party_id` surrogate key plays -- unlike
# `gender`/`date_of_birth`/`id_number`/`registration_number`, which are pure
# identity attributes with no legitimate use as a queryable BI/analytics
# slicing dimension. It remains SpecialCategory for catalog tagging and
# MCP-tool-response redaction (H6/H8's context: returning a customer's
# business key inside a raw query result is a real disclosure to an AI
# agent), just not for this narrower "should this be a public Cube.js
# dimension" question. See tests/test_pii_cube_enforcement.py.
PII_CUBEJS_MASK_PATTERNS = ["id_number", "date_of_birth", "registration_number", "gender"]


def classify_column(col_name: str) -> str | None:
    """Returns "SpecialCategory", "Personal", or None for a column name,
    using the same substring-match semantics as
    automate_openmetadata_pii_and_profiling.py's existing tagging loop
    (special-category checked first, since a name could in principle match
    both lists)."""
    if any(pat in col_name for pat in PII_SPECIAL_PATTERNS):
        return "SpecialCategory"
    if any(pat in col_name for pat in PII_PERSONAL_PATTERNS):
        return "Personal"
    return None
