# Stage 10 — Supabase schema integration verification

Stage 10 adds a **read-only** check for a real Supabase PostgreSQL database. It
verifies connectivity, the expected `members` and `payments` columns, required
payment/member uniqueness indexes, required payment constraints, and Row Level
Security on both tables. It does not create or modify records.

## Run locally

1. Install the project and PostgreSQL driver:

   ```powershell
   pip install -e "."
   ```

2. Set `DATABASE_URL` to the Supabase **PostgreSQL connection string** in your
   local shell or deployment environment. Use the connection string from
   Supabase Project Settings → Database. Prefer the pooler connection string
   when required by your hosting provider. Never commit this value or paste it
   into source code.

3. In Supabase SQL Editor, apply these migrations in order:
   - `backend/migrations/001_initial_schema.sql`
   - `backend/migrations/002_payment_integrity.sql`

4. Run the read-only check:

   ```powershell
   python scripts/supabase_integration_check.py
   ```

A successful result confirms the database is reachable and the expected
schema objects exist. It does **not** prove that Cashfree payments, Storage
uploads, webhook delivery, or production traffic work end to end.

## Safety

- The script uses read-only transaction mode and catalog `SELECT` queries.
- It does not print the database URL or driver exception details.
- It does not create test members, payments, or certificates.
- Keep `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and Cashfree secrets out of
  Git and out of screenshots/logs.

If the check reports missing objects, inspect the Supabase SQL Editor history
and apply the migrations in order. Do not drop production tables to make the
check pass.
