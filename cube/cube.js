// ============================================================================
// Cube.js Open-Source Semantic Layer Server Configuration
// ============================================================================

const crypto = require('crypto');

// H2 (hardening plan): every special-category-PII dimension in
// cube/model/cubes/*.yml is also marked `public: false` -- but verified
// live (Cube.js v0.35's api-gateway source: `public` is only checked in
// graphql.js, for GraphQL schema generation, never in the REST /load query
// path) that `public: false` alone does NOT block a direct REST query
// against the field; it only hides it from the Playground/GraphQL schema.
// This list plus queryRewrite below is the actual enforcement -- keep it in
// sync with every `public: false` dimension added under cube/model/cubes/
// (tests/test_pii_cube_enforcement.py checks the YAML side of that
// contract; nothing currently cross-checks this JS list against the YAML
// automatically, since Cube.js's own schema isn't introspectable from
// Node.js config-load time the way the Python-side tooling can read the
// YAML directly -- a known gap, not a silent one).
//
// Blocked for EVERY caller regardless of role -- there is no legitimate
// analytics use case for querying raw special-category PII through the
// semantic layer API at all, unlike AML_RESTRICTED_MEMBERS below, which is
// real, legitimate analytics data restricted to a privileged role, not
// blocked outright.
const MASKED_PII_MEMBERS = new Set([
  'party_individual.date_of_birth',
  'party_individual.gender',
  'party_organization.registration_number',
  'party_identification.id_number',
]);

// H1 (hardening plan): row-level/tenant authorization via queryRewrite.
// AML risk classification is real compliance-sensitive data (financial
// crime / sanctions risk profiling) -- a legitimate BI need for a
// privileged/compliance-analyst caller, but not something every caller of
// the semantic layer should see. Restricted to the 'privileged' role
// (CUBEJS_API_SECRET below); the 'restricted' role (CUBEJS_API_SECRET_RESTRICTED)
// gets every other cube/measure/dimension in the model, just not these.
const AML_RESTRICTED_MEMBERS = new Set([
  'party_role_customer.aml_risk_rating',
  'party_role_customer.high_aml_risk_count',
  'party_role_customer.high_aml_risk_ratio',
  'ref_country.is_high_risk_aml',
  'ref_country.high_risk_aml_country_count',
  'ref_nace_industry.risk_level',
  'ref_nace_industry.high_risk_industry_count',
]);

// Recursively collects every member name referenced in a normalized query's
// measures/dimensions/timeDimensions/filters -- filters can nest arbitrarily
// via `and`/`or` groups, so a flat `query.filters.map(f => f.member)` would
// miss a masked field hidden inside a nested boolean group. H1: originally
// written for H2's PII masking, where every masked field is a dimension, so
// `query.measures` was never collected -- a real gap this caught live: an
// AML-restricted *measure* (e.g. party_role_customer.high_aml_risk_count)
// queried via `{"measures": [...]}` alone sailed straight through
// queryRewrite's forbidden-member check, since it was never in the
// `members` set being checked against. Fixed by collecting `query.measures`
// too; tests/test_pii_cube_enforcement.py's dimension-only PII members are
// unaffected by this addition.
function collectReferencedMembers(query) {
  const members = new Set();
  (query.measures || []).forEach((m) => members.add(m));
  (query.dimensions || []).forEach((d) => members.add(d));
  (query.timeDimensions || []).forEach((td) => td && td.dimension && members.add(td.dimension));

  function walkFilters(filters) {
    (filters || []).forEach((f) => {
      if (!f) return;
      if (f.member || f.dimension) members.add(f.member || f.dimension);
      if (f.and) walkFilters(f.and);
      if (f.or) walkFilters(f.or);
    });
  }
  walkFilters(query.filters);

  return members;
}

