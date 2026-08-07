// ============================================================================
// Cube.js Open-Source Semantic Layer Server Configuration
// ============================================================================

module.exports = {
  dbType: 'postgres',
  schemaPath: 'model/cubes',

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
