"""Library-level tests; Cashfree is stubbed, never treated as a live sandbox test."""

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import certificates, database
from backend.config import ConfigurationError, load_runtime_config
import backend.main as main
from one_rupee import claim
from one_rupee.activation import get_installation_id


class FakeCashfree:
    XApiVersion = "2026-01-01"

    def __init__(self):
        self.order_customers = {}
        self.order_status = {}

    def PGCreateOrder(self, request, _request_id, _idempotency_key):
        self.order_customers[request.order_id] = request.customer_details.customer_id
        self.order_status[request.order_id] = "PAID"
        return SimpleNamespace(data=SimpleNamespace(
            order_id=request.order_id,
            payment_session_id="sandbox-session-123",
            order_amount=request.order_amount,
            order_currency=request.order_currency,
        ))

    def PGFetchOrder(self, order_id, _request_id, _idempotency_key):
        return SimpleNamespace(data=SimpleNamespace(
            order_id=order_id,
            order_status=self.order_status[order_id],
            order_amount=1.0,
            order_currency="INR",
            customer_details=SimpleNamespace(
                customer_id=self.order_customers[order_id]
            ),
        ))

    def PGOrderFetchPayments(self, order_id, _request_id, _idempotency_key):
        return SimpleNamespace(data=[SimpleNamespace(
            payment_status="SUCCESS",
            cf_payment_id=f"cf_{order_id}",
        )])


class LibraryFlowTests(unittest.TestCase):
    def test_public_import_and_installation_identity_are_stable(self):
        self.assertTrue(callable(claim))
        self.assertEqual(get_installation_id(), get_installation_id())

    def test_runtime_configuration_requires_phone_reachable_url_and_credentials(self):
        with patch.dict(os.environ, {"ONE_RUPEE_BASE_URL": "http://192.168.50.8:8000"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "CASHFREE_APP_ID"):
                load_runtime_config()

        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "CASHFREE_SECRET_KEY": "test-secret",
            "CASHFREE_ENV": "sandbox",
            "ONE_RUPEE_BASE_URL": "http://192.168.50.8:8123",
        }, clear=True):
            config = load_runtime_config()

        self.assertEqual(config.base_url, "http://192.168.50.8:8123")
        self.assertEqual(config.server_port, 8000)

    def test_verified_flow_is_idempotent_and_pending_never_creates_member(self):
        with TemporaryDirectory(dir=Path.cwd() / "work") as temp_dir:
            original_db_path = database.DB_PATH
            original_cert_dir = certificates.CERTIFICATE_DIR
            original_cashfree = main.cashfree
            original_app_id = main.CASHFREE_APP_ID
            original_secret = main.CASHFREE_SECRET_KEY
            database.DB_PATH = Path(temp_dir) / "one_rupee-test.db"
            certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"
            fake_cashfree = FakeCashfree()
            main.cashfree = fake_cashfree
            main.CASHFREE_APP_ID = "test-app"
            main.CASHFREE_SECRET_KEY = "test-secret"

            try:
                with redirect_stdout(StringIO()):
                    with TestClient(main.app) as client:
                        self.assertEqual(client.get("/pay").status_code, 200)
                        created = client.post("/create-payment", json={
                            "customer_id": "installation_test_id",
                            "customer_phone": "9876543210",
                        })
                        self.assertEqual(created.status_code, 200)
                        order_id = created.json()["order_id"]

                        returned = client.get("/payment-return", params={"order_id": order_id})
                        self.assertEqual(returned.status_code, 200)
                        self.assertIn("PAYMENT SUCCESSFUL", returned.text)

                        duplicate = client.get("/payment-return", params={"order_id": order_id})
                        self.assertEqual(duplicate.status_code, 200)

                        payment = database.get_payment_by_order_id(order_id)
                        self.assertEqual(payment["member_id"], 1)
                        self.assertEqual(database.get_member_count(), 1)
                        self.assertTrue(Path(payment["certificate_path"]).is_file())

                        remembered = main.verify_existing_membership_for_installation(
                            "installation_test_id"
                        )
                        self.assertEqual(remembered["member_id"], 1)

                        pending = client.post("/create-payment", json={
                            "customer_id": "pending_installation_id",
                            "customer_phone": "9876543210",
                        })
                        pending_order_id = pending.json()["order_id"]
                        fake_cashfree.order_status[pending_order_id] = "PENDING"
                        pending_return = client.get(
                            "/payment-return", params={"order_id": pending_order_id}
                        )
                        self.assertEqual(pending_return.status_code, 200)
                        self.assertIsNone(
                            database.get_payment_by_order_id(pending_order_id)["member_id"]
                        )
            finally:
                database.DB_PATH = original_db_path
                certificates.CERTIFICATE_DIR = original_cert_dir
                main.cashfree = original_cashfree
                main.CASHFREE_APP_ID = original_app_id
                main.CASHFREE_SECRET_KEY = original_secret


if __name__ == "__main__":
    unittest.main()
