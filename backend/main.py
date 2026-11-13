from decimal import Decimal, InvalidOperation
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from html import escape
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uuid
import base64
import hashlib
import hmac
import json
import os
import requests
from pydantic import BaseModel, Field

from backend.config import (
    CASHFREE_APP_ID,
    CASHFREE_SECRET_KEY,
    CASHFREE_ENV,
    BASE_URL,
    SERVER_PORT,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    CERTIFICATE_STORAGE,
)

import warnings

# Keep the known Cashfree sandbox TLS warning out of normal library output.
warnings.filterwarnings(
    "ignore",
    message=r"Unverified HTTPS request is being made to host 'sandbox\.cashfree\.com'",
    category=Warning,
)

try:
    from cashfree_pg.api_client import Cashfree
    from cashfree_pg.models.create_order_request import CreateOrderRequest
    from cashfree_pg.models.customer_details import CustomerDetails
    from cashfree_pg.models.order_meta import OrderMeta
except ImportError:  # Allows SQLite-only development and unit tests without SDK.
    from types import SimpleNamespace

    class Cashfree:
        SANDBOX = "SANDBOX"
        PRODUCTION = "PRODUCTION"

        def __init__(self, **kwargs):
            self.configuration = kwargs

        def __getattr__(self, name):
            if name.startswith("PG"):
                def unavailable(*args, **kwargs):
                    raise RuntimeError(
                        "Cashfree SDK is not installed. Install project dependencies."
                    )
                return unavailable
            raise AttributeError(name)

    class CustomerDetails:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class OrderMeta:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class CreateOrderRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

from backend.database import (
    init_db,
    create_payment,
    get_payment_by_order_id,
    confirm_verified_payment_and_activate,
    is_order_already_activated,
    set_certificate_path,
    get_latest_activated_payment_for_customer,
    get_connection,
)
from backend.certificates import generate_certificate


PAYMENT_PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"


# ============================================================
# APP
# ============================================================

@asynccontextmanager
async def lifespan(_app):
    """Initialize the configured database when the API process starts."""
    init_db()
    yield


app = FastAPI(
    title="One Rupee API",
    version="0.4.3",
    lifespan=lifespan,
)


# ============================================================
# CORS  (needed if frontend is ever served from different origin)
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{SERVER_PORT}",
        f"http://127.0.0.1:{SERVER_PORT}",
        BASE_URL,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CASHFREE CONFIGURATION
# ============================================================

if CASHFREE_ENV.lower() == "production":

    cashfree = Cashfree(
        XEnvironment=Cashfree.PRODUCTION,
        XClientId=CASHFREE_APP_ID,
        XClientSecret=CASHFREE_SECRET_KEY
    )

else:

    cashfree = Cashfree(
        XEnvironment=Cashfree.SANDBOX,
        XClientId=CASHFREE_APP_ID,
        XClientSecret=CASHFREE_SECRET_KEY
    )


# ============================================================
# BASIC ENDPOINTS
# ============================================================

@app.get("/")
def home():
    return {
        "message": "One Rupee API is running 🪙"
    }


@app.get("/health")
def health():
    """Liveness probe: the API process is responding."""
    return {"status": "ok"}


@app.get("/ready")
def readiness():
    """Readiness probe: confirm the configured database is reachable."""
    connection = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return {"status": "ready", "database": "reachable"}
    except Exception as error:
        # Do not return connection strings or driver details to public callers.
        raise HTTPException(status_code=503, detail="Database is unavailable.") from error
    finally:
        if connection is not None:
            connection.close()


# ============================================================
# PAYMENT REQUEST MODEL  (preserved for backwards compatibility)
# ============================================================


class PaymentRequest(BaseModel):

    customer_id: str = Field(
        min_length=10,
        max_length=80,
        pattern=r"^one_rupee_install_[0-9a-f]{32}$|^web_[0-9a-f-]{36}$",
    )
    customer_phone: str = Field(
        min_length=10,
        max_length=15,
        pattern=r"^[0-9]{10,15}$",
    )
    customer_name: str | None = Field(
        default=None,
        max_length=100,
    )


