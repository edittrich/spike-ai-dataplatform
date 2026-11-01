# Prompt 2: Data Model and Supabase Database

> Run this after Prompt 1 is merged, in the `spike-ai-dataplatform-steps`
> repository. Copy everything below the line.

---

We are continuing the BIAN/FIBO-aligned financial data platform in this repository.
Read CLAUDE.md, docs/REQUIREMENTS.md, and docs/ROADMAP.md first. This is step 2: the
relational data model and a local Supabase database. Build only this step.

## Work in two phases

Phase A: write docs/DATA_MODEL.md in a pull request. Cover the entities,
relationships, table kinds, versioning rules, and the effect of the stable-identity
design on joins. Then stop and wait for my approval.

Phase B: after I approve, implement it in several small pull requests, for example
schema, access boundary, simulator, and verification.

## Setup

- Supabase CLI 2.x, pinned in package.json, run locally with
  `db.major_version = 17`. PostgreSQL 18 temporal foreign keys are unavailable on
  Supabase, so do not use them.
- Ports: API 54321, database 54322, Studio 54323.
- npm scripts: supabase:start, supabase:stop, supabase:db:reset.
- Python through uv, with psycopg 3 and pytest.
- All credentials come from the typed settings object, with no hardcoded fallback.
  Extend .env.example. A Supabase reset restores the CLI's default local postgres
  password, so document how the tests connect after a reset.

## Conventions

- Four schemas: ref (reference data), financial (operational data), pii (direct
  identifiers), and curated (views for consumers).
- Inmon-style 3NF. Table names are prefixed by domain: party, deposit, loan, ref.
- UUID surrogate keys via gen_random_uuid(). Monetary values NUMERIC(18,4), rates
  NUMERIC(8,5), all timestamps TIMESTAMPTZ in UTC.
- Enumerations as named CHECK constraints.
- COMMENT ON every table and column. These comments later feed the data catalog, so
  write them for a business reader, and start each business-key column's comment
  with "Business key:".

## Table kinds

Classify every table in docs/DATA_MODEL.md:

- Versioned: master data and contract terms. This is every table in the financial
  and pii schemas that is not listed below. These tables carry the SCD2 header.
- Event, append-only: deposit_transaction, loan_disbursement, and loan_repayment.
  Block UPDATE and DELETE with a trigger. Corrections are new compensating rows that
  reference the row they reverse, so these tables hold no mutable status. Use
  md_created_at_utc instead of the SCD2 header.
- Snapshot: deposit_balance, one row per account and as-of date, computed from the
  transaction ledger. Use md_created_at_utc instead of the SCD2 header.

The SCD2 header is:

```text
md_created_at_utc  TIMESTAMPTZ NOT NULL DEFAULT now()
md_updated_at_utc  TIMESTAMPTZ NOT NULL DEFAULT now()  (maintained by a trigger)
md_valid_from_utc  TIMESTAMPTZ NOT NULL DEFAULT now()
md_valid_to_utc    TIMESTAMPTZ NOT NULL DEFAULT '9999-12-31 23:59:59+00'
md_is_active       BOOLEAN NOT NULL DEFAULT TRUE
```

## Stable identity

party, party_role_customer, deposit_account, loan_application, and loan_agreement
each become an immutable anchor table (stable ID, business key, attributes that never
change) plus a version table. Foreign keys reference the anchor, so closing a version
never strands its children.

## Model

The column lists below are the logical baseline. `[pii]` marks a field that moves to
the pii schema, 1:1 with its parent. `(BK)` marks a business key.

Do not store what can be derived. These values are computed in curated views:
ltv_ratio, days_past_due, paid amounts, installment status, and is_npl (90+ days past
due).

### ref schema

Plain lookups with created_at, and no SCD2 header:

- ref_country: country_code (ISO alpha-2, PK), country_name, iso_alpha3, iso_numeric
- ref_country_aml_risk: country_code, is_high_risk, valid_from, valid_to (dated
  history, with no overlapping ranges per country)
- ref_currency: currency_code (ISO 4217, PK), currency_name, symbol, decimal_places,
  is_active
- ref_nace_industry: nace_code (PK), nace_section, nace_title,
  risk_level (LOW/MEDIUM/HIGH)
- ref_fx_rate: rate_date, base_currency, quote_currency, rate, source

The reporting currency is EUR.

### Party & Customer

