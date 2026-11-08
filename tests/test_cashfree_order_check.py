from decimal import Decimal
from unittest.mock import Mock

import pytest

from scripts.cashfree_order_check import fetch_order


def test_fetch_order_returns_sanitized_fields(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "order_id": "one_rupee_test123",
        "order_amount": 1,
        "order_currency": "INR",
        "order_status": "PAID",
        "customer_details": {"customer_phone": "9999999999"},
    }
    get = Mock(return_value=response)
    monkeypatch.setattr("scripts.cashfree_order_check.requests.get", get)

    result = fetch_order("one_rupee_test123", "app", "secret", "sandbox")

    assert result == {
        "order_id": "one_rupee_test123",
        "amount": Decimal("1"),
        "currency": "INR",
        "status": "PAID",
    }
    assert "x-client-secret" in get.call_args.kwargs["headers"]
    assert result.get("customer_details") is None


def test_fetch_order_rejects_unknown_environment():
    with pytest.raises(ValueError):
        fetch_order("order", "app", "secret", "other")


def test_fetch_order_rejects_non_200(monkeypatch):
    response = Mock(status_code=401)
    monkeypatch.setattr("scripts.cashfree_order_check.requests.get", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        fetch_order("order", "app", "secret", "sandbox")


def test_fetch_order_rejects_incomplete_payload(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"order_id": "order"}
    monkeypatch.setattr("scripts.cashfree_order_check.requests.get", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="missing required"):
        fetch_order("order", "app", "secret", "sandbox")
