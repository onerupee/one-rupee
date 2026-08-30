import sqlite3
from pathlib import Path


# Keep application data outside the installed package.
DATA_DIR = Path.home() / ".one_rupee"
DB_PATH = DATA_DIR / "one_rupee.db"


def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    connection = get_connection()

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
            FOREIGN KEY (member_id) REFERENCES members (id)
        )
        """
    )

    # Migrate databases created by older versions.
    member_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(members)")
    }

    if "name" not in member_columns:
        connection.execute(
            "ALTER TABLE members ADD COLUMN name TEXT"
        )

    payment_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(payments)")
    }

    if "customer_name" not in payment_columns:
        connection.execute(
            "ALTER TABLE payments ADD COLUMN customer_name TEXT"
        )

    if "activated_at" not in payment_columns:
        connection.execute(
            "ALTER TABLE payments ADD COLUMN activated_at TIMESTAMP"
        )

    if "certificate_path" not in payment_columns:
        connection.execute(
            "ALTER TABLE payments ADD COLUMN certificate_path TEXT"
        )

    connection.commit()
    connection.close()


def create_member(name=None, connection=None):
    """Create a member and return the new member ID."""
    owns_connection = connection is None

    if connection is None:
        connection = get_connection()

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


def get_member_count():
    connection = get_connection()

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
    order_id,
    customer_id,
    customer_phone,
    customer_name=None,
    amount=1.00,
    currency="INR",
):
    """Create a pending payment record."""
    connection = get_connection()

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
    connection.close()

    return payment_id


def get_payment_by_order_id(order_id):
    connection = get_connection()
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


def mark_payment_success(order_id, cashfree_payment_id=None):
    connection = get_connection()

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
    order_id,
    cashfree_payment_id=None,
):
    """
    Record a verified Cashfree payment and create exactly one member.

    This must only be called after Cashfree has confirmed the order as PAID.
    """

    connection = get_connection()

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
            raise ValueError(
                f"Unknown local payment order: {order_id}"
            )

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
        member_id = create_member(
            row["customer_name"],
            connection,
        )

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
            raise RuntimeError(
                f"Could not activate verified order: {order_id}"
            )

        connection.commit()

        return member_id, True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def activate_membership_for_order(order_id, member_id):
    connection = get_connection()

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


def set_certificate_path(order_id, certificate_path):
    connection = get_connection()

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


def get_latest_activated_payment_for_customer(customer_id):
    connection = get_connection()
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


def is_order_already_activated(order_id):
    connection = get_connection()

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