- party (anchor + version): party_bk (BK), party_type (INDIVIDUAL/ORGANIZATION),
  status_code (ACTIVE/INACTIVE/SUSPENDED)
- party_individual: party ref, first_name [pii], last_name [pii],
  date_of_birth [pii], gender [pii], citizenship_country_code,
  tax_residence_country_code
- party_organization: party ref, legal_name, trade_name, registration_number [pii],
  incorporation_date, incorporation_country_code, nace_code, legal_form
- party_address: party ref, address_type (RESIDENTIAL/REGISTERED/MAILING),
  street_address [pii], building_number [pii], city, postal_code, country_code,
  is_primary
- party_identification: party ref, id_type (PASSPORT/NATIONAL_ID/TAX_ID/LEI),
  id_number [pii], issuing_country_code, issue_date, expiry_date,
  verification_status (VERIFIED/UNVERIFIED)
- party_role_customer (anchor + version): customer_number (BK), party ref,
  customer_segment (RETAIL/SME/CORPORATE/WEALTH), onboarding_date,
  kyc_status (VERIFIED/PENDING/EXPIRED), kyc_last_review_date,
  aml_risk_rating (LOW/MEDIUM/HIGH)
- party_relationship: from party ref, to party ref,
  relationship_type (UBO/DIRECTOR/GUARANTOR/HOUSEHOLD), ownership_share

### Deposit & Liquidity

- deposit_account (anchor + version): account_number (BK), currency_code,
  account_type (SAVINGS/CHECKING/TERM_DEPOSIT),
  account_status (ACTIVE/DORMANT/FROZEN/CLOSED), opened_date, closed_date
- deposit_account_holder: account ref, customer ref,
  holder_role (PRIMARY/JOINT/AUTHORIZED)
- deposit_balance (snapshot): account ref, as_of_date, currency_code,
  current_balance, available_balance, ledger_balance, accrued_interest
- deposit_transaction (event): transaction_reference (BK), account ref,
  currency_code,
  transaction_type (DEPOSIT/WITHDRAWAL/TRANSFER_IN/TRANSFER_OUT/INTEREST_CREDIT/FEE),
  amount, booking_date, value_date, counterparty deposit account ref (internal
  transfers), counterparty_account (external accounts only, free text),
  reversed transaction ref
- deposit_interest_term: account ref, interest_rate, rate_type (FIXED/VARIABLE),
  accrual_frequency (DAILY/MONTHLY/ANNUALLY),
  calculation_basis (ACT/360, ACT/365, 30/360), effective_date, expiry_date
- deposit_overdraft_facility: account ref, approved_limit, interest_rate_penalty,
  facility_status (ACTIVE/SUSPENDED/CANCELLED), granted_date, expiry_date

### Loan & Credit Risk

- loan_application (anchor + version): application_number (BK), customer ref,
  currency_code, requested_amount,
  application_status (SUBMITTED/UNDERWRITING/APPROVED/REJECTED), credit_score,
  submission_date, decision_date
- loan_agreement (anchor + version): agreement_number (BK), application ref,
  currency_code, principal_amount, interest_rate, term_months,
  agreement_status (ACTIVE/DEFAULTED/PAID_OFF), disbursement_date, maturity_date
- loan_party_role: agreement ref, party ref,
  party_role (BORROWER/CO_BORROWER/GUARANTOR). This is the only link between an
  agreement and its parties.
- loan_disbursement (event): disbursement_reference (BK), agreement ref,
  currency_code, disbursed_amount, disbursement_date, target deposit account ref,
  reversed disbursement ref
- loan_repayment (event): repayment_reference (BK), agreement ref,
  installment_number, source deposit account ref, currency_code, amount,
  booking_date, reversed repayment ref
- loan_repayment_schedule: agreement ref, installment_number, due_date,
  principal_due, interest_due, total_due (generated column)
- loan_collateral: agreement ref,
  collateral_type (REAL_ESTATE/VEHICLE/SECURITIES/CASH_DEPOSIT), currency_code,
  estimated_value, valuation_date,
  collateral_status (PLEDGED/RELEASED/LIQUIDATED), pledged deposit account ref

## Integrity, built in from the first migration

