"""Runtime configuration shared by the private backend and public library API."""

from dataclasses import dataclass
import os
import socket
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when claim() cannot safely start a payment session."""


@dataclass(frozen=True)
class RuntimeConfig:
    cashfree_app_id: str
    cashfree_secret_key: str
    cashfree_env: str
    server_port: int
    base_url: str


def get_lan_ip():
    """Return this computer's LAN IPv4 address, or None if it cannot be found."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            # No network traffic is sent; this only asks Windows which local
            # interface would reach the internet.
            connection.connect(("8.8.8.8", 80))
            address = connection.getsockname()[0]
    except OSError:
        return None

    if address.startswith("127.") or address == "0.0.0.0":
        return None
    return address


def _read_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError("ONE_RUPEE_PORT must be a number between 1 and 65535.") from error

    if not 1 <= port <= 65535:
        raise ConfigurationError("ONE_RUPEE_PORT must be between 1 and 65535.")
    return port


def _validate_phone_base_url(base_url):
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()

    if parsed.scheme not in {"http", "https"} or not host:
        raise ConfigurationError(
            "ONE_RUPEE_BASE_URL must be a complete http:// or https:// URL."
        )

    if host in {"localhost", "0.0.0.0", "::1"} or host.startswith("127."):
        raise ConfigurationError(
            "ONE_RUPEE_BASE_URL must be reachable from the phone, not localhost, "
            "127.0.0.1, or 0.0.0.0."
        )


def get_base_url(port=None):
    """Return the phone-reachable base URL, if it can be determined."""
    configured_port = SERVER_PORT if port is None else port
    override = os.getenv("ONE_RUPEE_BASE_URL", "").strip().rstrip("/")
    if override:
        return override

    host = os.getenv("ONE_RUPEE_HOST", "").strip() or get_lan_ip()
    if not host:
        return ""
    return f"http://{host}:{configured_port}"


def load_runtime_config():
    """Load and validate the complete configuration required by claim()."""
    app_id = os.getenv("CASHFREE_APP_ID", "").strip()
    secret_key = os.getenv("CASHFREE_SECRET_KEY", "").strip()
    environment = os.getenv("CASHFREE_ENV", "sandbox").strip().lower()
    port = _read_port(os.getenv("ONE_RUPEE_PORT", "8000"))
    base_url = get_base_url(port)

    if not app_id:
        raise ConfigurationError("CASHFREE_APP_ID is not configured.")
    if not secret_key:
        raise ConfigurationError("CASHFREE_SECRET_KEY is not configured.")
    if environment not in {"sandbox", "production"}:
        raise ConfigurationError("CASHFREE_ENV must be either 'sandbox' or 'production'.")
    if not base_url:
        raise ConfigurationError(
            "Could not determine a LAN IP. Set ONE_RUPEE_BASE_URL to a URL "
            "your phone can reach."
        )

    _validate_phone_base_url(base_url)
    if environment == "production" and not base_url.lower().startswith("https://"):
        raise ConfigurationError("Production payments require an HTTPS ONE_RUPEE_BASE_URL.")
    return RuntimeConfig(
        cashfree_app_id=app_id,
        cashfree_secret_key=secret_key,
        cashfree_env=environment,
        server_port=port,
        base_url=base_url,
    )


# These module constants preserve the existing backend entry point. The public
# claim() API validates fresh environment values before starting that backend.
CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID", "").strip()
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY", "").strip()
CASHFREE_ENV = os.getenv("CASHFREE_ENV", "sandbox").strip().lower()
try:
    SERVER_PORT = _read_port(os.getenv("ONE_RUPEE_PORT", "8000"))
except ConfigurationError:
    SERVER_PORT = 8000
BASE_URL = get_base_url(SERVER_PORT)
