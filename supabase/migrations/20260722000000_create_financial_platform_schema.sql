-- ============================================================================
-- Supabase Migration: AI-Enabled Financial Data Platform PoC
-- Migration Name: 20260722000000_create_financial_platform_schema.sql
-- Description: Creates schemas, reference tables, operational tables with 
--              SCD Type 2 metadata, foreign keys, triggers, composite indexes,
--              and full PostgreSQL native table and column comments for cataloging.
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create distinct schemas for reference data and financial operational domain
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS financial;

-- Grant schema permissions for Supabase roles
GRANT USAGE ON SCHEMA ref TO postgres, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA financial TO postgres, anon, authenticated, service_role;

-- ----------------------------------------------------------------------------
-- AUTOMATED METADATA TIMESTAMP TRIGGER FUNCTION
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION financial.fn_update_md_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.md_updated_at_utc = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- SECTION 1: REFERENCE DATA PRODUCT (ref)
-- ----------------------------------------------------------------------------

CREATE TABLE ref.ref_currency (
    currency_code VARCHAR(3) PRIMARY KEY,
    currency_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10),
    decimal_places INTEGER NOT NULL DEFAULT 2,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ref.ref_currency IS 'ISO 4217 currency reference table';
COMMENT ON COLUMN ref.ref_currency.currency_code IS 'ISO 4217 3-letter currency code (e.g., USD, EUR)';
COMMENT ON COLUMN ref.ref_currency.currency_name IS 'Official currency name';
COMMENT ON COLUMN ref.ref_currency.symbol IS 'Currency symbol representation';
COMMENT ON COLUMN ref.ref_currency.decimal_places IS 'Standard decimal precision';
COMMENT ON COLUMN ref.ref_currency.is_active IS 'Active currency status indicator';
COMMENT ON COLUMN ref.ref_currency.created_at IS 'Record creation timestamp UTC';

CREATE TABLE ref.ref_country (
    country_code VARCHAR(2) PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL,
    iso_alpha3 VARCHAR(3) NOT NULL,
    iso_numeric VARCHAR(3) NOT NULL,
    is_high_risk_aml BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ref.ref_country IS 'ISO 3166-1 country reference table';
COMMENT ON COLUMN ref.ref_country.country_code IS 'ISO 3166-1 alpha-2 country code (e.g., US, DE)';
COMMENT ON COLUMN ref.ref_country.country_name IS 'Official country name';
COMMENT ON COLUMN ref.ref_country.iso_alpha3 IS 'ISO 3166-1 alpha-3 country code';
COMMENT ON COLUMN ref.ref_country.iso_numeric IS 'ISO numeric country code';
COMMENT ON COLUMN ref.ref_country.is_high_risk_aml IS 'AML high-risk country indicator';
COMMENT ON COLUMN ref.ref_country.created_at IS 'Record creation timestamp UTC';

CREATE TABLE ref.ref_nace_industry (
    nace_code VARCHAR(10) PRIMARY KEY,
    nace_section VARCHAR(1) NOT NULL,
    nace_title VARCHAR(255) NOT NULL,
    risk_level VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ref.ref_nace_industry IS 'NACE Rev. 2 industry classification reference table';
COMMENT ON COLUMN ref.ref_nace_industry.nace_code IS 'NACE Rev. 2 industry sector code';
COMMENT ON COLUMN ref.ref_nace_industry.nace_section IS 'Main section classification letter';
COMMENT ON COLUMN ref.ref_nace_industry.nace_title IS 'Industry sector description title';
COMMENT ON COLUMN ref.ref_nace_industry.risk_level IS 'Industry risk rating (LOW, MEDIUM, HIGH)';
COMMENT ON COLUMN ref.ref_nace_industry.created_at IS 'Record creation timestamp UTC';

GRANT SELECT ON ALL TABLES IN SCHEMA ref TO anon, authenticated, service_role;

-- ----------------------------------------------------------------------------
-- SECTION 2: PARTY DATA PRODUCT (party)
-- ----------------------------------------------------------------------------

CREATE TABLE financial.party (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_bk VARCHAR(50) NOT NULL,
    party_type VARCHAR(20) NOT NULL CHECK (party_type IN ('INDIVIDUAL', 'ORGANIZATION')),
    status_code VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN ('ACTIVE', 'INACTIVE', 'SUSPENDED'))
);

COMMENT ON TABLE financial.party IS 'Master Party entity supertype (BIAN Party Domain)';
COMMENT ON COLUMN financial.party.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party.party_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party.party_bk IS 'Business key: Enterprise party master reference';
COMMENT ON COLUMN financial.party.party_type IS 'Party type discriminator: INDIVIDUAL or ORGANIZATION';
COMMENT ON COLUMN financial.party.status_code IS 'Party status (ACTIVE, INACTIVE, SUSPENDED)';

CREATE TRIGGER trg_party_updated_at
BEFORE UPDATE ON financial.party
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.party_individual (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_individual_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_id UUID NOT NULL REFERENCES financial.party(party_id) ON DELETE CASCADE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20),
    citizenship_country_code VARCHAR(2) NOT NULL REFERENCES ref.ref_country(country_code),
    tax_residence_country_code VARCHAR(2) NOT NULL REFERENCES ref.ref_country(country_code)
);

