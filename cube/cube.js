// ============================================================================
// Cube.js Open-Source Semantic Layer Server Configuration
// ============================================================================

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
const MASKED_PII_MEMBERS = new Set([
  'party_individual.date_of_birth',
  'party_individual.gender',
  'party_organization.registration_number',
  'party_identification.id_number',
]);

// Recursively collects every member name referenced in a normalized query's
// dimensions/timeDimensions/filters -- filters can nest arbitrarily via
// `and`/`or` groups, so a flat `query.filters.map(f => f.member)` would miss
// a masked field hidden inside a nested boolean group.
function collectReferencedMembers(query) {
  const members = new Set();
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

module.exports = {
  dbType: 'postgres',
  schemaPath: 'model/cubes',

  queryRewrite: (query) => {
    const referenced = collectReferencedMembers(query);
    const forbidden = [...referenced].filter((m) => MASKED_PII_MEMBERS.has(m));
    if (forbidden.length > 0) {
      // Cube.js surfaces a queryRewrite throw as a client-facing error
      // response (verified live: a real REST /load call against a masked
      // dimension now returns an error body, not query results), not a
      // silent 500 or a swallowed exception.
      throw new Error(
        `Forbidden: querying special-category PII dimension(s) [${forbidden.join(', ')}] `
        + 'is not permitted through the semantic layer API.'
      );
    }
    return query;
  },

  checkAuth: (req, auth) => {
    // Static bearer-token check against CUBEJS_API_SECRET. This replaces a
    // previous unconditional `return true` that authenticated every request
    // regardless of the configured secret (see docker-compose.yml's
    // CUBEJS_API_SECRET), leaving the semantic layer fully open on the
    // network. Cube.js expects checkAuth to throw to reject a request.
    const expectedSecret = process.env.CUBEJS_API_SECRET;
    if (!expectedSecret) {
      throw new Error(
        'CUBEJS_API_SECRET is not set on the server; refusing to authenticate any request.'
      );
    }

    const authHeader = req.headers && req.headers.authorization;
    const token = authHeader && authHeader.startsWith('Bearer ')
      ? authHeader.slice(7)
      : authHeader;

    if (!token || token !== expectedSecret) {
      throw new Error('Unauthorized: missing or invalid Cube.js API token.');
    }

    req.securityContext = {};
  }
};
