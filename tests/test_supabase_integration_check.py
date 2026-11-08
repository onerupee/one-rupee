from scripts.supabase_integration_check import inspect_schema


class FakeCursor:
    def __init__(self):
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        if "information_schema.columns" in query:
            self.rows = [
                (table, column)
                for table, columns in {
                    "members": {"id", "name", "created_at"},
                    "payments": {
                        "id", "order_id", "customer_id", "customer_phone", "customer_name",
                        "amount", "currency", "status", "cashfree_payment_id", "member_id",
                        "created_at", "verified_at", "activated_at", "certificate_path", "certificate_url",
                    },
                }.items()
                for column in columns
            ]
        elif "pg_indexes" in query:
            self.rows = [("uq_payments_member_id",), ("uq_payments_cashfree_payment_id",)]
        elif "pg_constraint" in query:
            self.rows = [(name,) for name in {
                "chk_amount_exactly_one", "chk_currency_valid", "chk_status_valid",
                "chk_payment_activation_consistency",
            }]
        elif "relrowsecurity" in query:
            self.rows = [("members", True), ("payments", True)]
        else:
            raise AssertionError("Unexpected query")

    def fetchall(self):
        return self.rows


class FakeConnection:
    def cursor(self):
        return FakeCursor()


def test_complete_supabase_schema_passes_readiness_check():
    result = inspect_schema(FakeConnection())
    assert result == {
        "missing_tables": [],
        "missing_columns": {},
        "missing_indexes": [],
        "missing_constraints": [],
        "rls_disabled": [],
    }
