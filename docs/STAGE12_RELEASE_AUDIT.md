# One Rupee — Stage 12 Release Audit

## Changes in this stage

- Moved the installation identity marker from the distributable Python package into the per-user `~/.one_rupee/` data directory.
- Created the marker with exclusive file creation so two simultaneous first launches do not overwrite each other's installation identity.
- Removed the checked-in installation marker from the release package and removed it from package data. This prevents every person installing the same wheel/source archive from inheriting one shared customer ID.
- Aligned the package and FastAPI application version at `0.4.3`.
- Added a regression test for per-user installation identity persistence.
- Removed generated Python bytecode and pytest cache files from the release archive.

## Local verification

Run from the repository root:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q backend one_rupee scripts tests
```

The Stage 12 archive was checked with the local test suite. These tests use a fake Cashfree client and mocked external services; they are not live payment or Supabase acceptance tests.

## Required external acceptance tests before production

1. Apply `backend/migrations/001_initial_schema.sql` and then `002_payment_integrity.sql` to the intended Supabase project.
2. Configure Render environment variables using `.env.example` as a guide. Never commit real credentials.
3. Run `python scripts/production_preflight.py` with the production database and Storage configuration.
4. Complete a Cashfree **sandbox** payment through the deployed `/pay` page.
5. Confirm Cashfree sends a webhook to `/webhooks/cashfree`, and confirm a repeated delivery does not create another member.
6. Confirm the certificate object is uploaded to the configured private Storage bucket and its signed URL works.
7. Run `python scripts/deployment_smoke_test.py https://YOUR-RENDER-SERVICE.onrender.com`.
8. Test two different customers and concurrent duplicate notifications in the sandbox environment.
9. Review Cashfree domain whitelisting, webhook configuration, Supabase RLS, database backups, and Render service settings before enabling production credentials.

## Important limitations

- The repository's automated tests do not prove that the user's live Supabase, Cashfree, or Render accounts are configured correctly.
- The production preflight checks PostgreSQL schema and Storage bucket reachability; it does not perform a Cashfree payment or upload a certificate.
- Local certificate files are temporary working artifacts when Supabase Storage is enabled. Persistent hosted delivery depends on the Storage upload succeeding.
- Do not enable production payments until the external acceptance tests above have passed.
- A public certificate bucket makes certificates accessible to anyone with the object URL. Prefer a private bucket and short-lived signed URLs unless public access is an explicit product decision.

## Release status

**Code-level release candidate; external production acceptance still required.** Do not describe the service as production-ready solely on the basis of local tests.
