from types import SimpleNamespace

from scripts import deployment_smoke_test


def test_smoke_test_checks_health_and_readiness(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        if url.endswith("/health"):
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok"})
        return SimpleNamespace(status_code=200, json=lambda: {"status": "ready"})

    monkeypatch.setattr(deployment_smoke_test.requests, "get", fake_get)
    results = deployment_smoke_test.run_smoke_test("https://example.test")

    assert all(passed for passed, _ in results)
    assert calls == ["https://example.test/health", "https://example.test/ready"]


def test_smoke_test_fails_when_database_is_not_ready(monkeypatch):
    def fake_get(url, timeout):
        if url.endswith("/health"):
            return SimpleNamespace(status_code=200, json=lambda: {"status": "ok"})
        return SimpleNamespace(status_code=503, json=lambda: {"detail": "unavailable"})

    monkeypatch.setattr(deployment_smoke_test.requests, "get", fake_get)
    results = deployment_smoke_test.run_smoke_test("https://example.test")

    assert results[0][0] is True
    assert results[1][0] is False


def test_smoke_test_rejects_invalid_url():
    results = deployment_smoke_test.run_smoke_test("not-a-url")
    assert results == [(False, "Base URL must be an absolute HTTP(S) URL")]