# ============================================================
# CREATE ₹1 CASHFREE PAYMENT ORDER
# ============================================================

@app.post("/create-payment")
def create_payment_endpoint(request: PaymentRequest):

    # --------------------------------------------------------
    # Check Cashfree credentials
    # --------------------------------------------------------

    if not CASHFREE_APP_ID:

        raise HTTPException(
            status_code=500,
            detail="CASHFREE_APP_ID is not configured"
        )

    if not CASHFREE_SECRET_KEY:

        raise HTTPException(
            status_code=500,
            detail="CASHFREE_SECRET_KEY is not configured"
        )


    # --------------------------------------------------------
    # Generate unique order ID
    # --------------------------------------------------------

    order_id = (
        "one_rupee_"
        + uuid.uuid4().hex[:20]
    )


    # --------------------------------------------------------
    # Customer information
    # --------------------------------------------------------

    customer_details = CustomerDetails(
        customer_id=request.customer_id,
        customer_phone=request.customer_phone,
        customer_name=request.customer_name.strip() if request.customer_name else None,
    )


    # --------------------------------------------------------
    # Return URL  (must use LAN IP for phone access)
    # --------------------------------------------------------

    return_url = f"{BASE_URL}/payment-return?{urlencode({'order_id': order_id})}"

    order_meta = OrderMeta(
        return_url=return_url
    )


    # --------------------------------------------------------
    # Create ₹1 order
    # --------------------------------------------------------

    order_request = CreateOrderRequest(
        order_id=order_id,
        order_amount=1.00,
        order_currency="INR",
        customer_details=customer_details,
        order_meta=order_meta
    )


    # --------------------------------------------------------
    # Send order to Cashfree
    # --------------------------------------------------------

    try:
        response = cashfree.PGCreateOrder(
            order_request,
            None,
            None
        )

        data = response.data

        # Persist the exact Cashfree order id, never a value inferred from the
        # browser.  A mismatch would make later verification ambiguous.
        if data.order_id != order_id:
            raise RuntimeError(
                "Cashfree returned an unexpected order id "
                f"({data.order_id!r} instead of {order_id!r})"
            )

        # Record payment in our database
        create_payment(
            order_id=order_id,
            customer_id=request.customer_id,
            customer_phone=request.customer_phone,
            customer_name=request.customer_name.strip()
                if request.customer_name
                else None,
            amount=1.00,
            currency="INR",
        )
        return {
            "success": True,
            "order_id": data.order_id,
            "payment_session_id": data.payment_session_id,
            "order_amount": data.order_amount,
            "order_currency": data.order_currency
        }

    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to create the payment. Please try again.") from error


# ============================================================
# PAYMENT PAGE  (serves the frontend)
# ============================================================

@app.get("/pay")
def payment_page(
    customer_id: str | None = None,
    name: str | None = None,
):
    page = PAYMENT_PAGE_PATH.read_text(
        encoding="utf-8"
    )

    page = page.replace(
        "__CASHFREE_MODE__",
        CASHFREE_ENV,
    )

    page = page.replace(
        "__CUSTOMER_ID__",
        escape(customer_id or ""),
    )

    page = page.replace(
        "__CUSTOMER_NAME__",
        escape(name or ""),
    )

    return HTMLResponse(content=page)


# ============================================================
# PAYMENT RETURN  (Cashfree redirects here after payment)
# ============================================================

