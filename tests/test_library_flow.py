"""Library-level tests; Cashfree is stubbed, never treated as a live sandbox test."""

from contextlib import redirect_stdout
from io import StringIO
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from backend import certificates, database
from backend.config import ConfigurationError, load_runtime_config
import backend.main as main
from one_rupee import claim
from one_rupee import activation
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


def _make_test_backend(temp_dir):
    """Create a fresh SQLiteBackend pointing at a temporary DB file."""
    backend = database.SQLiteBackend()
    test_db = Path(temp_dir) / "one_rupee-test.db"
    # Override the class-level paths so the backend writes here
    database.DB_PATH = test_db
    database.DATA_DIR = Path(temp_dir)
    return backend


class _BackendPatchMixin:
    """Shared setup/teardown for tests that need a temp SQLite database."""

    def _patch_backend(self, temp_dir):
        """Swap the global backend + cert dir for the duration of the test."""
        self._orig_db_path = database.DB_PATH
        self._orig_data_dir = database.DATA_DIR
        self._orig_backend = database._backend
        self._orig_cert_dir = certificates.CERTIFICATE_DIR
        self._orig_cashfree = main.cashfree
        self._orig_app_id = main.CASHFREE_APP_ID
        self._orig_secret = main.CASHFREE_SECRET_KEY

        backend = _make_test_backend(temp_dir)
        database._backend = backend
        certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"

        fake_cashfree = FakeCashfree()
        main.cashfree = fake_cashfree
        main.CASHFREE_APP_ID = "test-app"
        main.CASHFREE_SECRET_KEY = "test-secret"

        return fake_cashfree

    def _unpatch_backend(self):
        database.DB_PATH = self._orig_db_path
        database.DATA_DIR = self._orig_data_dir
        database._backend = self._orig_backend
        certificates.CERTIFICATE_DIR = self._orig_cert_dir
        main.cashfree = self._orig_cashfree
        main.CASHFREE_APP_ID = self._orig_app_id
        main.CASHFREE_SECRET_KEY = self._orig_secret


# ============================================================
# 1. BASIC IDENTITY + IMPORT TESTS
# ============================================================


class TestBasicImportsAndIdentity(unittest.TestCase):
    def test_public_import_and_installation_identity_are_stable(self):
        self.assertTrue(callable(claim))
        self.assertEqual(get_installation_id(), get_installation_id())

    def test_installation_identity_is_created_in_user_data_not_package(self):
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "user-data"
            marker = data_dir / ".installation_id"
            with patch.object(activation, "DATA_DIR", data_dir), patch.object(
                activation, "INSTALLATION_MARKER", marker
            ):
                first = get_installation_id()
                second = get_installation_id()
            self.assertRegex(first, r"^one_rupee_install_[0-9a-f]{32}$")
            self.assertEqual(first, second)
            self.assertTrue(marker.is_file())
            self.assertFalse((Path(activation.__file__).parent / ".installation_id").exists())


# ============================================================
# 2. CONFIGURATION VALIDATION TESTS
# ============================================================