// Constant-time string comparison -- Node's crypto.timingSafeEqual throws if
// the two buffers differ in length (rather than returning false), so length
// is checked first. That leaks the *length* of the expected secret via
// timing, not its content, which is the same tradeoff every standard
// constant-time-compare helper (Python's hmac.compare_digest included, used
// by mcp_server/financial_data_mcp_server.py's BearerAuthMiddleware) makes;
// it is not the class of leak this function exists to close.
function timingSafeEqualString(a, b) {
  const bufA = Buffer.from(String(a), 'utf8');
  const bufB = Buffer.from(String(b), 'utf8');
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

module.exports = {
  dbType: 'postgres',
  schemaPath: 'model/cubes',

  queryRewrite: (query, { securityContext }) => {
    const referenced = collectReferencedMembers(query);

    const forbiddenPii = [...referenced].filter((m) => MASKED_PII_MEMBERS.has(m));
    if (forbiddenPii.length > 0) {
      // Cube.js surfaces a queryRewrite throw as a client-facing error
      // response (verified live: a real REST /load call against a masked
      // dimension now returns an error body, not query results), not a
      // silent 500 or a swallowed exception.
      throw new Error(
        `Forbidden: querying special-category PII dimension(s) [${forbiddenPii.join(', ')}] `
        + 'is not permitted through the semantic layer API.'
      );
    }

    // H1: row-level/tenant authorization. securityContext is whatever
    // checkAuth below set on req.securityContext for the token this
    // request authenticated with -- {} (falsy role) for a caller that
    // somehow got here without going through checkAuth's role assignment
    // fails closed to "not privileged", not "not restricted".
    const role = securityContext && securityContext.role;
    if (role !== 'privileged') {
      const forbiddenAml = [...referenced].filter((m) => AML_RESTRICTED_MEMBERS.has(m));
      if (forbiddenAml.length > 0) {
        throw new Error(
          `Forbidden: querying AML-risk-restricted member(s) [${forbiddenAml.join(', ')}] `
          + `requires the privileged API role (current role: ${role || 'none'}).`
        );
      }
    }

    return query;
  },

  checkAuth: (req, auth) => {
    // Two static bearer tokens, each mapped to a real role -- replaces the
    // original single-secret check (itself a fix for a prior unconditional
    // `return true`) that authenticated every request into one flat,
    // undifferentiated access level (H1: "one secret grants every cube").
    // CUBEJS_API_SECRET is the privileged role (full access, including
    // AML_RESTRICTED_MEMBERS above); CUBEJS_API_SECRET_RESTRICTED is a
    // second, real, independently-issued token for a caller that should
    // see general BIAN/FIBO metrics but not AML risk classifications.
    const privilegedSecret = process.env.CUBEJS_API_SECRET;
    const restrictedSecret = process.env.CUBEJS_API_SECRET_RESTRICTED;
    if (!privilegedSecret) {
      throw new Error(
        'CUBEJS_API_SECRET is not set on the server; refusing to authenticate any request.'
      );
    }
    if (!restrictedSecret) {
      throw new Error(
        'CUBEJS_API_SECRET_RESTRICTED is not set on the server; refusing to authenticate any '
        + 'request. (H1: a second, real role is required so "privileged" is an actual boundary, '
        + 'not the only role that exists.)'
      );
    }

    const authHeader = req.headers && req.headers.authorization;
    const token = authHeader && authHeader.startsWith('Bearer ')
      ? authHeader.slice(7)
      : authHeader;

    if (!token) {
      throw new Error('Unauthorized: missing Cube.js API token.');
    }

    // Both comparisons always run (rather than short-circuiting on the
    // first match) so which branch matched isn't observable via timing
    // either, on top of each individual comparison being constant-time.
    const matchesPrivileged = timingSafeEqualString(token, privilegedSecret);
    const matchesRestricted = timingSafeEqualString(token, restrictedSecret);

    if (matchesPrivileged) {
      req.securityContext = { role: 'privileged' };
    } else if (matchesRestricted) {
      req.securityContext = { role: 'restricted' };
    } else {
      throw new Error('Unauthorized: invalid Cube.js API token.');
    }
  }
};
