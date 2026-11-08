import abc
import os
import sqlite3
from pathlib import Path
# PostgreSQL is optional for local SQLite development. Import the driver only
# when the production PostgreSQL backend is selected.
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - exercised on SQLite-only installs
    psycopg2 = None
    RealDictCursor = None

# Keep application data outside the installed package.
DATA_DIR = Path.home() / ".one_rupee"
DB_PATH = DATA_DIR / "one_rupee.db"


class DatabaseBackend(abc.ABC):
    @abc.abstractmethod
    def get_connection(self):
        pass

    @abc.abstractmethod
    def init_db(self):
        pass

    @abc.abstractmethod
    def create_member(self, name=None, connection=None):
        pass

    @abc.abstractmethod
    def get_member_count(self):
        pass

    @abc.abstractmethod
    def create_payment(
        self,
        order_id,
        customer_id,
        customer_phone,
        customer_name=None,
        amount=1.00,
        currency="INR",
    ):
        pass

    @abc.abstractmethod
    def get_payment_by_order_id(self, order_id):
        pass

    @abc.abstractmethod
    def mark_payment_success(self, order_id, cashfree_payment_id=None):
        pass

    @abc.abstractmethod
    def confirm_verified_payment_and_activate(
        self,
        order_id,
        cashfree_payment_id=None,
    ):
        pass

    @abc.abstractmethod
    def activate_membership_for_order(self, order_id, member_id):
        pass

    @abc.abstractmethod
    def set_certificate_path(self, order_id, certificate_path):
        pass

    @abc.abstractmethod
    def set_certificate_url(self, order_id, certificate_url):
        pass

    @abc.abstractmethod
    def get_latest_activated_payment_for_customer(self, customer_id):
        pass

    @abc.abstractmethod
    def is_order_already_activated(self, order_id):
        pass