class TestConfiguration(unittest.TestCase):

    def test_requires_cashfree_app_id(self):
        with patch.dict(os.environ, {"ONE_RUPEE_BASE_URL": "http://192.168.50.8:8000"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "CASHFREE_APP_ID"):
                load_runtime_config()

    def test_requires_cashfree_secret_key(self):
        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "ONE_RUPEE_BASE_URL": "http://192.168.50.8:8000",
        }, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "CASHFREE_SECRET_KEY"):
                load_runtime_config()

    def test_valid_config_loads_successfully(self):
        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "CASHFREE_SECRET_KEY": "test-secret",
            "CASHFREE_ENV": "sandbox",
            "ONE_RUPEE_BASE_URL": "http://192.168.50.8:8123",
        }, clear=True):
            config = load_runtime_config()
        self.assertEqual(config.base_url, "http://192.168.50.8:8123")
        self.assertEqual(config.server_port, 8000)
        self.assertEqual(config.cashfree_env, "sandbox")

    def test_rejects_invalid_cashfree_env(self):
        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "CASHFREE_SECRET_KEY": "test-secret",
            "CASHFREE_ENV": "invalid-env",
            "ONE_RUPEE_BASE_URL": "http://192.168.50.8:8000",
        }, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "CASHFREE_ENV"):
                load_runtime_config()

    def test_rejects_localhost_base_url(self):
        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "CASHFREE_SECRET_KEY": "test-secret",
            "ONE_RUPEE_BASE_URL": "http://localhost:8000",
        }, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "reachable from the phone"):
                load_runtime_config()

    def test_production_requires_https(self):
        with patch.dict(os.environ, {
            "CASHFREE_APP_ID": "test-app",
            "CASHFREE_SECRET_KEY": "test-secret",
            "CASHFREE_ENV": "production",
            "ONE_RUPEE_BASE_URL": "http://192.168.1.1:8000",
        }, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HTTPS"):
                load_runtime_config()


# ============================================================
# 3. PAYMENT REQUEST VALIDATION TESTS
# ============================================================


class TestPaymentRequestValidation(_BackendPatchMixin, unittest.TestCase):

    def setUp(self):
        self.work_dir = TemporaryDirectory()
        self.fake_cashfree = self._patch_backend(self.work_dir.name)

    def tearDown(self):
        self._unpatch_backend()
        self.work_dir.cleanup()

    def test_rejects_invalid_customer_id_format(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                # Customer ID too short / wrong format
                response = client.post("/create-payment", json={
                    "customer_id": "bad_id",
                    "customer_phone": "9876543210",
                })
                self.assertEqual(response.status_code, 422)

    def test_rejects_invalid_phone_format(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.post("/create-payment", json={
                    "customer_id": "web_12345678-1234-1234-1234-123456789012",
                    "customer_phone": "abc",
                })
                self.assertEqual(response.status_code, 422)

    def test_amount_always_one_rupee(self):
        """The server always creates ₹1 orders regardless of client input."""
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.post("/create-payment", json={
                    "customer_id": "web_12345678-1234-1234-1234-123456789012",
                    "customer_phone": "9876543210",
                    "customer_name": "Test User",
                })
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["order_amount"], 1.0)
                self.assertEqual(data["order_currency"], "INR")


# ============================================================
# 4. PAYMENT PERSISTENCE AND ₹1 ENFORCEMENT TESTS
# ============================================================


class TestPaymentPersistence(_BackendPatchMixin, unittest.TestCase):

    def setUp(self):
        self.work_dir = TemporaryDirectory()
        self.fake_cashfree = self._patch_backend(self.work_dir.name)

    def tearDown(self):
        self._unpatch_backend()
        self.work_dir.cleanup()

    def test_payment_persists_after_creation(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.post("/create-payment", json={
                    "customer_id": "web_12345678-1234-1234-1234-123456789012",
                    "customer_phone": "9876543210",
                    "customer_name": "Test Persistence",
                })
                self.assertEqual(response.status_code, 200)
                order_id = response.json()["order_id"]

                payment = database.get_payment_by_order_id(order_id)
                self.assertIsNotNone(payment)
                self.assertEqual(payment["order_id"], order_id)
                self.assertEqual(payment["status"], "PENDING")
                self.assertEqual(float(payment["amount"]), 1.00)
                self.assertEqual(payment["currency"], "INR")
                self.assertEqual(payment["customer_name"], "Test Persistence")

    def test_one_rupee_enforcement_in_verification(self):
        """is_expected_one_rupee_order rejects non-₹1 amounts."""
        wrong_amount = SimpleNamespace(
            order_amount=100.0,
            order_currency="INR",
            customer_details=SimpleNamespace(customer_id="test"),
        )
        self.assertFalse(main.is_expected_one_rupee_order(wrong_amount, "test"))

        wrong_currency = SimpleNamespace(
            order_amount=1.0,
            order_currency="USD",
            customer_details=SimpleNamespace(customer_id="test"),
        )
        self.assertFalse(main.is_expected_one_rupee_order(wrong_currency, "test"))

        correct = SimpleNamespace(
            order_amount=1.0,
            order_currency="INR",
            customer_details=SimpleNamespace(customer_id="test"),
        )
        self.assertTrue(main.is_expected_one_rupee_order(correct, "test"))


# ============================================================
# 5. FULL VERIFIED FLOW: IDEMPOTENCY + MEMBERSHIP CREATION
# ============================================================


class TestVerifiedFlowAndIdempotency(_BackendPatchMixin, unittest.TestCase):

    def setUp(self):
        self.work_dir = TemporaryDirectory()
        self.fake_cashfree = self._patch_backend(self.work_dir.name)

    def tearDown(self):
        self._unpatch_backend()
        self.work_dir.cleanup()

    def test_verified_flow_is_idempotent_and_pending_never_creates_member(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                # Payment page works
                self.assertEqual(client.get("/pay").status_code, 200)

                # Create a valid payment
                created = client.post("/create-payment", json={
                    "customer_id": "web_12345678-1234-1234-1234-123456789012",
                    "customer_phone": "9876543210",
                    "customer_name": "Integration Test",
                })
                self.assertEqual(created.status_code, 200)
                order_id = created.json()["order_id"]

                # First return: verifies and activates
                returned = client.get("/payment-return", params={"order_id": order_id})
                self.assertEqual(returned.status_code, 200)
                self.assertIn("PAYMENT SUCCESSFUL", returned.text)

                # Duplicate return: no new member
                duplicate = client.get("/payment-return", params={"order_id": order_id})
                self.assertEqual(duplicate.status_code, 200)

                # Verify persisted state
                payment = database.get_payment_by_order_id(order_id)
                self.assertEqual(payment["member_id"], 1)
                self.assertEqual(database.get_member_count(), 1)
                self.assertTrue(Path(payment["certificate_path"]).is_file())

                # Re-verification works
                remembered = main.verify_existing_membership_for_installation(
                    "web_12345678-1234-1234-1234-123456789012"
                )
                self.assertEqual(remembered["member_id"], 1)

                # Pending payment never creates a member
                pending = client.post("/create-payment", json={
                    "customer_id": "web_abcdefab-abcd-abcd-abcd-abcdefabcdef",
                    "customer_phone": "9876543210",
                })
                pending_order_id = pending.json()["order_id"]
                self.fake_cashfree.order_status[pending_order_id] = "PENDING"
                pending_return = client.get(
                    "/payment-return", params={"order_id": pending_order_id}
                )
                self.assertEqual(pending_return.status_code, 200)
                self.assertIsNone(
                    database.get_payment_by_order_id(pending_order_id)["member_id"]
                )

    def test_duplicate_successful_payment_cannot_create_duplicate_member(self):
        """The same Cashfree order must never create multiple members."""
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                created = client.post("/create-payment", json={
                    "customer_id": "web_11111111-1111-1111-1111-111111111111",
                    "customer_phone": "9876543210",
                    "customer_name": "Duplicate Test",
                })
                order_id = created.json()["order_id"]

                # Two concurrent-ish payment-return calls
                resp1 = client.get("/payment-return", params={"order_id": order_id})
                resp2 = client.get("/payment-return", params={"order_id": order_id})

                self.assertEqual(resp1.status_code, 200)
                self.assertEqual(resp2.status_code, 200)

                # Only one member should have been created
                self.assertEqual(database.get_member_count(), 1)
                payment = database.get_payment_by_order_id(order_id)
                self.assertEqual(payment["member_id"], 1)

    def test_unknown_order_returns_404(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.get("/payment-return", params={"order_id": "nonexistent_123"})
                self.assertEqual(response.status_code, 404)


# ============================================================
# 6. CERTIFICATE GENERATION TESTS
# ============================================================


class TestCertificateGeneration(unittest.TestCase):

    def test_generates_valid_pdf_certificate(self):
        with TemporaryDirectory() as temp_dir:
            original_cert_dir = certificates.CERTIFICATE_DIR
            certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"
            try:
                order_id = "one_rupee_test12345678901234"
                path = certificates.generate_certificate(
                    member_id=42,
                    order_id=order_id,
                    name="Test User",
                )

                pdf_path = Path(path)
                self.assertTrue(pdf_path.is_file())
                self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))

                content = certificates._certificate_html(
                    42, order_id, "Test User"
                )
                self.assertIn("Test User", content)
                self.assertIn("42", content)
                self.assertIn("One Rupee", content)
                self.assertIn("Certificate", content)
            finally:
                certificates.CERTIFICATE_DIR = original_cert_dir
    def test_certificate_is_idempotent(self):
        with TemporaryDirectory() as temp_dir:
            original_cert_dir = certificates.CERTIFICATE_DIR
            certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"
            try:
                path1 = certificates.generate_certificate(1, "order_abc", "Name")
                path2 = certificates.generate_certificate(1, "order_abc", "Name")
                self.assertEqual(path1, path2)
            finally:
                certificates.CERTIFICATE_DIR = original_cert_dir

    def test_certificate_no_name_shows_mystery_member(self):
        with TemporaryDirectory() as temp_dir:
            original_cert_dir = certificates.CERTIFICATE_DIR
            certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"
            try:
                path = certificates.generate_certificate(99, "order_xyz", None)

                pdf_path = Path(path)
                self.assertTrue(pdf_path.is_file())
                self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))

                content = certificates._certificate_html(
                    99, "order_xyz", None
                )
                self.assertIn("MYSTERY MEMBER", content)
            finally:
                certificates.CERTIFICATE_DIR = original_cert_dir

    def test_certificate_path_is_cross_platform(self):
        """Certificate path must not depend on a Windows-only path."""
        with TemporaryDirectory() as temp_dir:
            original_cert_dir = certificates.CERTIFICATE_DIR
            certificates.CERTIFICATE_DIR = Path(temp_dir) / "certificates"
            try:
                path = certificates.generate_certificate(7, "order_cross_plat", "Test")
                # Must be a valid path on the current OS
                self.assertTrue(Path(path).exists())
            finally:
                certificates.CERTIFICATE_DIR = original_cert_dir


# ============================================================
# 7. SQLite DATABASE BACKEND TESTS
# ============================================================


class TestSQLiteBackend(unittest.TestCase):

    def test_sqlite_init_and_create_member(self):
        with TemporaryDirectory() as temp_dir:
            orig_db = database.DB_PATH
            orig_data = database.DATA_DIR
            database.DB_PATH = Path(temp_dir) / "test.db"
            database.DATA_DIR = Path(temp_dir)
            try:
                backend = database.SQLiteBackend()
                backend.init_db()
                member_id = backend.create_member("Alice")
                self.assertEqual(member_id, 1)
                count = backend.get_member_count()
                self.assertEqual(count, 1)
            finally:
                database.DB_PATH = orig_db
                database.DATA_DIR = orig_data

    def test_sqlite_payment_lifecycle(self):
        with TemporaryDirectory() as temp_dir:
            orig_db = database.DB_PATH
            orig_data = database.DATA_DIR
            database.DB_PATH = Path(temp_dir) / "test.db"
            database.DATA_DIR = Path(temp_dir)
            try:
                backend = database.SQLiteBackend()
                backend.init_db()

                # Create payment
                pid = backend.create_payment(
                    "order_test_1", "cust_001", "9876543210",
                    customer_name="Test User", amount=1.00, currency="INR",
                )
                self.assertIsNotNone(pid)

                # Retrieve
                payment = backend.get_payment_by_order_id("order_test_1")
                self.assertEqual(payment["status"], "PENDING")
                self.assertIsNone(payment["member_id"])

                # Confirm and activate
                member_id, newly = backend.confirm_verified_payment_and_activate(
                    "order_test_1", "cf_payment_1"
                )
                self.assertTrue(newly)
                self.assertEqual(member_id, 1)

                # Idempotent
                member_id2, newly2 = backend.confirm_verified_payment_and_activate(
                    "order_test_1", "cf_payment_1"
                )
                self.assertFalse(newly2)
                self.assertEqual(member_id, member_id2)

                # Only one member
                self.assertEqual(backend.get_member_count(), 1)

            finally:
                database.DB_PATH = orig_db
                database.DATA_DIR = orig_data

    def test_sqlite_cashfree_payment_id_cannot_be_reused_for_another_order(self):
        with TemporaryDirectory() as temp_dir:
            orig_db = database.DB_PATH
            orig_data = database.DATA_DIR
            database.DB_PATH = Path(temp_dir) / "test.db"
            database.DATA_DIR = Path(temp_dir)
            try:
                backend = database.SQLiteBackend()
                backend.init_db()
                backend.create_payment("order_one", "cust_1", "9876543210", customer_name="One")
                backend.create_payment("order_two", "cust_2", "9876543210", customer_name="Two")

                backend.confirm_verified_payment_and_activate("order_one", "cf_shared_payment")
                with self.assertRaises(sqlite3.IntegrityError):
                    backend.confirm_verified_payment_and_activate("order_two", "cf_shared_payment")

                first = backend.get_payment_by_order_id("order_one")
                second = backend.get_payment_by_order_id("order_two")
                self.assertIsNotNone(first["member_id"])
                self.assertIsNone(second["member_id"])
                self.assertEqual(backend.get_member_count(), 1)
            finally:
                database.DB_PATH = orig_db
                database.DATA_DIR = orig_data

    def test_sqlite_concurrent_activation_of_same_order_creates_one_member(self):
        from concurrent.futures import ThreadPoolExecutor

        with TemporaryDirectory() as temp_dir:
            orig_db = database.DB_PATH
            orig_data = database.DATA_DIR
            database.DB_PATH = Path(temp_dir) / "test.db"
            database.DATA_DIR = Path(temp_dir)
            try:
                backend = database.SQLiteBackend()
                backend.init_db()
                backend.create_payment("order_concurrent", "cust_1", "9876543210", customer_name="Concurrent")

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(
                        lambda _: backend.confirm_verified_payment_and_activate(
                            "order_concurrent", "cf_concurrent"
                        ),
                        range(2),
                    ))

                self.assertEqual(sum(1 for _member_id, created in results if created), 1)
                self.assertEqual(results[0][0], results[1][0])
                self.assertEqual(backend.get_member_count(), 1)
            finally:
                database.DB_PATH = orig_db
                database.DATA_DIR = orig_data

    def test_sqlite_duplicate_order_id_rejected(self):
        with TemporaryDirectory() as temp_dir:
            orig_db = database.DB_PATH
            orig_data = database.DATA_DIR
            database.DB_PATH = Path(temp_dir) / "test.db"
            database.DATA_DIR = Path(temp_dir)
            try:
                backend = database.SQLiteBackend()
                backend.init_db()
                backend.create_payment(
                    "order_dup", "cust_1", "9876543210",
                )
                with self.assertRaises(Exception):
                    backend.create_payment(
                        "order_dup", "cust_2", "9876543210",
                    )
            finally:
                database.DB_PATH = orig_db
                database.DATA_DIR = orig_data