COMMENT ON TABLE financial.party_individual IS 'Individual natural person party subtype';
COMMENT ON COLUMN financial.party_individual.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party_individual.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party_individual.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party_individual.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party_individual.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party_individual.party_individual_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party_individual.party_id IS 'Foreign key to master party entity';
COMMENT ON COLUMN financial.party_individual.first_name IS 'First name of individual';
COMMENT ON COLUMN financial.party_individual.last_name IS 'Last name of individual';
COMMENT ON COLUMN financial.party_individual.date_of_birth IS 'Date of birth';
COMMENT ON COLUMN financial.party_individual.gender IS 'Gender identity';
COMMENT ON COLUMN financial.party_individual.citizenship_country_code IS 'Primary citizenship country code';
COMMENT ON COLUMN financial.party_individual.tax_residence_country_code IS 'Primary tax residence country code';

CREATE TRIGGER trg_party_individual_updated_at
BEFORE UPDATE ON financial.party_individual
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.party_organization (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_organization_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_id UUID NOT NULL REFERENCES financial.party(party_id) ON DELETE CASCADE,
    legal_name VARCHAR(255) NOT NULL,
    trade_name VARCHAR(255),
    registration_number VARCHAR(50) NOT NULL,
    incorporation_date DATE NOT NULL,
    incorporation_country_code VARCHAR(2) NOT NULL REFERENCES ref.ref_country(country_code),
    nace_code VARCHAR(10) NOT NULL REFERENCES ref.ref_nace_industry(nace_code),
    legal_form VARCHAR(50) NOT NULL
);

COMMENT ON TABLE financial.party_organization IS 'Organization legal entity party subtype';
COMMENT ON COLUMN financial.party_organization.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party_organization.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party_organization.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party_organization.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party_organization.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party_organization.party_organization_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party_organization.party_id IS 'Foreign key to master party entity';
COMMENT ON COLUMN financial.party_organization.legal_name IS 'Registered corporate legal name';
COMMENT ON COLUMN financial.party_organization.trade_name IS 'Commercial DBA trade name';
COMMENT ON COLUMN financial.party_organization.registration_number IS 'Corporate commercial register tax ID';
COMMENT ON COLUMN financial.party_organization.incorporation_date IS 'Date of corporate incorporation';
COMMENT ON COLUMN financial.party_organization.incorporation_country_code IS 'Country of incorporation';
COMMENT ON COLUMN financial.party_organization.nace_code IS 'NACE Rev. 2 industry code';
COMMENT ON COLUMN financial.party_organization.legal_form IS 'Legal corporate form (LLC, AG, Corp)';

CREATE TRIGGER trg_party_organization_updated_at
BEFORE UPDATE ON financial.party_organization
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.party_role_customer (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_role_customer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_number VARCHAR(50) NOT NULL,
    party_id UUID NOT NULL REFERENCES financial.party(party_id) ON DELETE CASCADE,
    customer_segment VARCHAR(30) NOT NULL CHECK (customer_segment IN ('RETAIL', 'SME', 'CORPORATE', 'WEALTH')),
    onboarding_date DATE NOT NULL,
    kyc_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (kyc_status IN ('VERIFIED', 'PENDING', 'EXPIRED')),
    kyc_last_review_date DATE,
    aml_risk_rating VARCHAR(20) NOT NULL DEFAULT 'LOW' CHECK (aml_risk_rating IN ('LOW', 'MEDIUM', 'HIGH'))
);

COMMENT ON TABLE financial.party_role_customer IS 'Customer role context assigned to a party';
COMMENT ON COLUMN financial.party_role_customer.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party_role_customer.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party_role_customer.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party_role_customer.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party_role_customer.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party_role_customer.party_role_customer_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party_role_customer.customer_number IS 'Business key: Customer account reference number';
COMMENT ON COLUMN financial.party_role_customer.party_id IS 'Foreign key to master party entity';
COMMENT ON COLUMN financial.party_role_customer.customer_segment IS 'Customer segment (RETAIL, SME, CORPORATE, WEALTH)';
COMMENT ON COLUMN financial.party_role_customer.onboarding_date IS 'Date customer was onboarded';
COMMENT ON COLUMN financial.party_role_customer.kyc_status IS 'KYC verification status (VERIFIED, PENDING, EXPIRED)';
COMMENT ON COLUMN financial.party_role_customer.kyc_last_review_date IS 'Date of last KYC review';
COMMENT ON COLUMN financial.party_role_customer.aml_risk_rating IS 'AML risk rating (LOW, MEDIUM, HIGH)';

