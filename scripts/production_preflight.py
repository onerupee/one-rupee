"""Read-only production preflight for One Rupee.

Checks environment, PostgreSQL schema, and Supabase Storage bucket access.
It never creates a payment, writes to the database, or uploads a certificate.
Usage: python scripts/production_preflight.py
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse


def _check_database(database_url: str) -> list[str]:
    """Verify connectivity and that both application migrations are present."""
    import psycopg2

    connection = psycopg2.connect(database_url, connect_timeout=8)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                return ["PostgreSQL SELECT 1 returned an unexpected result"]
            cursor.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = current_schema()
                     AND table_name IN ('members', 'payments')"""
            )
            tables = {row[0] for row in cursor.fetchall()}
            missing = {"members", "payments"} - tables
            if missing:
                return ["Database schema is incomplete; missing table(s): " + ", ".join(sorted(missing))]
            cursor.execute(
                """SELECT indexname FROM pg_indexes
                   WHERE schemaname = current_schema()
                     AND indexname = 'uq_payments_cashfree_payment_id'"""
            )
            if cursor.fetchone() is None:
                return ["Migration 002 is missing: uq_payments_cashfree_payment_id index not found"]
        return []
    finally:
        connection.close()


def _check_storage(supabase_url: str, service_key: str, bucket: str) -> list[str]:
    """Check that the configured Storage bucket exists and is accessible."""
    import requests

    base = supabase_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc:
        return ["SUPABASE_URL must be a valid HTTPS URL"]
    try:
        response = requests.get(
            f"{base}/storage/v1/bucket/{bucket}",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=8,
        )
    except requests.RequestException as exc:
        return [f"Supabase Storage request failed ({type(exc).__name__})"]
    if response.status_code == 200:
        return []
    if response.status_code == 404:
        return [f"Supabase Storage bucket '{bucket}' was not found"]
    if response.status_code in (401, 403):
        return ["Supabase Storage rejected the server-side credential (401/403)"]
    return [f"Supabase Storage check returned HTTP {response.status_code}"]


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for key in ("CASHFREE_APP_ID", "CASHFREE_SECRET_KEY", "DATABASE_URL",
                "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if not os.getenv(key, "").strip():
            errors.append(f"Missing required environment variable: {key}")

    base_url = os.getenv("ONE_RUPEE_BASE_URL", "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append("ONE_RUPEE_BASE_URL must be a complete HTTPS URL for hosted deployment")

    cashfree_env = os.getenv("CASHFREE_ENV", "sandbox").strip().lower()
    if cashfree_env not in {"sandbox", "production"}:
        errors.append("CASHFREE_ENV must be 'sandbox' or 'production'")
    elif cashfree_env == "sandbox":
        warnings.append("Cashfree is in sandbox mode; real payments will not be collected")

    if os.getenv("CERTIFICATE_STORAGE", "local").strip().lower() != "supabase":
        errors.append("CERTIFICATE_STORAGE must be 'supabase' for persistent hosted certificates")
    bucket = os.getenv("SUPABASE_CERTIFICATE_BUCKET", "certificates").strip()
    if not bucket:
        errors.append("SUPABASE_CERTIFICATE_BUCKET cannot be empty")

    if not errors:
        errors.extend(_check_database(os.environ["DATABASE_URL"]))
        errors.extend(_check_storage(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], bucket
        ))

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        print(f"Preflight failed: {len(errors)} issue(s). No payment or data changes were made.")
        return 1

    print("Preflight passed: PostgreSQL schema and Supabase Storage bucket are reachable.")
    print("This does NOT verify Cashfree credentials, webhook delivery, certificate upload, or checkout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
