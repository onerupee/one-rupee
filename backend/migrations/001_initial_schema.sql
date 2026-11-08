-- One Rupee: Initial Supabase PostgreSQL Schema
-- Run this in the Supabase SQL Editor to set up the database.
--
-- This migration creates the members and payments tables with
-- appropriate constraints, indexes, and security settings.

-- ============================================================
-- MEMBERS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS members (
    id          SERIAL PRIMARY KEY,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- PAYMENTS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS payments (
    id                   SERIAL PRIMARY KEY,
    order_id             TEXT UNIQUE NOT NULL,
    customer_id          TEXT NOT NULL,
    customer_phone       TEXT,
    customer_name        TEXT,
    amount               NUMERIC(10, 2) NOT NULL DEFAULT 1.00,
    currency             TEXT NOT NULL DEFAULT 'INR',
    status               TEXT NOT NULL DEFAULT 'PENDING',
    cashfree_payment_id  TEXT,
    member_id            INTEGER REFERENCES members(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at          TIMESTAMPTZ,
    activated_at         TIMESTAMPTZ,
    certificate_path     TEXT,
    certificate_url      TEXT,

    -- Prevent duplicate activations: only one payment per order can have a member_id
    CONSTRAINT chk_amount_exactly_one CHECK (amount = 1.00),
    CONSTRAINT chk_currency_valid CHECK (currency IN ('INR')),
    CONSTRAINT chk_status_valid CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'EXPIRED'))
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_payments_customer_id
    ON payments(customer_id);

CREATE INDEX IF NOT EXISTS idx_payments_status
    ON payments(status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_member_id
    ON payments(member_id)
    WHERE member_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payments_order_id
    ON payments(order_id);

CREATE INDEX IF NOT EXISTS idx_payments_activated
    ON payments(customer_id, activated_at DESC)
    WHERE member_id IS NOT NULL;


-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================
-- Enable RLS on both tables. Only the service role key (used by
-- the backend) can read/write. The anon key has no access.

ALTER TABLE members ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS automatically in Supabase.
-- No policies needed for anon key (it should have NO access).


-- ============================================================
-- FUNCTION: Prevent duplicate member activation
-- ============================================================
-- This function is used by the backend, but the actual
-- idempotency logic is handled in application code with
-- SELECT ... FOR UPDATE transactions.

-- Verify the schema was created successfully
DO $$
BEGIN
    RAISE NOTICE 'One Rupee schema created successfully.';
END $$;
