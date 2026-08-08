"""
H2 in the hardening plan: "The contract's classification is never enforced
anywhere -- not in the database, not in Cube.js, not in CI. The contracts
are declarative documents with no verifier." This is that verifier.

Statically parses every cube/model/cubes/*.yml file (no live Cube.js/DB
needed -- CI-runnable the same way test_contract_schema_drift.py and
test_schema_dbml_drift.py are) and asserts that every dimension whose name
matches scripts/_pii_classification.py's PII_CUBEJS_MASK_PATTERNS (the
special-category PII columns H2's fix masks: id_number, date_of_birth,
registration_number, gender) is declared `public: false`. If a future cube
adds one of these columns as a plain, publicly-queryable dimension again,
this test fails CI instead of silently reintroducing H2.
"""

import glob
import os
import re

import pytest
import yaml

from scripts._pii_classification import PII_CUBEJS_MASK_PATTERNS

CUBES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cube", "model", "cubes")
CUBE_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cube", "cube.js")


def _load_all_cube_dimensions():
    """Yields (cube_file, cube_name, dimension_dict) for every dimension in
    every cube/model/cubes/*.yml file (excluding the views/ subdirectory,
    which defines views over cubes, not cubes with their own dimensions)."""
    for path in sorted(glob.glob(os.path.join(CUBES_DIR, "*.yml"))):
        with open(path, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        for cube_def in parsed.get("cubes") or []:
            for dim in cube_def.get("dimensions", []):
                yield os.path.basename(path), cube_def.get("name"), dim


def test_cube_files_exist():
    # Guards against a path typo silently making every other test in this
    # file vacuously pass (zero dimensions found = zero assertions run).
    dimensions = list(_load_all_cube_dimensions())
    assert len(dimensions) > 50, f"expected 50+ dimensions across all cubes, found {len(dimensions)} -- CUBES_DIR wrong?"


@pytest.mark.parametrize(
    "cube_file,cube_name,dim",
    [
        (f, c, d) for f, c, d in _load_all_cube_dimensions()
        if any(pat in d.get("name", "").lower() for pat in PII_CUBEJS_MASK_PATTERNS)
    ],
    ids=lambda v: v.get("name") if isinstance(v, dict) else str(v),
)
def test_special_category_pii_dimension_is_masked(cube_file, cube_name, dim):
    assert dim.get("public") is False, (
        f"{cube_file}: cube '{cube_name}' dimension '{dim.get('name')}' matches a "
        f"PII_CUBEJS_MASK_PATTERNS special-category pattern but is not `public: false` "
        f"-- see H2 in the hardening plan."
    )


def _load_masked_pii_members_from_cube_js():
    """Extracts cube/cube.js's MASKED_PII_MEMBERS set via a targeted regex
    over the JS source (no JS runtime available from Python) -- fragile in
    general, but scoped tightly to this one array literal's declared
    format, and covered by test_masked_pii_members_extraction_sanity below
    so a change to that format fails loudly here instead of silently
    making the cross-check vacuous."""
    with open(CUBE_JS_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    match = re.search(r"MASKED_PII_MEMBERS\s*=\s*new Set\(\[(.*?)\]\)", source, re.DOTALL)
    assert match, "Could not find `const MASKED_PII_MEMBERS = new Set([...])` in cube/cube.js"
    return set(re.findall(r"'([a-zA-Z0-9_.]+)'", match.group(1)))


def test_masked_pii_members_extraction_sanity():
    # Guards the regex extraction above against silently returning an empty
    # set (e.g. if cube.js's array literal format ever changes) -- an empty
    # set would make test_cube_js_masked_members_match_yaml below vacuously
    # pass instead of catching real drift.
    members = _load_masked_pii_members_from_cube_js()
    assert len(members) >= 4, f"expected 4+ masked members extracted from cube.js, got {members}"


def test_cube_js_masked_members_match_yaml():
    # H2's queryRewrite enforcement in cube/cube.js is a hand-maintained
    # list, separate from the `public: false` flags in cube/model/cubes/
    # *.yml -- this cross-checks the two stay in sync (documented in both
    # places as a known gap otherwise: a dimension marked `public: false`
    # in YAML without a matching entry in cube.js's MASKED_PII_MEMBERS would
    # be hidden from the Playground/GraphQL schema but NOT actually blocked
    # from a direct REST query -- exactly the gap this whole fix exists to
    # close).
    yaml_masked = {
        f"{c}.{d['name']}"
        for _f, c, d in _load_all_cube_dimensions()
        if d.get("public") is False
    }
    js_masked = _load_masked_pii_members_from_cube_js()
    assert yaml_masked == js_masked, (
        f"cube/cube.js's MASKED_PII_MEMBERS and the `public: false` dimensions in "
        f"cube/model/cubes/*.yml have drifted apart.\n"
        f"In YAML but not enforced by queryRewrite: {yaml_masked - js_masked}\n"
        f"In queryRewrite but not marked public:false in YAML: {js_masked - yaml_masked}"
    )