@app.get("/payment-return")
def payment_return(order_id: str):

    print()
    # Cashfree should return the same order id that was sent in return_url.
    # Do not call its API for an unknown local order: it cannot activate a
    # membership in this installation and the local mismatch is actionable.
    payment = get_payment_by_order_id(order_id)
    if payment is None:
        print("   ❌ Return order is not present in the local payment ledger")
        return HTMLResponse(
            content=failure_page_html(
                order_id=order_id,
                reason="This payment order is not known to this One Rupee server.",
            ),
            status_code=404,
        )

    # --------------------------------------------------------
    # Check if already activated (idempotency)
    # --------------------------------------------------------

    if is_order_already_activated(order_id):
        certificate_path = ensure_certificate(payment)
        member_id = payment["member_id"]
        return HTMLResponse(content=success_page_html(
            order_id=order_id,
            member_id=str(member_id),
            certificate_url=certificate_url_for(order_id, certificate_path),
            already=True,
        ))


    # --------------------------------------------------------
    # Verify payment with Cashfree
    # --------------------------------------------------------

    try:
        # PGFetchOrder signature: (self, order_id, x_request_id, x_idempotency_key)
        response = cashfree.PGFetchOrder(
            order_id,
            None,
            None
        )

        data = response.data
        order_status = data.order_status

        if data.order_id != order_id:
            raise RuntimeError(
                "Cashfree verification returned a different order id "
                f"({data.order_id!r} instead of {order_id!r})"
            )

        if not is_expected_one_rupee_order(
            data,
            expected_customer_id=payment["customer_id"],
        ):
            raise RuntimeError(
                "Cashfree verification returned an unexpected order, amount, or currency"
            )
    except Exception as error:
        return HTMLResponse(content=failure_page_html(
            order_id=order_id,
            reason="Unable to verify payment with Cashfree. Please try again."
        ), status_code=500)


    # --------------------------------------------------------
    # Handle payment status
    # --------------------------------------------------------

    if order_status == "PAID":
        cashfree_payment_id = get_successful_cashfree_payment_id(order_id)
        member_id, newly_activated = confirm_verified_payment_and_activate(
            order_id,
            cashfree_payment_id,
        )
        payment = get_payment_by_order_id(order_id)
        certificate_path = ensure_certificate(payment)


        return HTMLResponse(content=success_page_html(
            order_id=order_id,
            member_id=str(member_id),
            certificate_url=certificate_url_for(order_id, certificate_path),
        ))

    elif order_status in ("ACTIVE", "PENDING"):
        return HTMLResponse(content=pending_page_html(
            order_id=order_id,
        ))

    else:
        # FAILED, USER_DROPPED, EXPIRED, etc.
        return HTMLResponse(content=failure_page_html(
            order_id=order_id,
            reason=f"Payment status: {order_status}"
        ))

