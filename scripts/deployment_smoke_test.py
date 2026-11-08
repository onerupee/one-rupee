"""Non-destructive smoke test for a deployed One Rupee API.

Checks only liveness and readiness. It never creates a payment, member, or
certificate and is safe to run against a sandbox or production deployment.
"""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlsplit

import requests


def check_endpoint(base_url: str, path: str, timeout: float = 10.0) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"{path}: request failed ({type(exc).__name__})"

    if response.status_code != 200:
        return False, f"{path}: expected HTTP 200, received HTTP {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return False, f"{path}: response was not valid JSON"

    if path == "/health" and payload.get("status") != "ok":
        return False, "/health: unexpected response payload"
    if path == "/ready" and payload.get("status") != "ready":
        return False, "/ready: database is not reported ready"
    return True, f"{path}: OK"


def run_smoke_test(base_url: str, timeout: float = 10.0) -> list[tuple[bool, str]]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [(False, "Base URL must be an absolute HTTP(S) URL")]
    return [
        check_endpoint(base_url, "/health", timeout),
        check_endpoint(base_url, "/ready", timeout),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Deployed API URL, e.g. https://one-rupee.onrender.com")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    results = run_smoke_test(args.base_url, args.timeout)
    for passed, message in results:
        print(("PASS" if passed else "FAIL") + "  " + message)
    return 0 if all(passed for passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
