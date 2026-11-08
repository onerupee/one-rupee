from types import SimpleNamespace

from scripts import production_preflight


def test_storage_check_accepts_existing_bucket(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200),
    )
    assert production_preflight._check_storage(
        "https://example.supabase.co", "server-secret", "certificates"
    ) == []


def test_storage_check_reports_missing_bucket_without_leaking_secret(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=404),
    )
    errors = production_preflight._check_storage(
        "https://example.supabase.co", "server-secret", "certificates"
    )
    assert errors == ["Supabase Storage bucket 'certificates' was not found"]
    assert "server-secret" not in " ".join(errors)


def test_storage_check_rejects_http_supabase_url():
    errors = production_preflight._check_storage(
        "http://example.supabase.co", "server-secret", "certificates"
    )
    assert errors == ["SUPABASE_URL must be a valid HTTPS URL"]
