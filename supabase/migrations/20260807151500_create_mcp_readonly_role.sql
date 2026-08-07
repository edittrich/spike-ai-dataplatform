-- ===============================================================================
-- Least-Privilege Read-Only Role for the MCP Server & Hybrid RAG Retriever
-- ===============================================================================
-- mcp_server/financial_data_mcp_server.py and scripts/hybrid_rag_retriever.py
-- previously defaulted POSTGRES_USER to `postgres` -- a superuser -- and relied
-- entirely on scripts/ai_safety_guardrails.py's keyword blocklist plus
-- `conn.set_session(readonly=True)` to stop mutation. Verified live: neither of
-- those stops `SELECT pg_read_file('/etc/passwd')`, `SELECT * FROM pg_shadow`, or
-- `SELECT 1; COPY (SELECT 1) TO PROGRAM 'id'` -- all pass the guardrail's keyword
-- scan, and a read-only *transaction* still permits calling superuser-only
-- functions and (for COPY ... TO PROGRAM specifically) executing an OS command.
--
-- `mcp_readonly` is a non-superuser role restricted to SELECT on financial + ref.
-- As a non-superuser it cannot call pg_read_file/pg_ls_dir/lo_import/lo_export,
-- cannot COPY TO/FROM PROGRAM, and cannot see rows or tables outside those two
-- schemas -- the privilege boundary is enforced by Postgres itself, not by a
-- regex, so it holds even if the guardrail's keyword list has a gap (which it
-- did -- see the same commit's fix to ai_safety_guardrails.py for the SQL/Cypher
-- keyword-list and identifier-tokenizer issues).
--
-- The role is created here with NOLOGIN and no usable password -- it cannot
-- authenticate until scripts/configure_readonly_role.py runs, which sets its
-- password from the MCP_PG_READONLY_PASSWORD env var (never hardcoded in a
-- checked-in file, per this repo's secrets convention). Re-running this
-- migration or the configure script is safe (idempotent).
-- ===============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_readonly') THEN
        CREATE ROLE mcp_readonly NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA financial TO mcp_readonly;
GRANT USAGE ON SCHEMA ref TO mcp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA financial TO mcp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA ref TO mcp_readonly;

-- Cover tables created by future migrations automatically, closing the gap that
-- left financial.entity_embeddings (added by the pgvector migration, which predates
-- this one) with no grants to any application role at all.
ALTER DEFAULT PRIVILEGES IN SCHEMA financial GRANT SELECT ON TABLES TO mcp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA ref GRANT SELECT ON TABLES TO mcp_readonly;

-- Session-level defense in depth: every connection authenticating as this role
-- gets a read-only transaction mode and bounded statement/idle timeouts, even
-- before the application code sets them explicitly.
ALTER ROLE mcp_readonly SET default_transaction_read_only = on;
ALTER ROLE mcp_readonly SET statement_timeout = '10s';
ALTER ROLE mcp_readonly SET idle_in_transaction_session_timeout = '30s';

-- The RLS migration (20260807150000_enable_rls_and_restrict_anon_access.sql)
-- enabled RLS on every financial/ref table with zero policies for anon/
-- authenticated -- deliberately, so those two get nothing. RLS applies to any
-- non-BYPASSRLS role, `mcp_readonly` included, so without a policy of its own
-- here it would pass every GRANT check above and still see zero rows. This is
-- the intended access for the read-only application role: full SELECT on both
-- schemas' current data (RLS is not being used here for row-level
-- multi-tenancy, just to keep the default posture deny-by-default).
DO $$
DECLARE
    tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('financial', 'ref')
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS mcp_readonly_select ON %I.%I;', tbl.schemaname, tbl.tablename);
        EXECUTE format(
            'CREATE POLICY mcp_readonly_select ON %I.%I FOR SELECT TO mcp_readonly USING (true);',
            tbl.schemaname, tbl.tablename
        );
    END LOOP;
END $$;