class SQLiteBackend(DatabaseBackend):
    def get_connection(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DB_PATH, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def init_db(self):
        connection = self.get_connection()

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                customer_id TEXT,
                customer_phone TEXT,
                customer_name TEXT,
                amount REAL DEFAULT 1.00,
                currency TEXT DEFAULT 'INR',
                status TEXT DEFAULT 'PENDING',
                cashfree_payment_id TEXT,
                member_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP,
                activated_at TIMESTAMP,
                certificate_path TEXT,
                certificate_url TEXT,
                FOREIGN KEY (member_id) REFERENCES members (id),
                CHECK (amount = 1.00),
                CHECK (currency = 'INR'),
                CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'EXPIRED'))
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_member_id "
            "ON payments(member_id) WHERE member_id IS NOT NULL"
        )
        # Cashfree payment IDs are globally unique. Enforce the same invariant
        # in local SQLite mode as in PostgreSQL migration 002 so a payment
        # cannot be attached to two different orders. NULL remains allowed for
        # pending payments and SQLite permits multiple NULL index entries.
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_cashfree_payment_id "
            "ON payments(cashfree_payment_id) "
            "WHERE cashfree_payment_id IS NOT NULL"
        )

        # Migrate databases created by older versions.
        member_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(members)")
        }

        if "name" not in member_columns:
            connection.execute("ALTER TABLE members ADD COLUMN name TEXT")

        payment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(payments)")
        }

        if "customer_name" not in payment_columns:
            connection.execute("ALTER TABLE payments ADD COLUMN customer_name TEXT")

        if "activated_at" not in payment_columns:
            connection.execute("ALTER TABLE payments ADD COLUMN activated_at TIMESTAMP")

        if "certificate_path" not in payment_columns:
            connection.execute("ALTER TABLE payments ADD COLUMN certificate_path TEXT")

        if "certificate_url" not in payment_columns:
            connection.execute("ALTER TABLE payments ADD COLUMN certificate_url TEXT")

        connection.commit()
        connection.close()

    def create_member(self, name=None, connection=None):
        """Create a member and return the new member ID."""
        owns_connection = connection is None

        if connection is None:
            connection = self.get_connection()

        cursor = connection.execute(
            """
            INSERT INTO members (name)
            VALUES (?)
            """,
            (name,),
        )

        member_id = cursor.lastrowid

        if owns_connection:
            connection.commit()
            connection.close()

        return member_id

    def get_member_count(self):
        connection = self.get_connection()

        cursor = connection.execute(
            """
            SELECT COUNT(*)
            FROM members
            """
        )

        count = cursor.fetchone()[0]

        connection.close()

        return count

    def create_payment(
        self,
        order_id,
        customer_id,
        customer_phone,
        customer_name=None,
        amount=1.00,
        currency="INR",
    ):
        """Create a pending payment record."""
        connection = self.get_connection()

        try:
            cursor = connection.execute(
                """
                INSERT INTO payments (
                    order_id,
                    customer_id,
                    customer_phone,
                    customer_name,
                    amount,
                    currency,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                """,
                (
                    order_id,
                    customer_id,
                    customer_phone,
                    customer_name,
                    amount,
                    currency,
                ),
            )

            payment_id = cursor.lastrowid

            connection.commit()

            return payment_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_payment_by_order_id(self, order_id):
        connection = self.get_connection()
        connection.row_factory = sqlite3.Row

        cursor = connection.execute(
            """
            SELECT
                p.*,
                m.name AS member_name
            FROM payments p
            LEFT JOIN members m
                ON m.id = p.member_id
            WHERE p.order_id = ?
            """,
            (order_id,),
        )

        row = cursor.fetchone()

        connection.close()

        if row is None:
            return None

        return dict(row)

    def mark_payment_success(self, order_id, cashfree_payment_id=None):
        connection = self.get_connection()

        if cashfree_payment_id is not None:
            cursor = connection.execute(
                """
                UPDATE payments
                SET
                    status = 'PAID',
                    cashfree_payment_id = ?,
                    verified_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                  AND status != 'PAID'
                """,
                (cashfree_payment_id, order_id),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE payments
                SET
                    status = 'PAID',
                    verified_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                  AND status != 'PAID'
                """,
                (order_id,),
            )

        updated = cursor.rowcount > 0

        connection.commit()
        connection.close()

        return updated

    def confirm_verified_payment_and_activate(
        self,
        order_id,
        cashfree_payment_id=None,
    ):
        """
        Record a verified Cashfree payment and create exactly one member.

        This must only be called after Cashfree has confirmed the order as PAID.
        """

        connection = self.get_connection()

        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.row_factory = sqlite3.Row

            row = connection.execute(
                """
                SELECT
                    status,
                    member_id,
                    customer_name
                FROM payments
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Unknown local payment order: {order_id}")

            # Duplicate payment-return requests must not create another member.
            if row["member_id"] is not None:
                connection.commit()
                return row["member_id"], False

            if cashfree_payment_id:
                connection.execute(
                    """
                    UPDATE payments
                    SET
                        status = 'PAID',
                        cashfree_payment_id = ?,
                        verified_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                    """,
                    (cashfree_payment_id, order_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE payments
                    SET
                        status = 'PAID',
                        verified_at = CURRENT_TIMESTAMP
                    WHERE order_id = ?
                    """,
                    (order_id,),
                )

            # The name entered for this payment becomes the member name.
            member_id = self.create_member(row["customer_name"], connection)

            updated = connection.execute(
                """
                UPDATE payments
                SET
                    member_id = ?,
                    activated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                  AND member_id IS NULL
                  AND status = 'PAID'
                """,
                (member_id, order_id),
            ).rowcount

            if updated != 1:
                raise RuntimeError(f"Could not activate verified order: {order_id}")

            connection.commit()

            return member_id, True

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def activate_membership_for_order(self, order_id, member_id):
        connection = self.get_connection()

        connection.execute(
            """
            UPDATE payments
            SET member_id = ?
            WHERE order_id = ?
            """,
            (member_id, order_id),
        )

        connection.commit()
        connection.close()

    def set_certificate_path(self, order_id, certificate_path):
        connection = self.get_connection()

        connection.execute(
            """
            UPDATE payments
            SET certificate_path = ?
            WHERE order_id = ?
            """,
            (certificate_path, order_id),
        )

        connection.commit()
        connection.close()

    def set_certificate_url(self, order_id, certificate_url):
        connection = self.get_connection()

        connection.execute(
            """
            UPDATE payments
            SET certificate_url = ?
            WHERE order_id = ?
            """,
            (certificate_url, order_id),
        )

        connection.commit()
        connection.close()

    def get_latest_activated_payment_for_customer(self, customer_id):
        connection = self.get_connection()
        connection.row_factory = sqlite3.Row

        row = connection.execute(
            """
            SELECT
                p.*,
                m.name AS member_name
            FROM payments p
            LEFT JOIN members m
                ON m.id = p.member_id
            WHERE p.customer_id = ?
              AND p.member_id IS NOT NULL
            ORDER BY p.activated_at DESC, p.id DESC
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()

        connection.close()

        return dict(row) if row is not None else None

    def is_order_already_activated(self, order_id):
        connection = self.get_connection()

        cursor = connection.execute(
            """
            SELECT member_id
            FROM payments
            WHERE order_id = ?
            """,
            (order_id,),
        )

        row = cursor.fetchone()

        connection.close()

        return row is not None and row[0] is not None


class SupabaseBackend(DatabaseBackend):
    def __init__(self, database_url):
        self.database_url = database_url

    def get_connection(self):
        if psycopg2 is None:
            raise RuntimeError(
                "PostgreSQL is configured but psycopg2 is not installed. "
                "Install the project with its PostgreSQL driver dependency."
            )
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)

    def init_db(self):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS members (
                        id SERIAL PRIMARY KEY,
                        name TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS payments (
                        id SERIAL PRIMARY KEY,
                        order_id TEXT UNIQUE NOT NULL,
                        customer_id TEXT NOT NULL,
                        customer_phone TEXT,
                        customer_name TEXT,
                        amount NUMERIC(10,2) DEFAULT 1.00,
                        currency TEXT DEFAULT 'INR',
                        status TEXT DEFAULT 'PENDING',
                        cashfree_payment_id TEXT,
                        member_id INTEGER REFERENCES members(id),
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        verified_at TIMESTAMPTZ,
                        activated_at TIMESTAMPTZ,
                        certificate_path TEXT,
                        certificate_url TEXT,
                        CONSTRAINT chk_amount_exactly_one CHECK (amount = 1.00),
                        CONSTRAINT chk_currency_valid CHECK (currency = 'INR'),
                        CONSTRAINT chk_status_valid CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'EXPIRED'))
                    )
                    """
                )
                
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_customer_id ON payments(customer_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_member_id ON payments(member_id)")
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_member_id "
                    "ON payments(member_id) WHERE member_id IS NOT NULL"
                )

            connection.commit()
        finally:
            connection.close()

    def create_member(self, name=None, connection=None):
        owns_connection = connection is None
        
        if connection is None:
            connection = self.get_connection()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO members (name)
                    VALUES (%s)
                    RETURNING id
                    """,
                    (name,),
                )
                member_id = cursor.fetchone()['id']
                
            if owns_connection:
                connection.commit()
                
            return member_id
        finally:
            if owns_connection:
                connection.close()

    def get_member_count(self):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM members")
                row = cursor.fetchone()
                return row['count']
        finally:
            connection.close()

    def create_payment(
        self,
        order_id,
        customer_id,
        customer_phone,
        customer_name=None,
        amount=1.00,
        currency="INR",
    ):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO payments (
                        order_id,
                        customer_id,
                        customer_phone,
                        customer_name,
                        amount,
                        currency,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING')
                    RETURNING id
                    """,
                    (
                        order_id,
                        customer_id,
                        customer_phone,
                        customer_name,
                        amount,
                        currency,
                    ),
                )
                payment_id = cursor.fetchone()['id']
            connection.commit()
            return payment_id
        finally:
            connection.close()

    def get_payment_by_order_id(self, order_id):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        p.*,
                        m.name AS member_name
                    FROM payments p
                    LEFT JOIN members m
                        ON m.id = p.member_id
                    WHERE p.order_id = %s
                    """,
                    (order_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        finally:
            connection.close()

    def mark_payment_success(self, order_id, cashfree_payment_id=None):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                if cashfree_payment_id is not None:
                    cursor.execute(
                        """
                        UPDATE payments
                        SET
                            status = 'PAID',
                            cashfree_payment_id = %s,
                            verified_at = NOW()
                        WHERE order_id = %s
                          AND status != 'PAID'
                        """,
                        (cashfree_payment_id, order_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE payments
                        SET
                            status = 'PAID',
                            verified_at = NOW()
                        WHERE order_id = %s
                          AND status != 'PAID'
                        """,
                        (order_id,),
                    )
                updated = cursor.rowcount > 0
            connection.commit()
            return updated
        finally:
            connection.close()

    def confirm_verified_payment_and_activate(
        self,
        order_id,
        cashfree_payment_id=None,
    ):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        status,
                        member_id,
                        customer_name
                    FROM payments
                    WHERE order_id = %s
                    FOR UPDATE
                    """,
                    (order_id,),
                )
                row = cursor.fetchone()

                if row is None:
                    raise ValueError(f"Unknown local payment order: {order_id}")

                if row["member_id"] is not None:
                    connection.commit()
                    return row["member_id"], False

                if cashfree_payment_id:
                    cursor.execute(
                        """
                        UPDATE payments
                        SET
                            status = 'PAID',
                            cashfree_payment_id = %s,
                            verified_at = NOW()
                        WHERE order_id = %s
                        """,
                        (cashfree_payment_id, order_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE payments
                        SET
                            status = 'PAID',
                            verified_at = NOW()
                        WHERE order_id = %s
                        """,
                        (order_id,),
                    )

                member_id = self.create_member(row["customer_name"], connection)

                cursor.execute(
                    """
                    UPDATE payments
                    SET
                        member_id = %s,
                        activated_at = NOW()
                    WHERE order_id = %s
                      AND member_id IS NULL
                      AND status = 'PAID'
                    """,
                    (member_id, order_id),
                )
                updated = cursor.rowcount

                if updated != 1:
                    raise RuntimeError(f"Could not activate verified order: {order_id}")

            connection.commit()
            return member_id, True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def activate_membership_for_order(self, order_id, member_id):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE payments
                    SET member_id = %s
                    WHERE order_id = %s
                    """,
                    (member_id, order_id),
                )
            connection.commit()
        finally:
            connection.close()

    def set_certificate_path(self, order_id, certificate_path):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE payments
                    SET certificate_path = %s
                    WHERE order_id = %s
                    """,
                    (certificate_path, order_id),
                )
            connection.commit()
        finally:
            connection.close()

    def set_certificate_url(self, order_id, certificate_url):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE payments
                    SET certificate_url = %s
                    WHERE order_id = %s
                    """,
                    (certificate_url, order_id),
                )
            connection.commit()
        finally:
            connection.close()

    def get_latest_activated_payment_for_customer(self, customer_id):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        p.*,
                        m.name AS member_name
                    FROM payments p
                    LEFT JOIN members m
                        ON m.id = p.member_id
                    WHERE p.customer_id = %s
                      AND p.member_id IS NOT NULL
                    ORDER BY p.activated_at DESC, p.id DESC
                    LIMIT 1
                    """,
                    (customer_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        finally:
            connection.close()

    def is_order_already_activated(self, order_id):
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT member_id
                    FROM payments
                    WHERE order_id = %s
                    """,
                    (order_id,),
                )
                row = cursor.fetchone()
                return row is not None and row["member_id"] is not None
        finally:
            connection.close()


def get_backend():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return SupabaseBackend(database_url)
    return SQLiteBackend()


_backend = get_backend()


def get_connection():
    return _backend.get_connection()


def init_db():
    return _backend.init_db()


def create_member(name=None, connection=None):
    return _backend.create_member(name, connection)


def get_member_count():
    return _backend.get_member_count()


def create_payment(
    order_id,
    customer_id,
    customer_phone,
    customer_name=None,
    amount=1.00,
    currency="INR",
):
    return _backend.create_payment(
        order_id,
        customer_id,
        customer_phone,
        customer_name,
        amount,
        currency,
    )


def get_payment_by_order_id(order_id):
    return _backend.get_payment_by_order_id(order_id)


def mark_payment_success(order_id, cashfree_payment_id=None):
    return _backend.mark_payment_success(order_id, cashfree_payment_id)


def confirm_verified_payment_and_activate(
    order_id,
    cashfree_payment_id=None,
):
    return _backend.confirm_verified_payment_and_activate(
        order_id,
        cashfree_payment_id,
    )


def activate_membership_for_order(order_id, member_id):
    return _backend.activate_membership_for_order(order_id, member_id)


def set_certificate_path(order_id, certificate_path):
    return _backend.set_certificate_path(order_id, certificate_path)


def set_certificate_url(order_id, certificate_url):
    return _backend.set_certificate_url(order_id, certificate_url)


def get_latest_activated_payment_for_customer(customer_id):
    return _backend.get_latest_activated_payment_for_customer(customer_id)


def is_order_already_activated(order_id):
    return _backend.is_order_already_activated(order_id)