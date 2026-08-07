-- ===============================================================================
-- Row-Level Security & Least-Privilege Grants for financial/ref schemas
-- ===============================================================================
-- Prior to this migration, `financial` and `ref` were published through PostgREST
-- (supabase/config.toml's [api].schemas) with:
--   GRANT SELECT ON ALL TABLES IN SCHEMA financial TO anon;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA financial TO authenticated;
-- and NO Row-Level Security anywhere -- so the anonymous Supabase API key (meant to be
-- shipped to browsers) could read every customer's PII, KYC/AML status, balances, and
-- loan data over plain HTTP, and any self-registered `authenticated` user could write to
-- any of it. Verified live: `GET /rest/v1/party_individual?select=first_name,last_name,
-- date_of_birth` with only the public anon key returned real customer rows.
--
-- This migration enables RLS (deny-by-default: no policies means no rows are visible to
-- anon/authenticated) and revokes the blanket grants. `postgres` and `service_role` are
-- unaffected -- both carry BYPASSRLS, and `postgres` is the platform's own admin
-- connection used by every pipeline script and by Cube.js.
--
-- `financial`/`ref` are also removed from supabase/config.toml's PostgREST-exposed
-- schemas in the same change -- nothing in the platform uses PostgREST (the MCP server
-- and pipeline scripts connect over the Postgres wire protocol on :54322 directly), so
-- this closes the HTTP surface entirely rather than relying on RLS alone.
-- ===============================================================================

-- ---------------------------------------------------------------------------
-- 1. Enable Row-Level Security (deny-by-default) on every financial + ref table
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname IN ('financial', 'ref')
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY;', tbl.schemaname, tbl.tablename);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Revoke the anon/authenticated grants that made RLS's prior absence
--    exploitable. (postgres and service_role are untouched -- see rationale above.)
-- ---------------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA financial FROM anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA ref FROM anon, authenticated;
REVOKE USAGE ON SCHEMA financial FROM anon, authenticated;
REVOKE USAGE ON SCHEMA ref FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. `ref` (currencies, countries, NACE industry codes) is public reference data,
--    not sensitive like `financial` -- it's safe to make readable. Re-grant USAGE +
--    SELECT to `authenticated` only (not `anon`), backed by an explicit permissive
--    RLS policy, so this is a deliberate choice rather than an oversight.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA ref TO authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA ref TO authenticated;

DO $$
DECLARE
    tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'ref'
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS ref_select_authenticated ON ref.%I;', tbl.tablename);
        EXECUTE format(
            'CREATE POLICY ref_select_authenticated ON ref.%I FOR SELECT TO authenticated USING (true);',
            tbl.tablename
        );
    END LOOP;
END $$;

-- `financial` intentionally gets no policies for anon/authenticated: RLS is enabled
-- with zero policies, so zero rows are visible to either role. Any future
-- application-level access (e.g. a real authenticated customer portal) must add
-- narrow, explicit policies here rather than relying on the removed blanket grants.