# ============================================================
# 8. SUPABASE BACKEND MOCK TESTS
# ============================================================


class TestSupabaseBackendMock(unittest.TestCase):
    """Test the SupabaseBackend using mock connections (no real DB)."""

    def test_supabase_backend_initialises_with_url(self):
        backend = database.SupabaseBackend("postgresql://test:test@localhost/test")
        self.assertEqual(backend.database_url, "postgresql://test:test@localhost/test")

    def test_get_backend_selects_sqlite_when_no_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            # Need to clear DATABASE_URL
            os.environ.pop("DATABASE_URL", None)
            backend = database.get_backend()
            self.assertIsInstance(backend, database.SQLiteBackend)

    def test_get_backend_selects_supabase_when_database_url_set(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://a:b@c/d"}, clear=True):
            backend = database.get_backend()
            self.assertIsInstance(backend, database.SupabaseBackend)


# ============================================================
# 9. SECURITY TESTS
# ============================================================


class TestSecurity(_BackendPatchMixin, unittest.TestCase):

    def setUp(self):
        self.work_dir = TemporaryDirectory()
        self.fake_cashfree = self._patch_backend(self.work_dir.name)

    def tearDown(self):
        self._unpatch_backend()
        self.work_dir.cleanup()

    def test_certificate_path_traversal_prevention(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                # Try path traversal
                response = client.get("/certificates/..%2F..%2Fetc%2Fpasswd")
                self.assertIn(response.status_code, [404, 422])

    def test_no_secrets_in_pay_page(self):
        """The /pay page must never contain Cashfree secret key."""
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.get("/pay")
                self.assertEqual(response.status_code, 200)
                # Should NOT contain the secret key
                self.assertNotIn("test-secret", response.text)
                # Should contain the mode (sandbox/production) for SDK init
                self.assertIn("sandbox", response.text)

    def test_health_endpoint_works(self):
        with redirect_stdout(StringIO()):
            with TestClient(main.app) as client:
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

    def test_readiness_endpoint_checks_database(self):
        fake_connection = MagicMock()
        fake_cursor = MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        with patch.object(main, "get_connection", return_value=fake_connection):
            with redirect_stdout(StringIO()), TestClient(main.app) as client:
                response = client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "database": "reachable"})
        fake_cursor.execute.assert_called_once_with("SELECT 1")
        fake_connection.close.assert_called_once()

    def test_readiness_endpoint_hides_database_errors(self):
        with patch.object(main, "get_connection", side_effect=RuntimeError("private connection detail")):
            with redirect_stdout(StringIO()), TestClient(main.app) as client:
                response = client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database is unavailable.")
        self.assertNotIn("private connection detail", response.text)

    def test_existing_certificate_is_uploaded_when_storage_enabled(self):
        with TemporaryDirectory() as directory:
            certificate = Path(directory) / "member-1.pdf"
            certificate.write_bytes(b"%PDF-1.4\nTest PDF content")
            payment = {
                "member_id": 1,
                "order_id": "one_rupee_test_order",
                "certificate_path": str(certificate),
                "customer_name": "Test Member",
            }
            upload_response = MagicMock(status_code=200)
            signed_response = MagicMock(status_code=200)
            signed_response.json.return_value = {"signedURL": "/storage/v1/object/sign/certificates/members/member-1.html?token=test"}
            with patch.object(main, "CERTIFICATE_STORAGE", "supabase"), \
                 patch.object(main, "SUPABASE_URL", "https://project.supabase.co"), \
                 patch.object(main, "SUPABASE_SERVICE_ROLE_KEY", "server-only-test-key"), \
                 patch.object(main.requests, "put", return_value=upload_response) as upload, \
                 patch.object(main.requests, "post", return_value=signed_response) as sign:
                result = main.ensure_certificate(payment)
            self.assertEqual(result, "https://project.supabase.co/storage/v1/object/sign/certificates/members/member-1.html?token=test")
            upload.assert_called_once()
            sign.assert_called_once()


