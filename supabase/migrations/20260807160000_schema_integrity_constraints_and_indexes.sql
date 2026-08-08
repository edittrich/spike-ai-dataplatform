-- ============================================================================
-- Supabase Migration: Schema Integrity Constraints & Missing FK Indexes
-- Migration Name: 20260807160000_schema_integrity_constraints_and_indexes.sql
-- Description: Closes the schema-integrity gaps identified in the hardening
--              plan's Q13 finding:
--                1. No table had a temporal sanity CHECK on its SCD2 header.
--                2. No business key was ever enforced unique, even among the
--                   "currently active" rows -- so nothing in the schema
--                   actually prevented two simultaneously-active versions of
--                   the same party/account/agreement/etc. This is enforced
--                   here via a GiST exclusion constraint on
--                   (business_key, [md_valid_from_utc, md_valid_to_utc)) --
--                   stronger than a plain UNIQUE, since it also rejects any
--                   temporal *overlap* between two versions of the same key,
--                   not just two that are simultaneously flagged active.
--                   Note this is an integrity *guarantee*, not an
--                   implementation of SCD2 close-and-insert logic -- see D3
--                   in the hardening plan and docs/ARCHITECTURE.md's Known
--                   Issues for why that's tracked separately.
--                3. 14 foreign-key columns (mostly ref.* lookups) had no
--                   index, forcing a sequential scan on every referencing
--                   table for a DELETE/UPDATE against the referenced row.
--                4. The HNSW vector index had no query-time recall tuning,
--                   and entity_type/metadata had no filter indexes despite
--                   both being natural predicates in hybrid_rag_retriever.py.
--              All additions were checked against the live, already-loaded
--              database before being written here -- zero existing rows
--              violate any of these constraints (verified: no duplicate
--              active business keys, no temporal overlaps, no inverted
--              valid_from/valid_to ranges).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. SCD2 temporal sanity: md_valid_from_utc must precede md_valid_to_utc.
-- ----------------------------------------------------------------------------
ALTER TABLE financial.party                     ADD CONSTRAINT chk_party_temporal_order                     CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.party_individual           ADD CONSTRAINT chk_party_individual_temporal_order           CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.party_organization         ADD CONSTRAINT chk_party_organization_temporal_order         CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.party_role_customer        ADD CONSTRAINT chk_party_role_customer_temporal_order        CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.party_address              ADD CONSTRAINT chk_party_address_temporal_order              CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.party_identification       ADD CONSTRAINT chk_party_identification_temporal_order       CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.deposit_account            ADD CONSTRAINT chk_deposit_account_temporal_order            CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.deposit_balance            ADD CONSTRAINT chk_deposit_balance_temporal_order            CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.deposit_transaction        ADD CONSTRAINT chk_deposit_transaction_temporal_order        CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.deposit_interest_term      ADD CONSTRAINT chk_deposit_interest_term_temporal_order      CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.deposit_overdraft_facility ADD CONSTRAINT chk_deposit_overdraft_facility_temporal_order CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.loan_application           ADD CONSTRAINT chk_loan_application_temporal_order           CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.loan_agreement             ADD CONSTRAINT chk_loan_agreement_temporal_order             CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.loan_repayment_schedule    ADD CONSTRAINT chk_loan_repayment_schedule_temporal_order    CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.loan_disbursement          ADD CONSTRAINT chk_loan_disbursement_temporal_order          CHECK (md_valid_from_utc < md_valid_to_utc);
ALTER TABLE financial.loan_collateral            ADD CONSTRAINT chk_loan_collateral_temporal_order            CHECK (md_valid_from_utc < md_valid_to_utc);

