# Stage 9 — Payment identity and concurrency hardening

## Changes

- Added a partial unique index to SQLite for non-null `cashfree_payment_id`.
  This brings local database behavior in line with PostgreSQL migration 002.
- Added a regression test proving one Cashfree payment ID cannot activate two
  separate local orders.
- Added a concurrent activation test proving two simultaneous attempts for the
  same SQLite order create only one member.
- Documented how existing local SQLite databases receive the index and what
  happens if historical duplicate payment IDs are present.

## Verification performed

- `pytest -q`: 47 passed.
- `python -m compileall -q backend one_rupee scripts`: passed.

## Not verified in this stage

- No live Supabase connection was made.
- No live Cashfree sandbox payment or webhook was sent.
- No Render deployment was changed or tested.
- PostgreSQL concurrency behavior still needs a test against a disposable
  Supabase project or a local PostgreSQL instance.

Do not interpret the local test results as a production certification.
