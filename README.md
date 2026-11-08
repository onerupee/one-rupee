# 🪙 ONE RUPEE

**A Python library that runs one verified ₹1 membership claim.**

`one_rupee` hides the FastAPI server, QR code, Cashfree checkout, payment
verification, database, and certificate behind one public function.

## 🚀 Quick Start

### 1. Set Cashfree Credentials

In PowerShell:

```powershell
$env:CASHFREE_APP_ID = "YOUR_SANDBOX_APP_ID"
$env:CASHFREE_SECRET_KEY = "YOUR_SANDBOX_SECRET_KEY"
$env:CASHFREE_ENV = "sandbox"
```

### 2. Install the library

```bash
pip install one-rupee
```

For a local checkout of this repository:

```bash
pip install .
```

### 3. Claim

```python
from one_rupee import claim

member_id = claim()
```

That is the complete public API. `claim()` validates the configuration,
detects the LAN address, starts an internal server on `0.0.0.0:8000`, shows a
terminal QR, waits for server-side Cashfree verification, generates a
certificate, then shuts down the server it started. It returns the member
number, or `None` when the claim does not complete.

### 4. Scan & Pay

1. Open your phone (same Wi-Fi network)
2. Scan the terminal QR code
3. Tap **Pay ₹1**
4. Complete the Cashfree Sandbox payment
5. Use OTP: **111000**
6. See your membership activated! 🎉

---

## 📱 Payment Flow

```
Terminal QR  →  /pay page  →  Cashfree Checkout  →  OTP 111000
     →  /payment-return  →  Backend verifies  →  Membership activated!
     →  Individual printable certificate
```

## 🌐 URLs

| URL | Description |
|-----|-------------|
| `http://<LAN_IP>:8000/pay` | Payment page (scan with phone) |
| `http://<LAN_IP>:8000/health` | Liveness check (API process) |
| `http://<LAN_IP>:8000/ready` | Readiness check (database connection) |
| `http://<LAN_IP>:8000/certificates/<filename>` | Verified member certificate |

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CASHFREE_APP_ID` | *(required)* | Cashfree App ID |
| `CASHFREE_SECRET_KEY` | *(required)* | Cashfree Secret Key |
| `CASHFREE_ENV` | `sandbox` | `sandbox` or `production` |
| `ONE_RUPEE_HOST` | *(auto-detected)* | Override LAN IP |
| `ONE_RUPEE_PORT` | `8000` | Server port |
| `ONE_RUPEE_BASE_URL` | *(auto-generated)* | Public/reachable full base URL |
| `DATABASE_URL` | *(unset)* | Optional PostgreSQL connection string; when set, PostgreSQL is used instead of local SQLite |

## 🔒 Security

- Credentials are loaded from environment variables only
- Secret keys are never printed or logged
- `.env` is in `.gitignore`
- Membership only activates after server-side Cashfree `PGFetchOrder` returns
  `PAID` for the matching ₹1 INR order
- The payment ledger and member insert are performed transactionally. SQLite
  uses an immediate write transaction; PostgreSQL locks the payment row before
  activation. A unique partial index also prevents one member record from being
  attached to multiple payment rows.
- The Cashfree payment id (when available) and a deterministic certificate path
  are stored with the verified payment
- Each installed copy has an installation-specific Cashfree customer id. On a
  repeat `claim()`, the stored receipt is re-verified with Cashfree before the
  existing member is returned; no new order, payment, member, or certificate is
  created.
- A normal uninstall followed by reinstall creates a fresh installation marker and a new installation id. Persistent payment data remains under `~/.one_rupee`, so earlier members remain recorded without being reused by the new installation.

Development-only member-creation endpoints are not included in the published payment flow.

## 💾 Local Data

Runtime payment data, certificates, and the optional local receipt are stored
under:

```text
~/.one_rupee/
```

This keeps payment history outside the installed package. A normal
uninstall/reinstall removes the package's installation marker and therefore
creates a new installation identity while preserving the old payment history.

## 🏗️ Project Structure

```
one-rupee/
├── pyproject.toml          # Installable package metadata
├── run.py                  # Development wrapper around claim()
├── .gitignore
├── .github/workflows/tests.yml  # CI test workflow
├── backend/
│   ├── __init__.py
│   ├── config.py           # Credentials, LAN IP, base URL
│   ├── database.py         # SQLite: members + payments
│   ├── certificates.py     # Verified-member certificate generator
│   ├── static/index.html   # /pay frontend page (packaged asset)
│   └── main.py             # FastAPI application
└── one_rupee/
    ├── __init__.py
    ├── claim.py            # Public claim() orchestration
    ├── qr.py               # Terminal QR code generator
    ├── cli.py               # CLI claim tool
    ├── activation.py        # Local activation state
    └── api.py               # Client API helpers
