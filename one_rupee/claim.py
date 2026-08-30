"""The tiny public API for the One Rupee library."""

import threading
import time
from urllib.parse import urlencode

from one_rupee.activation import get_installation_id
from one_rupee.api import get_health, get_membership_status
from one_rupee.qr import generate_terminal_qr


def _api_url(port):
    """Loopback URL for library-to-server coordination."""
    return f"http://127.0.0.1:{port}"


def _start_backend(port):
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "backend.main:app",
            host="0.0.0.0",
            port=port,
            reload=False,
            log_level="warning",
        )
    )

    thread = threading.Thread(
        target=server.run,
        daemon=True,
    )

    thread.start()

    return server, thread


def _wait_for_backend(api_url, timeout_seconds=15):
    deadline = time.monotonic() + timeout_seconds
    last_error = None

    while time.monotonic() < deadline:
        try:
            if get_health(api_url).get("status") == "ok":
                return
        except Exception as error:
            last_error = error

        time.sleep(0.25)

    raise RuntimeError(
        f"The One Rupee server did not start: {last_error}"
    )


def _existing_membership(installation_id):
    """Verify an earlier membership before trusting local state."""

    from backend.main import (
        PaymentVerificationError,
        verify_existing_membership_for_installation,
    )

    try:
        return verify_existing_membership_for_installation(
            installation_id
        )

    except PaymentVerificationError as error:
        print(f"❌ {error}")
        return False


def _print_existing_membership(membership):
    member_id = membership["member_id"]
    name = membership.get("name") or membership.get("member_name")

    print()
    print("=" * 58)
    print("                 🪙 ONE RUPEE")
    print("=" * 58)
    print()

    print("✅ YOU ALREADY PAID ₹1!")
    print()

    if name:
        print(f"👤 {name}")

    print(f"🏆 Member #{member_id}")
    print()

    print("😂 Your wallet has already suffered enough.")
    print(f"🎉 Welcome back, Member #{member_id}!")
    print("📜 Your certificate is ready.")

    print("=" * 58)
    print()


def _print_terminal(config, pay_url):
    print()
    print("=" * 58)
    print("          🪙 ONE RUPEE PAYMENT TERMINAL 🪙")
    print("=" * 58)
    print()

    print("💰 Pay ₹1")
    print(f"🧪 {config.cashfree_env.upper()}")
    print()

    print("📱 Scan the QR code with your phone")
    print()

    generate_terminal_qr(pay_url)

    print()
    print(f"🌐 {pay_url}")
    print()
    print("⏳ Waiting for payment...")
    print()


def _print_verified_membership(
    member_id,
    certificate_url,
    name=None,
    certificate_path=None,
):
    print()
    print("=" * 58)
    print("             🎉 PAYMENT SUCCESS! 🎉")
    print("=" * 58)
    print()

    print("💳 ₹1 Payment: ✅ VERIFIED")

    if name:
        print()
        print(f"👤 {name}")

    print()
    print(f"🏆 Member #{member_id}")
    print("📜 Certificate: ✅ READY")

    if certificate_path:
        print()
        print("📁 Certificate path:")
        print(f"   {certificate_path}")

    print()
    print("😂 Congratulations!")
    print("Your wallet is ₹1 lighter.")
    print("Your membership is priceless. 😎")

    print()
    print("=" * 58)
    print()


def _stop_server(server, thread):
    if server is None:
        return

    server.should_exit = True

    thread.join(timeout=5)

    if thread.is_alive():
        print(
            "⚠️ The payment server is still shutting down "
            "in the background."
        )


def claim(name=None):
    """
    Run one complete, verified ₹1 claim.

    Parameters
    ----------
    name:
        The name to appear on the membership certificate.

    Returns
    -------
    int | None
        Member number if successful.
    """

    # Load configuration only when claim() is called.
    from backend.config import (
        ConfigurationError,
        load_runtime_config,
    )

    # Clean and validate the name.
    if name is not None:
        name = str(name).strip()

        if not name:
            name = None

        if name and len(name) > 100:
            print("❌ Name must be 100 characters or fewer.")
            return None

    try:
        config = load_runtime_config()

    except ConfigurationError as error:
        print(f"❌ {error}")
        return None

    installation_id = get_installation_id()

    existing = _existing_membership(
        installation_id
    )

    if existing is False:
        return None

    if existing:
        _print_existing_membership(existing)

        return existing["member_id"]

    api_url = _api_url(
        config.server_port
    )

    server = None
    thread = None

    try:

        try:
            _wait_for_backend(
                api_url,
                timeout_seconds=0.1,
            )

        except RuntimeError:

            server, thread = _start_backend(
                config.server_port
            )

            _wait_for_backend(api_url)

        # Name is included in the QR URL.
        params = {
            "customer_id": installation_id
        }

        if name:
            params["name"] = name

        pay_url = (
            f"{config.base_url}/pay?"
            f"{urlencode(params)}"
        )

        _print_terminal(
            config,
            pay_url,
        )

        while True:

            status = get_membership_status(
                api_url,
                installation_id,
            )

            if status.get("status") == "activated":

                member_id = status["member_id"]

                member_name = (
                    status.get("name")
                    or status.get("member_name")
                    or name
                )

                certificate_url = status.get(
                    "certificate_url"
                )

                if certificate_url:
                    certificate_url = (
                        f"{config.base_url}"
                        f"{certificate_url}"
                    )

                _print_verified_membership(
                    member_id,
                    certificate_url,
                    member_name,
                    status.get("certificate_path"),
                )

                return member_id

            time.sleep(2)

    except KeyboardInterrupt:

        print(
            "\n👋 Payment terminal stopped. "
            "No membership was activated here."
        )

        return None

    except Exception as error:

        print(
            "❌ Unable to run the One Rupee "
            "payment terminal."
        )

        print(f"   {error}")

        return None

    finally:

        _stop_server(
            server,
            thread,
        )