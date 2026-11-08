"""Read-only Cashfree order verification for a known sandbox order.

This script fetches an existing order; it never creates an order or charges a
customer. Set CASHFREE_APP_ID, CASHFREE_SECRET_KEY and CASHFREE_ENV=sandbox,
then pass the order ID returned by the One Rupee payment flow.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation

import requests

API_VERSION = os.getenv("CASHFREE_API_VERSION", "2023-08-01")
BASE_URLS = {
    "sandbox": "https://sandbox.cashfree.com/pg",
    "production": "https://api.cashfree.com/pg",
}


def fetch_order(order_id: str, app_id: str, secret: str, environment: str, timeout: float = 15.0):
    """Fetch an existing Cashfree order; returns sanitized order fields only."""
    if environment not in BASE_URLS:
        raise ValueError("CASHFREE_ENV must be sandbox or production")
    response = requests.get(
        f"{BASE_URLS[environment]}/orders/{order_id}",
        headers={
            "x-client-id": app_id,
            "x-client-secret": secret,
            "x-api-version": API_VERSION,
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Cashfree returned HTTP {response.status_code}")
    payload = response.json()
    try:
        amount = Decimal(str(payload["order_amount"]))
        currency = str(payload["order_currency"])
        status = str(payload["order_status"])
        returned_order_id = str(payload["order_id"])
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise RuntimeError("Cashfree response is missing required order fields") from exc
    return {
        "order_id": returned_order_id,
        "amount": amount,
        "currency": currency,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id", help="Existing One Rupee Cashfree order ID")
    parser.add_argument("--expect-paid", action="store_true", help="Fail unless Cashfree reports PAID")
    args = parser.parse_args()

    app_id = os.getenv("CASHFREE_APP_ID", "").strip()
    secret = os.getenv("CASHFREE_SECRET_KEY", "").strip()
    environment = os.getenv("CASHFREE_ENV", "sandbox").strip().lower()
    if not app_id or not secret:
        print("FAIL: CASHFREE_APP_ID and CASHFREE_SECRET_KEY must be configured.")
        return 2
    if environment != "sandbox":
        print("FAIL: This diagnostic is restricted to CASHFREE_ENV=sandbox.")
        return 2
    try:
        order = fetch_order(args.order_id, app_id, secret, environment)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"FAIL: Cashfree order lookup failed ({type(exc).__name__}): {exc}")
        return 1

    print(f"Order ID: {order['order_id']}")
    print(f"Amount: {order['amount']:.2f} {order['currency']}")
    print(f"Status: {order['status']}")
    if order["amount"] != Decimal("1.00") or order["currency"] != "INR":
        print("FAIL: Order is not exactly INR 1.00.")
        return 1
    if args.expect_paid and order["status"] != "PAID":
        print("FAIL: Cashfree has not reported PAID.")
        return 1
    print("PASS: Existing sandbox order matches the One Rupee amount and currency.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
