# Stage 11 — Cashfree sandbox and deployment verification

Stage 11 adds a read-only diagnostic for looking up an existing Cashfree
**sandbox** order. It does not create orders, start checkout, or charge a user.
The live test still requires your own Cashfree sandbox credentials and a real
sandbox order created through the deployed One Rupee payment page.

## 1. Deploy and check Render

Set the Render environment variables documented in `PRODUCTION_CHECKLIST.md`.
After deployment, run:

```powershell
python scripts/deployment_smoke_test.py https://YOUR-RENDER-SERVICE.onrender.com
```

Both `/health` and `/ready` must pass. A failure of `/ready` means the service
cannot currently reach its configured database; do not proceed to checkout.

## 2. Verify an existing Cashfree sandbox order

Set these variables in the current PowerShell session (do not commit them):

```powershell
$env:CASHFREE_ENV = "sandbox"
$env:CASHFREE_APP_ID = "YOUR_SANDBOX_APP_ID"
$env:CASHFREE_SECRET_KEY = "YOUR_SANDBOX_SECRET"
```

Create a sandbox order from the deployed `/pay` page and copy its order ID.
Then run:

```powershell
python scripts/cashfree_order_check.py YOUR_ORDER_ID
```

For an order you have completed successfully in the sandbox, additionally run:

```powershell
python scripts/cashfree_order_check.py YOUR_ORDER_ID --expect-paid
```

The script fetches the existing order using Cashfree's server-side order-fetch
API and checks that its amount is exactly `1.00 INR`. It is restricted to
`sandbox` to reduce the risk of accidentally querying a live transaction. It
never prints credentials or customer details.

## 3. End-to-end acceptance checklist

- [ ] Render `/health` and `/ready` both return HTTP 200.
- [ ] `/pay` loads over HTTPS.
- [ ] Cashfree sandbox checkout opens successfully.
- [ ] A completed sandbox order reports `PAID` and exactly `1.00 INR`.
- [ ] The application independently fetches and verifies the order before activation.
- [ ] Exactly one member and certificate are created for the order.
- [ ] Replaying the webhook and refreshing the return page does not create another member.
- [ ] Failed, pending, and cancelled orders do not create a member or certificate.
- [ ] The certificate remains available after a Render restart/redeploy.

A successful local `pytest` run tests code paths with mocks; it does not prove
that your Render, Supabase, or Cashfree accounts are configured correctly.
Do not enable production credentials until every acceptance item has been
verified against the sandbox deployment.