def verify_cashfree_webhook_signature(raw_body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    """Return whether Cashfree's signature matches the exact raw request body.

    Do not parse/re-serialize JSON before verification: whitespace and key order
    are part of the signed payload.
    """
    if not raw_body or not timestamp or not signature or not secret:
        return False
    signed_payload = timestamp.encode("utf-8") + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


@app.post("/webhooks/cashfree")
async def cashfree_webhook(request: Request):
    """Verify Cashfree webhook authenticity, then independently verify its order.

    Cashfree signs timestamp + raw request body using the PG secret key. The
    webhook is only a notification; PGFetchOrder remains the source of truth.
    """
    raw_body = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")
    if not timestamp or not signature or not CASHFREE_SECRET_KEY:
        raise HTTPException(status_code=400, detail="Missing webhook signature headers.")
    if not verify_cashfree_webhook_signature(
        raw_body, timestamp, signature, CASHFREE_SECRET_KEY
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    try:
        payload = json.loads(raw_body)
        order_data = payload.get("data", {}).get("order", {})
        order_id = order_data.get("order_id") or payload.get("data", {}).get("order_id")
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    if not order_id:
        raise HTTPException(status_code=400, detail="Webhook does not contain an order ID.")
    payment = get_payment_by_order_id(order_id)
    if payment is None:
        # Unknown order: acknowledge only after valid signature; it cannot activate a member.
        return {"received": True, "activated": False}
    try:
        verified = cashfree.PGFetchOrder(order_id, None, None).data
    except Exception as error:
        raise HTTPException(status_code=503, detail="Could not verify order with Cashfree.") from error
    if (getattr(verified, "order_id", None) != order_id or
        not is_expected_one_rupee_order(verified, expected_customer_id=payment["customer_id"])):
        raise HTTPException(status_code=400, detail="Cashfree order details do not match the payment record.")
    if getattr(verified, "order_status", None) != "PAID":
        return {"received": True, "activated": False, "status": getattr(verified, "order_status", "UNKNOWN")}
    payment_id = get_successful_cashfree_payment_id(order_id)
    confirm_verified_payment_and_activate(order_id, payment_id)
    activated = get_payment_by_order_id(order_id)
    certificate_path = ensure_certificate(activated)
    return {"received": True, "activated": True, "certificate_url": certificate_url_for(order_id, certificate_path)}


@app.get("/certificates/{filename}")
def serve_certificate(filename: str):
    """Serve a verified member certificate."""

    certificate_dir = Path.home() / ".one_rupee" / "certificates"

    # Prevent path traversal
    safe_filename = Path(filename).name

    certificate_path = certificate_dir / safe_filename

    if not certificate_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Certificate not found.",
        )

    if certificate_path.suffix.lower() != ".pdf":
        raise HTTPException(
        status_code=404,
        detail="Invalid certificate.",
        )

    return FileResponse(
        path=certificate_path,
        media_type="application/pdf",
        filename=safe_filename,
    )

@app.get("/membership-status/{customer_id}")
def membership_status(customer_id: str):
    """Small polling endpoint used only by the local public claim() flow."""
    payment = get_latest_activated_payment_for_customer(customer_id)

    if payment is None:
        return {"status": "waiting"}

    certificate_path = ensure_certificate(payment)
    return {
    "status": "activated",
    "member_id": payment["member_id"],
    "name": (
        payment.get("member_name")
        or payment.get("customer_name")
    ),
    "order_id": payment["order_id"],
    "certificate_url": certificate_url_for(
        payment["order_id"],
        certificate_path,
    ),
    "certificate_path": certificate_path,
    }


@app.get("/certificate/{order_id}")
def certificate(order_id: str):
    payment = get_payment_by_order_id(order_id)
    if payment is None or payment["member_id"] is None:
        raise HTTPException(status_code=404, detail="Verified certificate not found")

    certificate_path = ensure_certificate(payment)
    if str(certificate_path).startswith(("https://", "http://")):
        return RedirectResponse(certificate_path)
    return FileResponse(
        certificate_path,
        media_type="application/pdf",
        filename=Path(certificate_path).name,
    )

class PaymentVerificationError(RuntimeError):
    """A stored local receipt could not be verified with Cashfree."""


def verify_existing_membership_for_installation(installation_id):
    """Return a re-verified membership for one library installation, if any.

    A local database record is never enough by itself.  Repeated claim() calls
    use this function to confirm the original Cashfree order is still PAID and
    belongs to the same installation-specific customer id.
    """
    init_db()
    payment = get_latest_activated_payment_for_customer(installation_id)
    if payment is None:
        return None

    try:
        response = cashfree.PGFetchOrder(payment["order_id"], None, None)
        order = response.data
    except Exception as error:
        raise PaymentVerificationError(
            "Unable to re-verify the existing payment with Cashfree. "
            "Check the terminal diagnostics and try again."
        ) from error

    if (
        getattr(order, "order_status", None) != "PAID"
        or getattr(order, "order_id", None) != payment["order_id"]
        or not is_expected_one_rupee_order(
            order,
            expected_customer_id=installation_id,
        )
    ):
        return None

    certificate_path = ensure_certificate(payment)
    return {
        "status": "activated",
        "member_id": payment["member_id"],
        "name": payment.get("member_name") or payment.get("customer_name"),
        "order_id": payment["order_id"],
        "certificate_path": certificate_path,
    }


def _customer_id_from_order(order_data):
    customer = getattr(order_data, "customer_details", None)
    if isinstance(customer, dict):
        return customer.get("customer_id")
    return getattr(customer, "customer_id", None)


def is_expected_one_rupee_order(order_data, expected_customer_id=None):
    """Validate the fields that authorize a ₹1 membership activation."""
    try:
        amount = Decimal(str(order_data.order_amount))
    except (AttributeError, InvalidOperation, ValueError):
        return False

    if amount != Decimal("1.00") or getattr(order_data, "order_currency", None) != "INR":
        return False

    if expected_customer_id is not None:
        return _customer_id_from_order(order_data) == expected_customer_id
    return True


def get_successful_cashfree_payment_id(order_id: str):
    """Record Cashfree's payment id when available, without trusting it alone."""
    try:
        response = cashfree.PGOrderFetchPayments(order_id, None, None)
        payments = response.data or []
        for payment in reversed(payments):
            if getattr(payment, "payment_status", None) == "SUCCESS":
                return getattr(payment, "cf_payment_id", None)
    except Exception:
        # PGFetchOrder already returned PAID, so the extra payment-id lookup is
        # optional ledger metadata and must not block activation.
        pass
    return None


def ensure_certificate(payment):
    """Create a verified member certificate and optionally upload it to Storage.

    A local copy is retained as a temporary working artifact. When Supabase
    Storage is enabled, upload is attempted even if that local copy already
    exists; this fixes upgrades where an earlier run generated the file before
    persistent storage was configured. Signed URLs are minted on demand and
    are deliberately not persisted because they expire.
    """
    if payment is None or payment.get("member_id") is None:
        return None

    existing_path = payment.get("certificate_path")
    if existing_path and Path(existing_path).is_file():
        certificate_path = existing_path
    else:
        certificate_path = generate_certificate(
            payment["member_id"],
            payment["order_id"],
            payment.get("member_name") or payment.get("customer_name"),
        )
        set_certificate_path(payment["order_id"], certificate_path)

    if CERTIFICATE_STORAGE.lower() != "supabase":
        return certificate_path

    bucket = os.getenv("SUPABASE_CERTIFICATE_BUCKET", "certificates").strip()
    if not bucket:
        raise RuntimeError("SUPABASE_CERTIFICATE_BUCKET cannot be empty.")
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Supabase certificate storage requires SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY."
        )

    filename = Path(certificate_path).name
    object_path = f"members/{filename}"
    encoded_bucket = quote(bucket, safe="")
    encoded_object = quote(object_path, safe="/")
    storage_root = f"{SUPABASE_URL.rstrip('/')}/storage/v1"
    endpoint = f"{storage_root}/object/{encoded_bucket}/{encoded_object}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/pdf",
        "x-upsert": "true",
    }
    with open(certificate_path, "rb") as certificate_file:
        response = requests.put(endpoint, headers=headers, data=certificate_file, timeout=20)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Supabase Storage upload failed ({response.status_code}).")

    public_access = os.getenv("SUPABASE_CERTIFICATE_PUBLIC", "false").strip().lower() in {"1", "true", "yes"}
    if public_access:
        return f"{storage_root}/object/public/{encoded_bucket}/{encoded_object}"

    signed_endpoint = f"{storage_root}/object/sign/{encoded_bucket}/{encoded_object}"
    signed_response = requests.post(
        signed_endpoint,
        headers={
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Content-Type": "application/json",
        },
        json={"expiresIn": 3600},
        timeout=20,
    )
    if signed_response.status_code not in (200, 201):
        raise RuntimeError(
            f"Supabase signed certificate URL failed ({signed_response.status_code})."
        )
    signed_path = signed_response.json().get("signedURL")
    if not signed_path:
        raise RuntimeError("Supabase did not return a signed certificate URL.")
    if signed_path.startswith(("http://", "https://")):
        return signed_path
    if signed_path.startswith("/storage/v1/"):
        return f"{SUPABASE_URL.rstrip('/')}{signed_path}"
    return f"{storage_root}{signed_path if signed_path.startswith('/') else '/' + signed_path}"