```

## 🧪 Cashfree Sandbox

- **Environment**: Sandbox
- **API URL**: `https://sandbox.cashfree.com/pg`
- **Test OTP**: `111000`
- **SDK**: `cashfree_pg` v6.0.1

## 🔧 Advanced: Manual Server Start

```bash
uvicorn backend.main:app --reload --host 0.0.0.0
```

This is only useful while developing the backend. Library users should call
`claim()` instead.

## 🐛 Troubleshooting

**Phone can't connect?**
- Ensure phone and laptop are on the same Wi-Fi
- Check Windows Firewall allows Python on private networks
- Try: `ONE_RUPEE_HOST=<your-ip> python run.py`

**Cashfree 401 Unauthorized?**
- Verify `CASHFREE_APP_ID` and `CASHFREE_SECRET_KEY` are set
- Ensure you're using Sandbox credentials

**Payment returns to localhost?**
- The return URL is auto-configured to use your LAN IP
- Set `ONE_RUPEE_BASE_URL` if auto-detection fails

**Cashfree returns `order_not_found` after checkout?**
- Confirm the terminal log's created order id is the same id logged at
  `/payment-return`; the application now rejects unknown local order ids before
  attempting activation.
- Ensure the same Sandbox credentials and `CASHFREE_ENV=sandbox` are used for
  both creation and verification. The startup log prints the environment and
  SDK API version (never the secret).
- Confirm `ONE_RUPEE_BASE_URL` is the reachable LAN URL, not `localhost`, so
  Cashfree returns the phone to the same server that created the order.


## PostgreSQL / Supabase deployment

The backend can use Supabase PostgreSQL through its direct PostgreSQL
connection string. Set `DATABASE_URL` to the connection string from your
Supabase project (use the pooler connection string if your hosting provider
requires it), then apply the SQL migrations in order in the Supabase SQL Editor:

1. `backend/migrations/001_initial_schema.sql`
2. `backend/migrations/002_payment_integrity.sql`

The second migration adds uniqueness for Cashfree payment IDs and enforces
that a membership can only be marked activated when its payment is `PAID`.
The application currently connects with `psycopg2`; the Supabase REST URL,
anon key, and service-role key are not needed for this database connection.
Never put a database password or service-role key in frontend code or Git.

For Render, configure at least:

- `CASHFREE_APP_ID`
- `CASHFREE_SECRET_KEY`
- `CASHFREE_ENV=sandbox` while testing
- `ONE_RUPEE_BASE_URL=https://<your-service>.onrender.com`
- `DATABASE_URL=<your-Supabase-PostgreSQL-connection-string>`

Build command: `pip install .`

Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

### Production verification status

The application now contains a Cashfree webhook endpoint and optional Supabase
Storage upload for certificates. These integrations have unit-level/code-path
coverage only; they have **not** been verified against your live Cashfree or
Supabase projects. The local filesystem remains the default certificate mode. The `/health` endpoint
checks process liveness; `/ready` performs a database connectivity check and
returns HTTP 503 if the database is unavailable. For hosted production, configure Supabase Storage and verify uploads and signed
URL access with a real test project before relying on certificate persistence.

Run tests locally with:

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

### Cashfree webhook

Configure the Cashfree webhook URL as:

`https://YOUR_RENDER_SERVICE/webhooks/cashfree`

Subscribe to order/payment events supported by your Cashfree account. The
endpoint validates `x-webhook-timestamp` and `x-webhook-signature` against the
raw request body using the Cashfree PG secret, then fetches the order directly
from Cashfree before activating membership. The webhook is a notification, not
payment proof by itself.