CREATE TRIGGER trg_party_role_customer_updated_at
BEFORE UPDATE ON financial.party_role_customer
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.party_address (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_address_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_id UUID NOT NULL REFERENCES financial.party(party_id) ON DELETE CASCADE,
    address_type VARCHAR(30) NOT NULL CHECK (address_type IN ('RESIDENTIAL', 'REGISTERED', 'MAILING')),
    street_address VARCHAR(255) NOT NULL,
    building_number VARCHAR(20),
    city VARCHAR(100) NOT NULL,
    postal_code VARCHAR(20) NOT NULL,
    country_code VARCHAR(2) NOT NULL REFERENCES ref.ref_country(country_code),
    is_primary BOOLEAN NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE financial.party_address IS 'Physical and registered address details for parties';
COMMENT ON COLUMN financial.party_address.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party_address.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party_address.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party_address.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party_address.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party_address.party_address_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party_address.party_id IS 'Foreign key to master party entity';
COMMENT ON COLUMN financial.party_address.address_type IS 'Address classification (RESIDENTIAL, REGISTERED, MAILING)';
COMMENT ON COLUMN financial.party_address.street_address IS 'Street name and address details';
COMMENT ON COLUMN financial.party_address.building_number IS 'House / building number';
COMMENT ON COLUMN financial.party_address.city IS 'City name';
COMMENT ON COLUMN financial.party_address.postal_code IS 'Postal / ZIP code';
COMMENT ON COLUMN financial.party_address.country_code IS 'Country reference code';
COMMENT ON COLUMN financial.party_address.is_primary IS 'Primary address indicator';

CREATE TRIGGER trg_party_address_updated_at
BEFORE UPDATE ON financial.party_address
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.party_identification (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    party_identification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    party_id UUID NOT NULL REFERENCES financial.party(party_id) ON DELETE CASCADE,
    id_type VARCHAR(30) NOT NULL CHECK (id_type IN ('PASSPORT', 'NATIONAL_ID', 'TAX_ID', 'LEI')),
    id_number VARCHAR(100) NOT NULL,
    issuing_country_code VARCHAR(2) NOT NULL REFERENCES ref.ref_country(country_code),
    issue_date DATE NOT NULL,
    expiry_date DATE,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'VERIFIED' CHECK (verification_status IN ('VERIFIED', 'UNVERIFIED'))
);

COMMENT ON TABLE financial.party_identification IS 'Official identification and tax documents for parties';
COMMENT ON COLUMN financial.party_identification.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.party_identification.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.party_identification.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.party_identification.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.party_identification.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.party_identification.party_identification_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.party_identification.party_id IS 'Foreign key to master party entity';
COMMENT ON COLUMN financial.party_identification.id_type IS 'Identification document type (PASSPORT, NATIONAL_ID, TAX_ID, LEI)';
COMMENT ON COLUMN financial.party_identification.id_number IS 'Official document identification number';
COMMENT ON COLUMN financial.party_identification.issuing_country_code IS 'Issuing country code';
COMMENT ON COLUMN financial.party_identification.issue_date IS 'Document issue date';
COMMENT ON COLUMN financial.party_identification.expiry_date IS 'Document expiration date';
COMMENT ON COLUMN financial.party_identification.verification_status IS 'Verification status (VERIFIED, UNVERIFIED)';

CREATE TRIGGER trg_party_identification_updated_at
BEFORE UPDATE ON financial.party_identification
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

-- ----------------------------------------------------------------------------
-- SECTION 3: DEPOSIT DATA PRODUCT (deposit)
-- ----------------------------------------------------------------------------

CREATE TABLE financial.deposit_account (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    deposit_account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_number VARCHAR(50) NOT NULL,
    customer_id UUID NOT NULL REFERENCES financial.party_role_customer(party_role_customer_id),
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    account_type VARCHAR(30) NOT NULL CHECK (account_type IN ('SAVINGS', 'CHECKING', 'TERM_DEPOSIT')),
    account_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE', 'DORMANT', 'FROZEN', 'CLOSED')),
    opened_date DATE NOT NULL,
    closed_date DATE
);

COMMENT ON TABLE financial.deposit_account IS 'Deposit account core contract entity (BIAN Deposit Account)';
COMMENT ON COLUMN financial.deposit_account.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.deposit_account.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.deposit_account.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.deposit_account.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.deposit_account.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.deposit_account.deposit_account_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.deposit_account.account_number IS 'Business key: IBAN / Deposit account number';
COMMENT ON COLUMN financial.deposit_account.customer_id IS 'Customer relationship owner ID';
COMMENT ON COLUMN financial.deposit_account.currency_code IS 'Base account currency';
COMMENT ON COLUMN financial.deposit_account.account_type IS 'Account type (SAVINGS, CHECKING, TERM_DEPOSIT)';
COMMENT ON COLUMN financial.deposit_account.account_status IS 'Account status (ACTIVE, DORMANT, FROZEN, CLOSED)';
COMMENT ON COLUMN financial.deposit_account.opened_date IS 'Account opening date';
COMMENT ON COLUMN financial.deposit_account.closed_date IS 'Account closing date';

CREATE TRIGGER trg_deposit_account_updated_at
BEFORE UPDATE ON financial.deposit_account
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.deposit_balance (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    deposit_balance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deposit_account_id UUID NOT NULL REFERENCES financial.deposit_account(deposit_account_id) ON DELETE CASCADE,
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    current_balance NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    available_balance NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    ledger_balance NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    accrued_interest NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    as_of_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE financial.deposit_balance IS 'Deposit account real-time balance snapshot';
COMMENT ON COLUMN financial.deposit_balance.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.deposit_balance.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.deposit_balance.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.deposit_balance.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.deposit_balance.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.deposit_balance.deposit_balance_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.deposit_balance.deposit_account_id IS 'Parent deposit account ID';
COMMENT ON COLUMN financial.deposit_balance.currency_code IS 'Balance currency code';
COMMENT ON COLUMN financial.deposit_balance.current_balance IS 'Book balance';
COMMENT ON COLUMN financial.deposit_balance.available_balance IS 'Funds available for withdrawal';
COMMENT ON COLUMN financial.deposit_balance.ledger_balance IS 'Settled ledger balance';
COMMENT ON COLUMN financial.deposit_balance.accrued_interest IS 'Unposted accrued interest balance';
COMMENT ON COLUMN financial.deposit_balance.as_of_timestamp IS 'Balance snapshot timestamp UTC';

CREATE TRIGGER trg_deposit_balance_updated_at
BEFORE UPDATE ON financial.deposit_balance
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.deposit_transaction (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    deposit_transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_reference VARCHAR(100) NOT NULL,
    deposit_account_id UUID NOT NULL REFERENCES financial.deposit_account(deposit_account_id) ON DELETE CASCADE,
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    transaction_type VARCHAR(30) NOT NULL CHECK (transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT', 'INTEREST_CREDIT', 'FEE')),
    amount NUMERIC(18,4) NOT NULL,
    booking_date TIMESTAMPTZ NOT NULL,
    value_date DATE NOT NULL,
    counterparty_account VARCHAR(100),
    transaction_status VARCHAR(20) NOT NULL DEFAULT 'BOOKED' CHECK (transaction_status IN ('BOOKED', 'PENDING', 'REVERSED'))
);

COMMENT ON TABLE financial.deposit_transaction IS 'Deposit transaction accounting journal records';
COMMENT ON COLUMN financial.deposit_transaction.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.deposit_transaction.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.deposit_transaction.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.deposit_transaction.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.deposit_transaction.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.deposit_transaction.deposit_transaction_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.deposit_transaction.transaction_reference IS 'Business key: Transaction reference number';
COMMENT ON COLUMN financial.deposit_transaction.deposit_account_id IS 'Target deposit account ID';
COMMENT ON COLUMN financial.deposit_transaction.currency_code IS 'Transaction currency code';
COMMENT ON COLUMN financial.deposit_transaction.transaction_type IS 'Type (DEPOSIT, WITHDRAWAL, TRANSFER_IN, TRANSFER_OUT, INTEREST_CREDIT, FEE)';
COMMENT ON COLUMN financial.deposit_transaction.amount IS 'Transaction amount (positive value)';
COMMENT ON COLUMN financial.deposit_transaction.booking_date IS 'Ledger posting timestamp UTC';
COMMENT ON COLUMN financial.deposit_transaction.value_date IS 'Interest value date';
COMMENT ON COLUMN financial.deposit_transaction.counterparty_account IS 'Counterparty IBAN / account';
COMMENT ON COLUMN financial.deposit_transaction.transaction_status IS 'Status (BOOKED, PENDING, REVERSED)';

CREATE TRIGGER trg_deposit_transaction_updated_at
BEFORE UPDATE ON financial.deposit_transaction
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.deposit_interest_term (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    deposit_interest_term_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deposit_account_id UUID NOT NULL REFERENCES financial.deposit_account(deposit_account_id) ON DELETE CASCADE,
    interest_rate NUMERIC(8,5) NOT NULL,
    rate_type VARCHAR(20) NOT NULL DEFAULT 'VARIABLE' CHECK (rate_type IN ('FIXED', 'VARIABLE')),
    accrual_frequency VARCHAR(20) NOT NULL DEFAULT 'DAILY' CHECK (accrual_frequency IN ('DAILY', 'MONTHLY', 'ANNUALLY')),
    calculation_basis VARCHAR(20) NOT NULL DEFAULT 'ACT/360' CHECK (calculation_basis IN ('ACT/360', 'ACT/365', '30/360')),
    effective_date DATE NOT NULL,
    expiry_date DATE
);

COMMENT ON TABLE financial.deposit_interest_term IS 'Deposit account interest terms and accrual rates';
COMMENT ON COLUMN financial.deposit_interest_term.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.deposit_interest_term.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.deposit_interest_term.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.deposit_interest_term.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.deposit_interest_term.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.deposit_interest_term.deposit_interest_term_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.deposit_interest_term.deposit_account_id IS 'Parent deposit account ID';
COMMENT ON COLUMN financial.deposit_interest_term.interest_rate IS 'Annual interest rate percentage (e.g., 0.02500 for 2.5%)';
COMMENT ON COLUMN financial.deposit_interest_term.rate_type IS 'Interest rate type (FIXED, VARIABLE)';
COMMENT ON COLUMN financial.deposit_interest_term.accrual_frequency IS 'Accrual frequency (DAILY, MONTHLY, ANNUALLY)';
COMMENT ON COLUMN financial.deposit_interest_term.calculation_basis IS 'Day count convention (ACT/360, ACT/365, 30/360)';
COMMENT ON COLUMN financial.deposit_interest_term.effective_date IS 'Term effective start date';
COMMENT ON COLUMN financial.deposit_interest_term.expiry_date IS 'Term expiration date';

CREATE TRIGGER trg_deposit_interest_term_updated_at
BEFORE UPDATE ON financial.deposit_interest_term
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.deposit_overdraft_facility (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    deposit_overdraft_facility_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deposit_account_id UUID NOT NULL REFERENCES financial.deposit_account(deposit_account_id) ON DELETE CASCADE,
    approved_limit NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    interest_rate_penalty NUMERIC(8,5) NOT NULL,
    facility_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (facility_status IN ('ACTIVE', 'SUSPENDED', 'CANCELLED')),
    granted_date DATE NOT NULL,
    expiry_date DATE
);

COMMENT ON TABLE financial.deposit_overdraft_facility IS 'Approved overdraft facility bounds for deposit accounts';
COMMENT ON COLUMN financial.deposit_overdraft_facility.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.deposit_overdraft_facility.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.deposit_overdraft_facility.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.deposit_overdraft_facility.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.deposit_overdraft_facility.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.deposit_overdraft_facility.deposit_overdraft_facility_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.deposit_overdraft_facility.deposit_account_id IS 'Associated deposit account ID';
COMMENT ON COLUMN financial.deposit_overdraft_facility.approved_limit IS 'Approved overdraft limit amount';
COMMENT ON COLUMN financial.deposit_overdraft_facility.interest_rate_penalty IS 'Penalty interest rate on overdrawn balances';
COMMENT ON COLUMN financial.deposit_overdraft_facility.facility_status IS 'Facility status (ACTIVE, SUSPENDED, CANCELLED)';
COMMENT ON COLUMN financial.deposit_overdraft_facility.granted_date IS 'Facility approval date';
COMMENT ON COLUMN financial.deposit_overdraft_facility.expiry_date IS 'Facility expiration date';

CREATE TRIGGER trg_deposit_overdraft_facility_updated_at
BEFORE UPDATE ON financial.deposit_overdraft_facility
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

-- ----------------------------------------------------------------------------
-- SECTION 4: LOAN DATA PRODUCT (loan)
-- ----------------------------------------------------------------------------

CREATE TABLE financial.loan_application (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    loan_application_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_number VARCHAR(50) NOT NULL,
    customer_id UUID NOT NULL REFERENCES financial.party_role_customer(party_role_customer_id),
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    requested_amount NUMERIC(18,4) NOT NULL,
    application_status VARCHAR(30) NOT NULL DEFAULT 'SUBMITTED' CHECK (application_status IN ('SUBMITTED', 'UNDERWRITING', 'APPROVED', 'REJECTED')),
    credit_score INTEGER,
    submission_date DATE NOT NULL,
    decision_date DATE
);

COMMENT ON TABLE financial.loan_application IS 'Loan origination and credit application lifecycle';
COMMENT ON COLUMN financial.loan_application.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.loan_application.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.loan_application.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.loan_application.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.loan_application.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.loan_application.loan_application_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.loan_application.application_number IS 'Business key: Application reference number';
COMMENT ON COLUMN financial.loan_application.customer_id IS 'Applicant customer ID';
COMMENT ON COLUMN financial.loan_application.currency_code IS 'Requested currency code';
COMMENT ON COLUMN financial.loan_application.requested_amount IS 'Requested loan principal amount';
COMMENT ON COLUMN financial.loan_application.application_status IS 'Application status (SUBMITTED, UNDERWRITING, APPROVED, REJECTED)';
COMMENT ON COLUMN financial.loan_application.credit_score IS 'Underwriting credit score snapshot';
COMMENT ON COLUMN financial.loan_application.submission_date IS 'Application submission date';
COMMENT ON COLUMN financial.loan_application.decision_date IS 'Underwriting decision date';

CREATE TRIGGER trg_loan_application_updated_at
BEFORE UPDATE ON financial.loan_application
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.loan_agreement (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    loan_agreement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agreement_number VARCHAR(50) NOT NULL,
    loan_application_id UUID NOT NULL REFERENCES financial.loan_application(loan_application_id),
    customer_id UUID NOT NULL REFERENCES financial.party_role_customer(party_role_customer_id),
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    principal_amount NUMERIC(18,4) NOT NULL,
    interest_rate NUMERIC(8,5) NOT NULL,
    term_months INTEGER NOT NULL,
    agreement_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (agreement_status IN ('ACTIVE', 'DEFAULTED', 'PAID_OFF')),
    is_npl BOOLEAN NOT NULL DEFAULT FALSE,
    disbursement_date DATE NOT NULL,
    maturity_date DATE NOT NULL
);

COMMENT ON TABLE financial.loan_agreement IS 'Core contractual loan agreement (FIBO Loan Agreement)';
COMMENT ON COLUMN financial.loan_agreement.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.loan_agreement.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.loan_agreement.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.loan_agreement.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.loan_agreement.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.loan_agreement.loan_agreement_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.loan_agreement.agreement_number IS 'Business key: Contractual agreement number';
COMMENT ON COLUMN financial.loan_agreement.loan_application_id IS 'Originating loan application ID';
COMMENT ON COLUMN financial.loan_agreement.customer_id IS 'Borrower customer ID';
COMMENT ON COLUMN financial.loan_agreement.currency_code IS 'Loan currency code';
COMMENT ON COLUMN financial.loan_agreement.principal_amount IS 'Approved loan principal amount';
COMMENT ON COLUMN financial.loan_agreement.interest_rate IS 'Contractual annual interest rate';
COMMENT ON COLUMN financial.loan_agreement.term_months IS 'Loan tenor in months';
COMMENT ON COLUMN financial.loan_agreement.agreement_status IS 'Loan status (ACTIVE, DEFAULTED, PAID_OFF)';
COMMENT ON COLUMN financial.loan_agreement.is_npl IS 'Non-Performing Loan (NPL) default indicator';
COMMENT ON COLUMN financial.loan_agreement.disbursement_date IS 'Initial disbursement date';
COMMENT ON COLUMN financial.loan_agreement.maturity_date IS 'Contractual maturity date';

CREATE TRIGGER trg_loan_agreement_updated_at
BEFORE UPDATE ON financial.loan_agreement
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.loan_repayment_schedule (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    loan_repayment_schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_agreement_id UUID NOT NULL REFERENCES financial.loan_agreement(loan_agreement_id) ON DELETE CASCADE,
    installment_number INTEGER NOT NULL,
    due_date DATE NOT NULL,
    principal_due NUMERIC(18,4) NOT NULL,
    interest_due NUMERIC(18,4) NOT NULL,
    total_due NUMERIC(18,4) NOT NULL,
    installment_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (installment_status IN ('PENDING', 'PAID', 'OVERDUE', 'PARTIALLY_PAID')),
    paid_amount NUMERIC(18,4) NOT NULL DEFAULT 0.0000,
    paid_date DATE
);

COMMENT ON TABLE financial.loan_repayment_schedule IS 'Amortization repayment schedule installments';
COMMENT ON COLUMN financial.loan_repayment_schedule.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.loan_repayment_schedule.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.loan_repayment_schedule.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.loan_repayment_schedule.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.loan_repayment_schedule.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.loan_repayment_schedule.loan_repayment_schedule_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.loan_repayment_schedule.loan_agreement_id IS 'Parent loan agreement ID';
COMMENT ON COLUMN financial.loan_repayment_schedule.installment_number IS 'Sequential installment number';
COMMENT ON COLUMN financial.loan_repayment_schedule.due_date IS 'Payment due date';
COMMENT ON COLUMN financial.loan_repayment_schedule.principal_due IS 'Scheduled principal component';
COMMENT ON COLUMN financial.loan_repayment_schedule.interest_due IS 'Scheduled interest component';
COMMENT ON COLUMN financial.loan_repayment_schedule.total_due IS 'Total installment due';
COMMENT ON COLUMN financial.loan_repayment_schedule.installment_status IS 'Status (PENDING, PAID, OVERDUE, PARTIALLY_PAID)';
COMMENT ON COLUMN financial.loan_repayment_schedule.paid_amount IS 'Cumulative amount paid';
COMMENT ON COLUMN financial.loan_repayment_schedule.paid_date IS 'Actual payment date';

CREATE TRIGGER trg_loan_repayment_schedule_updated_at
BEFORE UPDATE ON financial.loan_repayment_schedule
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.loan_disbursement (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    loan_disbursement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    disbursement_reference VARCHAR(100) NOT NULL,
    loan_agreement_id UUID NOT NULL REFERENCES financial.loan_agreement(loan_agreement_id) ON DELETE CASCADE,
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    disbursed_amount NUMERIC(18,4) NOT NULL,
    disbursement_date TIMESTAMPTZ NOT NULL,
    target_account_number VARCHAR(100) NOT NULL,
    disbursement_status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED' CHECK (disbursement_status IN ('COMPLETED', 'PENDING', 'FAILED'))
);

COMMENT ON TABLE financial.loan_disbursement IS 'Loan principal disbursement execution events';
COMMENT ON COLUMN financial.loan_disbursement.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.loan_disbursement.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.loan_disbursement.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.loan_disbursement.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.loan_disbursement.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.loan_disbursement.loan_disbursement_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.loan_disbursement.disbursement_reference IS 'Business key: Disbursement reference number';
COMMENT ON COLUMN financial.loan_disbursement.loan_agreement_id IS 'Associated loan agreement ID';
COMMENT ON COLUMN financial.loan_disbursement.currency_code IS 'Disbursement currency code';
COMMENT ON COLUMN financial.loan_disbursement.disbursed_amount IS 'Disbursed principal amount';
COMMENT ON COLUMN financial.loan_disbursement.disbursement_date IS 'Execution timestamp UTC';
COMMENT ON COLUMN financial.loan_disbursement.target_account_number IS 'Beneficiary destination IBAN';
COMMENT ON COLUMN financial.loan_disbursement.disbursement_status IS 'Status (COMPLETED, PENDING, FAILED)';

CREATE TRIGGER trg_loan_disbursement_updated_at
BEFORE UPDATE ON financial.loan_disbursement
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

CREATE TABLE financial.loan_collateral (
    md_created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_from_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    md_valid_to_utc TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00',
    md_is_active BOOLEAN NOT NULL DEFAULT TRUE,

    loan_collateral_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_agreement_id UUID NOT NULL REFERENCES financial.loan_agreement(loan_agreement_id) ON DELETE CASCADE,
    collateral_type VARCHAR(30) NOT NULL CHECK (collateral_type IN ('REAL_ESTATE', 'VEHICLE', 'SECURITIES', 'CASH_DEPOSIT')),
    currency_code VARCHAR(3) NOT NULL REFERENCES ref.ref_currency(currency_code),
    estimated_value NUMERIC(18,4) NOT NULL,
    ltv_ratio NUMERIC(8,5) NOT NULL,
    valuation_date DATE NOT NULL,
    collateral_status VARCHAR(20) NOT NULL DEFAULT 'PLEDGED' CHECK (collateral_status IN ('PLEDGED', 'RELEASED', 'LIQUIDATED'))
);

COMMENT ON TABLE financial.loan_collateral IS 'Pledged security assets securing loan contracts';
COMMENT ON COLUMN financial.loan_collateral.md_created_at_utc IS 'Operational metadata: Record creation timestamp UTC';
COMMENT ON COLUMN financial.loan_collateral.md_updated_at_utc IS 'Operational metadata: System update timestamp UTC';
COMMENT ON COLUMN financial.loan_collateral.md_valid_from_utc IS 'SCD Type 2: Effective start timestamp UTC';
COMMENT ON COLUMN financial.loan_collateral.md_valid_to_utc IS 'SCD Type 2: Effective end timestamp UTC (9999-12-31 for active records)';
COMMENT ON COLUMN financial.loan_collateral.md_is_active IS 'SCD Type 2: Active version flag (TRUE=active, FALSE=historical)';
COMMENT ON COLUMN financial.loan_collateral.loan_collateral_id IS 'Surrogate primary key UUID';
COMMENT ON COLUMN financial.loan_collateral.loan_agreement_id IS 'Secured loan agreement ID';
COMMENT ON COLUMN financial.loan_collateral.collateral_type IS 'Collateral type (REAL_ESTATE, VEHICLE, SECURITIES, CASH_DEPOSIT)';
COMMENT ON COLUMN financial.loan_collateral.currency_code IS 'Valuation currency code';
COMMENT ON COLUMN financial.loan_collateral.estimated_value IS 'Appraised market value';
COMMENT ON COLUMN financial.loan_collateral.ltv_ratio IS 'Loan-to-Value ratio (e.g., 0.75000 for 75%)';
COMMENT ON COLUMN financial.loan_collateral.valuation_date IS 'Appraisal valuation date';
COMMENT ON COLUMN financial.loan_collateral.collateral_status IS 'Status (PLEDGED, RELEASED, LIQUIDATED)';

CREATE TRIGGER trg_loan_collateral_updated_at
BEFORE UPDATE ON financial.loan_collateral
FOR EACH ROW EXECUTE FUNCTION financial.fn_update_md_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA financial TO postgres, authenticated, service_role;
GRANT SELECT ON ALL TABLES IN SCHEMA financial TO anon;

-- ----------------------------------------------------------------------------
-- SECTION 5: COMPOSITE INDEXES FOR SCD TYPE 2 & BUSINESS KEY PERFORMANCE
-- ----------------------------------------------------------------------------

CREATE INDEX idx_party_bk ON financial.party(party_bk);
CREATE INDEX idx_party_scd_active ON financial.party(md_is_active) WHERE md_is_active = TRUE;
CREATE INDEX idx_party_scd_temporal ON financial.party(md_valid_from_utc, md_valid_to_utc);

CREATE INDEX idx_party_individual_party_id ON financial.party_individual(party_id, md_is_active);
CREATE INDEX idx_party_organization_party_id ON financial.party_organization(party_id, md_is_active);

CREATE INDEX idx_customer_party_id ON financial.party_role_customer(party_id, md_is_active);
CREATE INDEX idx_customer_number ON financial.party_role_customer(customer_number);
CREATE INDEX idx_customer_scd_active ON financial.party_role_customer(md_is_active) WHERE md_is_active = TRUE;

CREATE INDEX idx_address_party_id ON financial.party_address(party_id, md_is_active);
CREATE INDEX idx_identification_party_id ON financial.party_identification(party_id, md_is_active);

CREATE INDEX idx_deposit_account_customer ON financial.deposit_account(customer_id, md_is_active);
CREATE INDEX idx_deposit_account_number ON financial.deposit_account(account_number);
CREATE INDEX idx_deposit_account_scd_active ON financial.deposit_account(md_is_active) WHERE md_is_active = TRUE;

CREATE INDEX idx_deposit_balance_account ON financial.deposit_balance(deposit_account_id, md_is_active);
CREATE INDEX idx_deposit_transaction_account ON financial.deposit_transaction(deposit_account_id, booking_date);
CREATE INDEX idx_deposit_interest_term_account ON financial.deposit_interest_term(deposit_account_id, md_is_active);
CREATE INDEX idx_deposit_overdraft_facility_account ON financial.deposit_overdraft_facility(deposit_account_id, md_is_active);

CREATE INDEX idx_loan_app_customer ON financial.loan_application(customer_id, md_is_active);
CREATE INDEX idx_loan_app_number ON financial.loan_application(application_number);

CREATE INDEX idx_loan_agreement_customer ON financial.loan_agreement(customer_id, md_is_active);
CREATE INDEX idx_loan_agreement_number ON financial.loan_agreement(agreement_number);
CREATE INDEX idx_loan_agreement_scd_active ON financial.loan_agreement(md_is_active) WHERE md_is_active = TRUE;
CREATE INDEX idx_loan_agreement_npl ON financial.loan_agreement(is_npl) WHERE is_npl = TRUE;

CREATE INDEX idx_loan_repayment_schedule_agreement ON financial.loan_repayment_schedule(loan_agreement_id, installment_number);
CREATE INDEX idx_loan_disbursement_agreement ON financial.loan_disbursement(loan_agreement_id);
CREATE INDEX idx_loan_collateral_agreement ON financial.loan_collateral(loan_agreement_id);