- Temporal order: md_valid_from_utc < md_valid_to_utc on every versioned table.
- md_is_active is true exactly when md_valid_to_utc is the sentinel value.
- Non-overlapping history: use EXCLUDE USING gist (btree_gist) with
  tstzrange(md_valid_from_utc, md_valid_to_utc) on the logical key of each versioned
  table. This means the five anchors, plus:
  - one party_individual or party_organization version per party
  - one installment number per agreement

  Justify in docs/DATA_MODEL.md any versioned table with no such key.
- Event business keys are UNIQUE. Snapshots are UNIQUE per account and as-of date.
- At most one active BORROWER per agreement, enforced by a partial unique index.
- A transaction has a counterparty account reference or an external account, never
  both. Collateral has a pledged deposit account exactly when its type is
  CASH_DEPOSIT.
- Domain rules as CHECK constraints: positive amounts where meaningful,
  maturity_date after disbursement_date, and closing dates not before opening dates.
- An index on every foreign-key column, partial indexes for active rows, and
  composite indexes for active-row lookups.
- Security from day one:
  - Enable RLS on all ref, financial, and pii tables, with no policies for anon or
    authenticated.
  - Grant anon and authenticated nothing on ref, financial, pii, or curated.
  - Do not expose any of the four schemas in config.toml's `[api].schemas`.
  - Set `enable_signup = false`.

## Data access boundary

- Add curated views over current, non-PII data, including reporting-currency amounts
  and the derived values above. Document an as-of query pattern.
- Add a NOLOGIN group role, curated_reader, that can read only curated.
- Add model/column_classification.yaml with pii_class, owner domain, and FIBO IRI for
  every column. A test fails on any unclassified column.

## Seed data

Add an entry point that writes supabase/seed.sql, and `npm run supabase:db:reset`
loads it. It is a day-by-day simulator with a fixed clock, not independent random
rows. It covers onboarding, account opening, transfers between real accounts, loan
applications including rejections, disbursements into real accounts, repayments
debited from those accounts, missed payments leading to default, KYC, AML and address
changes, and account closures.

- Deterministic: running it twice gives identical output. Derive all UUIDs from the
  seeded generator, because uuid.uuid4() ignores random.seed().
- 1,000 parties: 800 individuals and 200 organizations, each with a customer role.
- Include a minimal SCD2 close-and-insert path in this step and create all history
  through it, in several tables.
- Every balance must equal the sum of its transactions.
- Include overdrawn accounts, NPLs, high-risk-country customers, and all AML levels.
- Generate FX rates for the simulated dates. Amounts respect each currency's
  decimal_places.
- Reference data uses real ISO and NACE codes.
- Plant at least three named cases: a UBO chain ending in a high-risk country,
  guarantor contagion from a defaulted loan, and an account overdrawn beyond its
  limit.

## Golden answers

The simulator also writes tests/golden/expected_answers.yaml, with the question, SQL
against curated, and the expected value from simulator state. A test compares them.
Later steps reuse this file as benchmark ground truth.

## Verification

Add integration tests that run against the local database. Locally they skip cleanly
when no database is reachable. In CI, a skipped database test is a failure.

Negative tests must actually attempt the bad operation and assert rejection:

- overlapping versions of the same key
- two active versions of the same key
- an invalid enum value
- an orphaned foreign key
- an inverted validity range
- UPDATE or DELETE on an event table
- anon and authenticated reading any table or view in the four schemas
- curated_reader reading anything outside curated, tested with SET ROLE

Also assert that:

- curated_reader gets real rows from every curated view, not just permission
- no curated view exposes a pii column
- every table and column has a comment
- every foreign-key column has an index
- there are no referential or subtype mismatches in the seed
- every active row's chain resolves to active parents
- every agreement has exactly one active BORROWER

Add Hypothesis as a dev dependency. Use property-based tests for invariants: versions
of one key never overlap, at most one version of a key is current, and every balance
equals the sum of its transactions.

Add an entry point that generates schema.dbml from the live database, never by hand,
and a test that fails if it drifts.

## CI

Add a CI job that starts the pinned Supabase stack, resets it twice, and runs all
tests.

## Out of scope for this step

Do not build vector embeddings, login roles for services, a semantic layer, a graph,
a catalog, APIs, or AI components. Do not add Docker services.

## Done when

- `npm run supabase:db:reset` succeeds on a clean start and when repeated.
- All tests pass, locally and in CI.
- Tag step-02-data-model exists.
- You report row counts per table and the actual test output.
- If something failed or was skipped, say so plainly.
