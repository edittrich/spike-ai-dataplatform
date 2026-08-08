-- ============================================================================
-- D9 addendum (hardening plan): deposit_balance had no uniqueness guarantee
-- on deposit_account_id, despite Cube.js's deposit_account.yml joining it as
-- `has_one` (see the comment at that join: "the current seed happens to be
-- 1:1, so it works -- a second snapshot per account will silently fan out
-- four measures with no error"). deposit_balance is a real-time snapshot
-- table (one row per account reflecting its *current* balance), not a
-- SCD2 business-key table, so this does not use the EXCLUDE-based temporal
-- overlap pattern from the Q13 migration -- there is no meaningful validity
-- range to overlap-check here, only "at most one active snapshot per
-- account" to enforce.
--
-- Verified against the live, already-loaded database before writing this:
-- zero accounts currently have more than one active (md_is_active = TRUE)
-- balance row, so this is safe to apply directly.
-- ============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_deposit_balance_account_active
    ON financial.deposit_balance (deposit_account_id)
    WHERE md_is_active = TRUE;

COMMENT ON INDEX financial.uq_deposit_balance_account_active IS
    'D9: guarantees at most one active balance snapshot per deposit account, preventing the deposit_account -> deposit_balance Cube.js has_one join from silently fanning out measures if a second concurrent snapshot is ever inserted.';