-- ----------------------------------------------------------------------------
-- 2. Business-key temporal-overlap exclusion constraints (the 7 tables with a
--    documented "Business key:" column -- see the COMMENT ON COLUMN entries
--    in the base migration). Requires btree_gist for the `=` operator class
--    on varchar/uuid inside a GiST index alongside the range overlap check.
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE financial.party ADD CONSTRAINT excl_party_bk_temporal_overlap
    EXCLUDE USING gist (party_bk WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.party_role_customer ADD CONSTRAINT excl_customer_number_temporal_overlap
    EXCLUDE USING gist (customer_number WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.deposit_account ADD CONSTRAINT excl_account_number_temporal_overlap
    EXCLUDE USING gist (account_number WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.deposit_transaction ADD CONSTRAINT excl_transaction_reference_temporal_overlap
    EXCLUDE USING gist (transaction_reference WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.loan_application ADD CONSTRAINT excl_application_number_temporal_overlap
    EXCLUDE USING gist (application_number WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.loan_agreement ADD CONSTRAINT excl_agreement_number_temporal_overlap
    EXCLUDE USING gist (agreement_number WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

ALTER TABLE financial.loan_disbursement ADD CONSTRAINT excl_disbursement_reference_temporal_overlap
    EXCLUDE USING gist (disbursement_reference WITH =, tstzrange(md_valid_from_utc, md_valid_to_utc) WITH &&);

COMMENT ON CONSTRAINT excl_party_bk_temporal_overlap ON financial.party IS
    'SCD2 integrity guarantee: no two rows sharing this business key may have overlapping validity ranges -- prevents two simultaneously-active versions. Does not itself implement SCD2 close-and-insert logic; see D3 in the hardening plan.';

-- ----------------------------------------------------------------------------
-- 3. Missing foreign-key indexes -- every FK column below had no index,
--    forcing a sequential scan of the referencing table on every UPDATE or
--    DELETE against the referenced ref.*/financial.* row.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_party_individual_citizenship_country ON financial.party_individual(citizenship_country_code);
CREATE INDEX IF NOT EXISTS idx_party_individual_tax_residence_country ON financial.party_individual(tax_residence_country_code);
CREATE INDEX IF NOT EXISTS idx_party_organization_incorporation_country ON financial.party_organization(incorporation_country_code);
CREATE INDEX IF NOT EXISTS idx_party_organization_nace_code ON financial.party_organization(nace_code);
CREATE INDEX IF NOT EXISTS idx_party_address_country_code ON financial.party_address(country_code);
CREATE INDEX IF NOT EXISTS idx_party_identification_issuing_country ON financial.party_identification(issuing_country_code);
CREATE INDEX IF NOT EXISTS idx_deposit_account_currency_code ON financial.deposit_account(currency_code);
CREATE INDEX IF NOT EXISTS idx_deposit_balance_currency_code ON financial.deposit_balance(currency_code);
CREATE INDEX IF NOT EXISTS idx_deposit_transaction_currency_code ON financial.deposit_transaction(currency_code);
CREATE INDEX IF NOT EXISTS idx_loan_application_currency_code ON financial.loan_application(currency_code);
CREATE INDEX IF NOT EXISTS idx_loan_agreement_currency_code ON financial.loan_agreement(currency_code);
CREATE INDEX IF NOT EXISTS idx_loan_agreement_application_id ON financial.loan_agreement(loan_application_id);
CREATE INDEX IF NOT EXISTS idx_loan_disbursement_currency_code ON financial.loan_disbursement(currency_code);
CREATE INDEX IF NOT EXISTS idx_loan_collateral_currency_code ON financial.loan_collateral(currency_code);

-- ----------------------------------------------------------------------------
-- 4. pgvector: filter indexes for the two natural predicates
--    hybrid_rag_retriever.py filters on (entity_type equality, metadata JSONB
--    containment). Query-time HNSW recall tuning (`hnsw.ef_search`) is
--    deliberately *not* set here via ALTER ROLE -- it's a per-session GUC
--    defined by the vector extension's loaded library, so ALTER ROLE ... SET
--    can't reliably reference it outside a session that has already used the
--    extension; callers that need higher recall should issue
--    `SET LOCAL hnsw.ef_search = 100;` at the start of their own session/
--    transaction instead (e.g. in query_pg's connection setup), which is the
--    documented, reliable way to set it either way.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_entity_type ON financial.entity_embeddings(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_metadata_gin ON financial.entity_embeddings USING gin(metadata);