def certificate_url_for(order_id, certificate_path=None):
    if not certificate_path:
        return None
    if str(certificate_path).startswith(("https://", "http://")):
        return certificate_path
    filename = Path(certificate_path).name
    return f"/certificates/{quote(filename)}"


# ============================================================
# HTML PAGES
# ============================================================

def success_page_html(
    order_id: str,
    member_id: str,
    certificate_url: str = None,
    already: bool = False,
):
    already_note = "<p class='already'>⚠️ Relax, you already activated this. We don't do double-dipping.</p>" if already else ""
    certificate_note = (
        f"<a class='certificate-link' href='{certificate_url}'>📜 View / print your certificate</a>"
        if certificate_url else ""
    )

    # Funny one-liners for the success page
    jokes = [
        "You just mass₹ the art of spending ₹1.",
        "Elon has mass, you have member pass.",
        "₹1 spent. Financial advisor in shambles.",
        "Your bank statement now has a ₹1 mystery line.",
        "This is the most exclusive ₹1 club in India.",
        "Warren Buffett wishes he got in this early.",
        "You're now richer in experience, poorer by ₹1.",
        "This ₹1 has more purpose than most ₹500 notes.",
    ]

    # Pick a joke based on member_id for consistency
    try:
        joke_index = int(member_id) % len(jokes)
    except (ValueError, TypeError):
        joke_index = 0
    joke = jokes[joke_index]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YOU DID IT! 🎉🪙</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow: hidden;
        }}
        .confetti {{
            position: fixed;
            top: -10px;
            font-size: 24px;
            animation: fall linear forwards;
            z-index: 0;
        }}
        @keyframes fall {{
            to {{ transform: translateY(110vh) rotate(720deg); opacity: 0; }}
        }}
        .card {{
            background: white;
            border-radius: 24px;
            padding: 40px 30px;
            max-width: 440px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
            position: relative;
            z-index: 1;
            animation: popIn 0.6s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }}
        @keyframes popIn {{
            0% {{ transform: scale(0.3) rotate(-10deg); opacity: 0; }}
            100% {{ transform: scale(1) rotate(0deg); opacity: 1; }}
        }}
        .mega-icon {{
            font-size: 80px;
            margin-bottom: 12px;
            animation: bounce 1s ease infinite;
        }}
        @keyframes bounce {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-15px); }}
        }}
        h1 {{
            font-size: 32px;
            color: #1a1a2e;
            margin-bottom: 4px;
            font-weight: 900;
        }}
        .subtitle {{
            font-size: 18px;
            color: #555;
            margin-bottom: 8px;
        }}
        .joke {{
            font-size: 15px;
            color: #888;
            font-style: italic;
            margin-bottom: 24px;
            line-height: 1.4;
        }}
        .member-reveal {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 16px;
            padding: 20px;
            margin: 16px 0;
            animation: glow 2s ease-in-out infinite alternate;
        }}
        @keyframes glow {{
            from {{ box-shadow: 0 0 10px rgba(102, 126, 234, 0.3); }}
            to {{ box-shadow: 0 0 25px rgba(102, 126, 234, 0.6); }}
        }}
        .member-label {{
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 2px;
            opacity: 0.8;
            margin-bottom: 6px;
        }}
        .member-number {{
            font-size: 48px;
            font-weight: 900;
            letter-spacing: 2px;
        }}
        .detail {{
            background: #f8f9fa;
            border-radius: 12px;
            padding: 14px 16px;
            margin: 12px 0;
            text-align: left;
        }}
        .detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            font-size: 13px;
        }}
        .detail-label {{ color: #aaa; }}
        .detail-value {{ color: #333; font-weight: 600; word-break: break-all; }}
        .badge {{
            display: inline-block;
            background: #d4edda;
            color: #155724;
            font-size: 15px;
            padding: 10px 24px;
            border-radius: 50px;
            margin-top: 20px;
            font-weight: 700;
            animation: pulse 2s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
        }}
        .already {{
            color: #856404;
            background: #fff3cd;
            border-radius: 12px;
            padding: 10px 14px;
            font-size: 14px;
            margin-bottom: 16px;
        }}
        .footer {{
            margin-top: 20px;
            font-size: 12px;
            color: #bbb;
        }}
        .certificate-link {{
            display: inline-block;
            margin-top: 18px;
            color: white;
            background: #4b187d;
            border-radius: 50px;
            padding: 11px 18px;
            font: 700 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="mega-icon">🪙</div>
        <h1>PAYMENT SUCCESSFUL!</h1>
        <p class="subtitle">₹1 paid. Enormous membership status: unlocked.</p>
        <p class="joke">"{joke}"</p>
        {already_note}
        <div class="member-reveal">
            <div class="member-label">Your Member Number</div>
            <div class="member-number">#{member_id}</div>
        </div>
        <div class="detail">
            <div class="detail-row">
                <span class="detail-label">Amount Paid</span>
                <span class="detail-value">₹1.00 (yes, really)</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Order</span>
                <span class="detail-value">{order_id}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Status</span>
                <span class="detail-value">✅ VERIFIED & ACTIVATED</span>
            </div>
        </div>
        <div class="badge">🎖️ Official One Rupee Member</div>
        {certificate_note}
        <p class="footer">Screenshot this. Frame it. Tell your grandchildren.</p>
    </div>

    <script>
        // Confetti explosion!
        const emojis = ['🎉', '🪙', '✨', '💰', '🎊', '⭐', '🥳', '💎'];
        for (let i = 0; i < 40; i++) {{
            const el = document.createElement('div');
            el.className = 'confetti';
            el.textContent = emojis[Math.floor(Math.random() * emojis.length)];
            el.style.left = Math.random() * 100 + 'vw';
            el.style.animationDuration = (2 + Math.random() * 3) + 's';
            el.style.animationDelay = (Math.random() * 2) + 's';
            document.body.appendChild(el);
        }}
    </script>
</body>
</html>"""


def failure_page_html(order_id: str, reason: str = ""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Failed</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 24px;
            padding: 40px 30px;
            max-width: 420px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
        }}
        .icon {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ font-size: 28px; color: #1a1a2e; margin-bottom: 8px; }}
        .subtitle {{ font-size: 16px; color: #555; margin-bottom: 24px; }}
        .reason {{
            background: #fff3cd;
            border-radius: 12px;
            padding: 12px 16px;
            font-size: 14px;
            color: #856404;
            margin-bottom: 20px;
        }}
        .retry-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px 40px;
            font-size: 18px;
            font-weight: 700;
            border-radius: 50px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">💸</div>
        <h1>PAYMENT NOT COMPLETED</h1>
        <p class="subtitle">No membership was created.</p>
        <div class="reason">{escape(reason)}</div>
        <p style="font-size:13px; color:#888; margin-bottom:12px;">Order: {escape(order_id)}</p>
        <a href="/pay" class="retry-btn">Try Again</a>
    </div>
</body>
</html>"""


def pending_page_html(order_id: str):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Pending</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 24px;
            padding: 40px 30px;
            max-width: 420px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
        }}
        .icon {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ font-size: 28px; color: #1a1a2e; margin-bottom: 8px; }}
        .subtitle {{ font-size: 16px; color: #555; margin-bottom: 24px; }}
    </style>
    <script>
        // Auto-refresh every 5 seconds to check if payment completed
        setTimeout(function() {{ window.location.reload(); }}, 5000);
    </script>
</head>
<body>
    <div class="card">
        <div class="icon">⏳</div>
        <h1>Payment Pending</h1>
        <p class="subtitle">Your payment is being processed...</p>
        <p style="font-size:14px; color:#888; margin-top:16px;">
            This page will refresh automatically.
        </p>
        <p style="font-size:13px; color:#aaa; margin-top:12px;">Order: {order_id}</p>
    </div>
</body>
</html>"""
