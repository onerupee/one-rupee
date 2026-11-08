# One Rupee production rollout checklist

This checklist separates code-level tests from checks that require real Cashfree
and Supabase accounts. Passing `pytest` does not prove external integrations work.

## A. Supabase PostgreSQL

1. Create a Supabase project and copy its PostgreSQL connection string.
2. Use the connection string supported by your host (Supabase pooler is often
   preferable for serverless/short-lived connections). Keep the password private.
3. In Supabase **SQL Editor**, apply migrations in order:
   - `backend/migrations/001_initial_schema.sql`
   - `backend/migrations/002_payment_integrity.sql`
4. Confirm both tables exist: `members` and `payments`.
5. Confirm Row Level Security is enabled on both tables. The FastAPI server uses
   the database connection string server-side; never put it in browser code.
6. Set `DATABASE_URL` only in the Render service's secret environment settings.

Migration 002 adds a uniqueness constraint for Cashfree payment IDs and a
consistency constraint requiring every activated member to have a `PAID`
payment and activation timestamp. It intentionally fails if old rows violate
those invariants. Resolve such rows before retrying the migration.

## B. Supabase Storage

1. Create a **private** Storage bucket named `certificates` (or configure a
   different bucket with `SUPABASE_CERTIFICATE_BUCKET`).
2. Set `CERTIFICATE_STORAGE=supabase`.
3. Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` on the backend host only.
4. Keep `SUPABASE_CERTIFICATE_PUBLIC=false`.
5. Run a sandbox payment and verify that the resulting certificate object is
   present in `members/` in the private bucket and that the signed URL opens.
6. Confirm that a later request creates a fresh signed URL; signed URLs expire.

The service-role key bypasses Storage policies. Never expose it to the browser,
commit it, or print it in logs.

## C. Cashfree sandbox

1. Configure Cashfree sandbox credentials in Render.
2. Set `CASHFREE_ENV=sandbox` and the exact HTTPS Render URL in
   `ONE_RUPEE_BASE_URL`.
3. Configure the Cashfree webhook URL as
   `https://YOUR_RENDER_HOST/webhooks/cashfree`.
4. Subscribe to the relevant payment/order event types in Cashfree.
5. Complete a full sandbox checkout from the public `/pay` page.
6. Confirm the backend fetches the order from Cashfree and sees `PAID` before
   creating a member.
7. Confirm a duplicate webhook/return does not create another member.
8. Test failed, cancelled, and pending payments; none should create a member.

Use Cashfree's current dashboard/documentation to confirm webhook event names
and the credentials/environment used for signature verification. Do not use
production credentials until the sandbox flow is verified.

## D. Render

Build command:

```bash
pip install .
```

Start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Required backend environment variables:

- `CASHFREE_APP_ID`
- `CASHFREE_SECRET_KEY`
- `CASHFREE_ENV=sandbox`
- `ONE_RUPEE_BASE_URL=https://YOUR_RENDER_HOST`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `CERTIFICATE_STORAGE=supabase`
- `SUPABASE_CERTIFICATE_BUCKET=certificates`
- `SUPABASE_CERTIFICATE_PUBLIC=false`

After deploy, verify `/health` and `/ready`. `/health` only proves the API
process responds; `/ready` performs a database connectivity check. Run
`python scripts/production_preflight.py` in an environment with the same
configuration to check required settings, the required database tables, the migration 002
uniqueness index, and access to the configured Storage bucket. It does not create
a payment, upload a certificate, or verify Cashfree credentials/checkout end to end.

## E. Release gate

Do not enable live payments until all of these are true:

- [ ] Migrations 001 and 002 applied successfully.
- [ ] `/ready` returns HTTP 200.
- [ ] Private Storage upload and signed retrieval tested with a real project.
- [ ] Successful Cashfree sandbox payment creates exactly one member.
- [ ] Duplicate webhook and browser return do not create duplicate members.
- [ ] Failed/pending/cancelled payment creates no member.
- [ ] Certificate survives a Render restart/redeploy.
- [ ] No secret values are present in Git history or frontend assets.
- [ ] A backup/recovery plan exists for the Supabase database.

Only after these checks should the Cashfree production environment be
configured. A passing local test suite alone is not a production release gate.

## Non-destructive deployed API smoke test

After deploying the FastAPI service, run this from the project root:

```powershell
python scripts/deployment_smoke_test.py https://YOUR-RENDER-SERVICE.onrender.com
```

The script checks `/health` and `/ready` only. It does not create a Cashfree
order, charge a customer, create a member, or upload a certificate. A passing
result confirms that the public API responds and its configured database is
reachable; it does **not** prove that Cashfree checkout, webhook delivery, or
Supabase Storage uploads work end to end.

## Cashfree sandbox end-to-end acceptance test

Perform this manually only after the non-destructive smoke test passes:

1. Set `CASHFREE_ENV=sandbox` and configure the sandbox App ID and secret in
   the hosting provider's secret environment settings.
2. Set `ONE_RUPEE_BASE_URL` to the exact HTTPS public service URL.
3. Add that domain to the Cashfree sandbox web checkout allowlist, if required
   by the Cashfree account configuration.
4. Configure the Cashfree webhook URL as
   `https://YOUR-RENDER-SERVICE.onrender.com/webhooks/cashfree` and subscribe
   to the payment/order event used by the integration.
5. Open `/pay`, create a sandbox payment, and complete it with Cashfree's
   currently documented sandbox test instrument details.
6. Confirm the order is `PAID` using the server-side Cashfree order lookup,
   then confirm exactly one member and one certificate exist.
7. Deliver/retry the same webhook event and refresh the return page. Confirm
   the existing membership is returned and no second member is created.
8. Test a failed/cancelled payment and confirm that no membership or
   certificate is created.

Use Cashfree's current sandbox test details from its official documentation;
do not hardcode test card numbers or credentials into this repository. Never
perform these tests with production credentials unless you intentionally want
to make a real payment.

## Local SQLite integrity parity

The local SQLite backend now enforces uniqueness for non-null
`cashfree_payment_id` values with the `uq_payments_cashfree_payment_id`
partial unique index. This mirrors the PostgreSQL invariant created by
`backend/migrations/002_payment_integrity.sql`. Existing local databases get
the index automatically when `init_db()` runs. If an older database already
contains the same Cashfree payment ID on multiple payment rows, initialization
will fail rather than silently choosing or deleting a record; investigate and
repair those rows before restarting.

Automated tests cover both reuse of a Cashfree payment ID across different
orders and two concurrent activation attempts for the same SQLite order. These
are local database tests, not a substitute for running concurrency tests
against the actual Supabase PostgreSQL project.