# ============================================================
# 10. GITIGNORE + SECRETS TESTS
# ============================================================


class TestSecretsNotTracked(unittest.TestCase):

    def test_env_file_is_gitignored(self):
        gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
        self.assertIn(".env", gitignore)

    def test_env_example_has_no_real_secrets(self):
        env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
        # Should only have placeholder values, not real ones
        self.assertIn("your_cashfree_app_id", env_example)
        self.assertIn("your_cashfree_secret_key", env_example)
        # Should NOT have actual keys (simplistic check)
        lines = env_example.strip().split("\n")
        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                # Values should be obviously placeholder
                if key.strip() in ("CASHFREE_ENV", "ONE_RUPEE_PORT",
                                   "CERTIFICATE_STORAGE", "ONE_RUPEE_ENV",
                                   "SUPABASE_CERTIFICATE_PUBLIC"):
                    continue  # These have legitimate default values
                self.assertTrue(
                    "your" in value.lower()
                    or "example" in value.lower()
                    or "placeholder" in value.lower()
                    or value.strip() in ("sandbox", "8000", "local", "development"),
                    f"Suspicious value in .env.example for {key}: {value}"
                )


if __name__ == "__main__":
    unittest.main()


class TestCashfreeWebhookSignature(unittest.TestCase):
    def test_valid_signature_uses_exact_raw_body(self):
        import base64
        import hashlib
        import hmac

        raw = b'{"data": {"order": {"order_id": "order_123"}}}'
        timestamp = "1730000000000"
        secret = "webhook-test-secret"
        digest = hmac.new(secret.encode(), timestamp.encode() + raw, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        self.assertTrue(main.verify_cashfree_webhook_signature(raw, timestamp, signature, secret))
        # A whitespace change must invalidate the signature.
        self.assertFalse(main.verify_cashfree_webhook_signature(raw + b" ", timestamp, signature, secret))

    def test_missing_or_invalid_signature_is_rejected(self):
        self.assertFalse(main.verify_cashfree_webhook_signature(b"{}", "", "sig", "secret"))
        self.assertFalse(main.verify_cashfree_webhook_signature(b"{}", "ts", "bad", "secret"))


class TestCashfreeWebhookEndpoint(_BackendPatchMixin, unittest.TestCase):
    def setUp(self):
        self.work_dir = TemporaryDirectory()
        self.fake_cashfree = self._patch_backend(self.work_dir.name)

    def tearDown(self):
        self._unpatch_backend()
        self.work_dir.cleanup()

    def test_rejects_invalid_webhook_signature_before_processing(self):
        with TestClient(main.app) as client:
            response = client.post(
                "/webhooks/cashfree",
                content=b'{"data":{"order":{"order_id":"unknown"}}}',
                headers={
                    "content-type": "application/json",
                    "x-webhook-timestamp": "1730000000000",
                    "x-webhook-signature": "not-a-valid-signature",
                },
            )
        self.assertEqual(response.status_code, 401)

    def test_valid_signature_for_unknown_order_never_activates_member(self):
        import base64
        import hashlib
        import hmac

        raw = b'{"data":{"order":{"order_id":"unknown_order"}}}'
        timestamp = "1730000000000"
        secret = "test-secret"
        digest = hmac.new(secret.encode(), timestamp.encode() + raw, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        with TestClient(main.app) as client:
            response = client.post(
                "/webhooks/cashfree",
                content=raw,
                headers={
                    "content-type": "application/json",
                    "x-webhook-timestamp": timestamp,
                    "x-webhook-signature": signature,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"received": True, "activated": False})


class TestPostgresMigrationFiles(unittest.TestCase):
    def test_integrity_migration_adds_payment_id_uniqueness(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "migrations"
            / "002_payment_integrity.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("uq_payments_cashfree_payment_id", migration)
        self.assertIn("cashfree_payment_id IS NOT NULL", migration)

    def test_integrity_migration_requires_paid_activation_consistency(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "migrations"
            / "002_payment_integrity.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("chk_payment_activation_consistency", migration)
        self.assertIn("status = 'PAID'", migration)
        self.assertIn("activated_at IS NOT NULL", migration)
