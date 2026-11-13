-- One Rupee: payment integrity hardening (PostgreSQL / Supabase)
-- Apply after 001_initial_schema.sql in the Supabase SQL Editor.
-- This migration intentionally fails if existing data violates the new
-- invariants; investigate inconsistent rows rather than silently rewriting them.

-- A successful Cashfree payment identifier must not be attached to two orders.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_cashfree_payment_id
    ON payments (cashfree_payment_id)
    WHERE cashfree_payment_id IS NOT NULL;

-- An activated membership must always be backed by a PAID payment and have
-- an activation timestamp. Unactivated rows must not carry activation time.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_payment_activation_consistency'
          AND conrelid = 'payments'::regclass
    ) THEN
        ALTER TABLE payments
            ADD CONSTRAINT chk_payment_activation_consistency
            CHECK (
                (member_id IS NULL AND activated_at IS NULL)
                OR
                (member_id IS NOT NULL AND activated_at IS NOT NULL AND status = 'PAID')
            ) NOT VALID;
    END IF;
END $$;

ALTER TABLE payments
    VALIDATE CONSTRAINT chk_payment_activation_consistency;

-- Keep member identifiers monotonic after imports/manual data restoration.
-- SERIAL sequences are normally correct; this safely advances the sequence
-- if imported rows have a larger ID than its current value.
SELECT setval(
    pg_get_serial_sequence('members', 'id'),
    GREATEST(COALESCE((SELECT MAX(id) FROM members), 1), 1),
    EXISTS (SELECT 1 FROM members)
);

DO $$
BEGIN
    RAISE NOTICE 'One Rupee payment integrity migration 002 applied.';
END $$;
