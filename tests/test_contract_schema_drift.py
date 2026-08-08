"""
CI-blocking drift check between contracts/*.yaml and the live schema
definition in the base migration SQL (see D2 in the hardening plan: "add a
CI check asserting every declared column and allowed_values set matches
information_schema and the live CHECK constraints. This one check would have
caught all five defects above.").

Static (parses the migration .sql file directly, no live database needed),
so this runs as a normal blocking pytest test in CI.
"""

from scripts._schema_drift import find_drift


def test_no_contract_schema_drift():
    problems = find_drift()
    assert not problems, "Contract <-> schema drift detected:\n" + "\n".join(f"  - {p}" for p in problems)