### Optional Supabase certificate storage

Create a bucket in Supabase Storage (recommended name: `certificates`). Keep
the bucket **private**. Configure `CERTIFICATE_STORAGE=supabase`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_CERTIFICATE_BUCKET`. The backend
uploads certificates and requests one-hour signed URLs. If you intentionally
want public certificates, set `SUPABASE_CERTIFICATE_PUBLIC=true`; this exposes
member names and certificate details to anyone with the URL. Keep the
service-role key server-side only. Live Supabase testing is still required.

### Hosted deployment preflight (read-only)

Before switching a hosted deployment to real payments, configure its environment
variables and run:

```bash
python scripts/production_preflight.py
```

The script checks that the public base URL uses HTTPS, PostgreSQL is reachable,
the `members` and `payments` tables exist, migration 002 created its payment-ID
uniqueness index, and the configured Supabase Storage bucket is reachable with
the server-side key. It does not create an order, write to the database, upload
a certificate, or charge a payment method. A passing preflight does not prove
that Cashfree credentials, webhook delivery, certificate upload, or checkout work;
those still require a controlled sandbox end-to-end test.

For a hosted deployment, use `CERTIFICATE_STORAGE=supabase` and a **private**
Storage bucket. Keep `SUPABASE_SERVICE_ROLE_KEY` only in the backend's secret
environment configuration. Do not use a public bucket for member certificates
unless public access is an explicit product decision.

### Stage 5 verification notes

Webhook signature verification is isolated in a unit-testable helper and tests
cover valid signatures, tampering, missing/invalid signatures, and a correctly
signed notification for an unknown order. The endpoint still independently
fetches the order from Cashfree before activation. These tests use a fake
Cashfree client; they are not a live webhook delivery test.


See [`docs/PRODUCTION_CHECKLIST.md`](docs/PRODUCTION_CHECKLIST.md) for the
ordered Supabase, Storage, Cashfree sandbox, and Render release checks.

### Deployed API smoke test

To check that a deployed service responds and its database is reachable without
creating a payment, run:

```powershell
python scripts/deployment_smoke_test.py https://YOUR-RENDER-SERVICE.onrender.com
```

This checks `/health` and `/ready` only. See
[`docs/PRODUCTION_CHECKLIST.md`](docs/PRODUCTION_CHECKLIST.md) for the manual
Cashfree sandbox acceptance procedure and the limits of this smoke test.

## Supabase schema verification (Stage 10)

After applying `backend/migrations/001_initial_schema.sql` and
`backend/migrations/002_payment_integrity.sql`, configure `DATABASE_URL` with
your Supabase PostgreSQL connection string and run:

```powershell
python scripts/supabase_integration_check.py
```

This is a read-only check of database connectivity, required columns, payment
uniqueness constraints, and RLS. It does not perform Cashfree or Storage
end-to-end tests. See `docs/STAGE10_NOTES.md`.
## Cashfree sandbox order diagnostic

After creating an existing sandbox order through the payment page, you can
verify its server-side amount, currency, and status without creating another
order:

```powershell
$env:CASHFREE_ENV = "sandbox"
$env:CASHFREE_APP_ID = "YOUR_SANDBOX_APP_ID"
$env:CASHFREE_SECRET_KEY = "YOUR_SANDBOX_SECRET"
python scripts/cashfree_order_check.py YOUR_ORDER_ID
```

See `docs/STAGE11_NOTES.md` for the deployment and end-to-end acceptance
checklist. Never commit credentials or use production credentials for sandbox
testing.

## Stage 12 release audit

The Stage 12 audit moves the installation identity marker into the per-user
`~/.one_rupee/` data directory so separate package installations do not share a
customer ID baked into the source distribution. It also aligns the package and
API version at `0.4.3`.

See [`docs/STAGE12_RELEASE_AUDIT.md`](docs/STAGE12_RELEASE_AUDIT.md) for the
final local verification commands, external acceptance tests, and release
limitations. **Local tests passing does not mean live Cashfree, Supabase, or
Render integrations have been verified.**
