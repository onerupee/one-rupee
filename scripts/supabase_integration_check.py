"""Read-only verification of the One Rupee Supabase PostgreSQL schema.

Requires DATABASE_URL and psycopg2. This script never creates, updates, or
 deletes rows and never prints connection credentials.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

REQUIRED_COLUMNS = {
    "members": {"id", "name", "created_at"},
    "payments": {
        "id", "order_id", "customer_id", "customer_phone", "customer_name",
        "amount", "currency", "status", "cashfree_payment_id", "member_id",
        "created_at", "verified_at", "activated_at", "certificate_path",
        "certificate_url",
    },
}
REQUIRED_INDEXES = {
    "uq_payments_member_id",
    "uq_payments_cashfree_payment_id",
}
REQUIRED_CONSTRAINTS = {
    "chk_amount_exactly_one",
    "chk_currency_valid",
    "chk_status_valid",
    "chk_payment_activation_consistency",
}


def inspect_schema(connection: Any) -> dict[str, Any]:
    """Inspect public schema metadata using SELECT-only catalog queries."""
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT table_name, column_name
               FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name IN ('members', 'payments')"""
        )
        columns: dict[str, set[str]] = {"members": set(), "payments": set()}
        for table_name, column_name in cursor.fetchall():
            columns.setdefault(table_name, set()).add(column_name)

        cursor.execute(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname = 'public'"""
        )
        indexes = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            """SELECT conname FROM pg_constraint
               WHERE conrelid IN ('public.members'::regclass,
                                  'public.payments'::regclass)"""
        )
        constraints = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            """SELECT c.relname, c.relrowsecurity
               FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'public'
                 AND c.relname IN ('members', 'payments')"""
        )
        rls = {name: enabled for name, enabled in cursor.fetchall()}

    missing_columns = {
        table: sorted(required - columns.get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - columns.get(table, set())
    }
    return {
        "missing_tables": sorted(set(REQUIRED_COLUMNS) - set(columns)),
        "missing_columns": missing_columns,
        "missing_indexes": sorted(REQUIRED_INDEXES - indexes),
        "missing_constraints": sorted(REQUIRED_CONSTRAINTS - constraints),
        "rls_disabled": sorted(table for table in REQUIRED_COLUMNS if not rls.get(table, False)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Supabase PostgreSQL connection string (or set DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.database_url.strip():
        print("FAIL: DATABASE_URL is not configured.", file=sys.stderr)
        return 2

    try:
        import psycopg2
    except ImportError:
        print("FAIL: Install the PostgreSQL extra: pip install '.[postgres]'", file=sys.stderr)
        return 2

    connection = None
    try:
        connection = psycopg2.connect(args.database_url, connect_timeout=10)
        connection.set_session(readonly=True, autocommit=True)
        problems = inspect_schema(connection)
    except Exception as exc:
        # Avoid printing exception text: some drivers include connection details.
        print(f"FAIL: Supabase PostgreSQL check could not complete ({type(exc).__name__}).")
        return 1
    finally:
        if connection is not None:
            connection.close()

    if any(problems.values()):
        print("FAIL: Supabase schema is incomplete:")
        for key, value in problems.items():
            if value:
                print(f"  - {key}: {value}")
        print("Apply migrations 001_initial_schema.sql and 002_payment_integrity.sql in order.")
        return 1

    print("PASS: Supabase PostgreSQL is reachable and the required schema is present.")
    print("PASS: Required uniqueness constraints/indexes and Row Level Security are enabled.")
    print("No database rows were created or modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
