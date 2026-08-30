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
| `http://<LAN_IP>:8000/health` | Health check |
| `http://<LAN_IP>:8000/certificate/<order_id>` | Verified member certificate |

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CASHFREE_APP_ID` | *(required)* | Cashfree App ID |
| `CASHFREE_SECRET_KEY` | *(required)* | Cashfree Secret Key |
| `CASHFREE_ENV` | `sandbox` | `sandbox` or `production` |
| `ONE_RUPEE_HOST` | *(auto-detected)* | Override LAN IP |
| `ONE_RUPEE_PORT` | `8000` | Server port |
| `ONE_RUPEE_BASE_URL` | *(auto-generated)* | Full base URL override |

## 🔒 Security

- Credentials are loaded from environment variables only
- Secret keys are never printed or logged
- `.env` is in `.gitignore`
- Membership only activates after server-side Cashfree `PGFetchOrder` returns
  `PAID` for the matching ₹1 INR order
- The local payment ledger and member insert are written in one SQLite
  transaction, so duplicate return requests cannot create duplicate members
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
