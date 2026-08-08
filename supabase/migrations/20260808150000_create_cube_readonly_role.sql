-- ===============================================================================
-- Least-Privilege Read-Only Role for Cube.js's Own Postgres Data Source
-- ===============================================================================
-- H1 (hardening plan): docker-compose.yml's `cube` service previously connected
-- to Postgres as CUBEJS_DB_USER=postgres -- the superuser -- to compute every
-- semantic-layer aggregation. Cube.js only ever issues SELECT queries against
-- financial/ref (it stores its own pre-aggregation cache in the separate Cube
-- Store service, not back into Postgres), so superuser was never functionally
-- required; it was the same "default to postgres because it's what's in .env"
-- pattern C2 already fixed for the MCP server and scripts/hybrid_rag_retriever.py.
--
-- `cube_readonly` is a direct sibling of mcp_readonly
-- (20260807151500_create_mcp_readonly_role.sql) -- same grants, same RLS
-- carve-out, same NOLOGIN-until-configured pattern -- kept as a *separate* role
-- (not a shared login) so Cube.js's own Postgres connections are distinguishable
-- from the MCP server's / hybrid_rag_retriever's in pg_stat_activity and any
-- future audit logging, per the principle of least-shared-privilege: two
-- unrelated callers should not authenticate as the same database identity just
-- because they happen to need the same grants today.
--
-- statement_timeout is intentionally longer than mcp_readonly's 10s: Cube.js's
-- own queries are real analytical aggregations (GROUP BY across the full table,
-- not point lookups), including materializing the 4 pre_aggregations rollups in
-- cube/model/cubes/*.yml, which legitimately take longer than the ad-hoc,
-- single-purpose queries mcp_readonly's callers issue.
-- ===============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cube_readonly') THEN
        CREATE ROLE cube_readonly NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA financial TO cube_readonly;
GRANT USAGE ON SCHEMA ref TO cube_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA financial TO cube_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ref TO cube_readonly;

-- Cover tables created by future migrations automatically, same reasoning as
-- mcp_readonly's identical grant.
ALTER DEFAULT PRIVILEGES IN SCHEMA financial GRANT SELECT ON TABLES TO cube_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA ref GRANT SELECT ON TABLES TO cube_readonly;

-- Session-level defense in depth, mirroring mcp_readonly's -- see that
-- migration's own comment for why this holds even if application-level
-- guardrails have a gap. 30s statement_timeout (vs. mcp_readonly's 10s) to
-- accommodate genuine full-table aggregation queries; see module comment above.
ALTER ROLE cube_readonly SET default_transaction_read_only = on;
ALTER ROLE cube_readonly SET statement_timeout = '30s';
ALTER ROLE cube_readonly SET idle_in_transaction_session_timeout = '30s';

-- RLS is enabled with no default policy for any non-BYPASSRLS role (see
-- 20260807150000_enable_rls_and_restrict_anon_access.sql) -- without an
-- explicit policy here, cube_readonly would pass every GRANT above and still
-- see zero rows. Same intended access as mcp_readonly: full SELECT on both
-- schemas' current data; RLS is being used for deny-by-default posture, not
-- row-level multi-tenancy.
DO $$
DECLARE
    tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('financial', 'ref')
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS cube_readonly_select ON %I.%I;', tbl.schemaname, tbl.tablename);
        EXECUTE format(
            'CREATE POLICY cube_readonly_select ON %I.%I FOR SELECT TO cube_readonly USING (true);',
            tbl.schemaname, tbl.tablename
        );
    END LOOP;
END $$;
