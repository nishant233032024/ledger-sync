from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from config.settings import database_from_environment
from ledger.models import AuditLog, Batch, Discrepancy, Organization, ReconciliationRun, Transaction, User


def test_database_url_preserves_neon_tls_options(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user%40demo:pass%2Fword@db.example:5432/ledger%2Dsync?sslmode=require&channel_binding=require&connect_timeout=10")
    database = database_from_environment()
    assert database["USER"] == "user@demo"
    assert database["PASSWORD"] == "pass/word"
    assert database["NAME"] == "ledger-sync"
    assert database["OPTIONS"] == {"sslmode": "require", "channel_binding": "require", "connect_timeout": "10"}


@override_settings(SECURE_SSL_REDIRECT=True, SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
def test_render_proxy_https_does_not_redirect_in_a_loop():
    client = APIClient()
    assert client.get("/api/v1/health/", HTTP_X_FORWARDED_PROTO="https").status_code == 200
    assert client.get("/api/v1/health/").status_code == 301


@pytest.mark.django_db
@override_settings(
    LEDGERSYNC_PUBLIC_DEMO=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    CELERY_TASK_ALWAYS_EAGER=True,
    SECRET_KEY="public-demo-test-key-with-enough-characters-for-jwt-signing-12345",
)
def test_public_seed_is_verified_idempotent_and_tenant_scoped(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    call_command("seed_public_demo", stdout=StringIO())
    user = User.objects.get(username="demo@example.com")
    assert user.role == User.Role.AUDITOR
    assert not user.is_staff and not user.is_superuser
    counts = [model.objects.count() for model in (Batch, Transaction, Discrepancy, AuditLog)]
    assert counts[:3] == [8, 4400, 3487]
    run_ids = set(ReconciliationRun.objects.values_list("id", flat=True))
    call_command("seed_public_demo", stdout=StringIO())
    assert [model.objects.count() for model in (Batch, Transaction, Discrepancy, AuditLog)] == counts
    assert set(ReconciliationRun.objects.values_list("id", flat=True)) == run_ids

    client = APIClient()
    tokens = client.post("/api/v1/auth/token/", {"username": user.username, "password": "Demo12345!"}, format="json")
    assert tokens.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.data['access']}")
    assert client.get("/api/v1/auth/me/").data["data"]["read_only"] is True
    run = ReconciliationRun.objects.get(ledger_batch__original_filename="controlled_faults_2023_ledger.csv")
    summary = client.get(f"/api/v1/summary/?run_id={run.id}")
    assert summary.status_code == 200
    assert summary.data["data"]["total_uploaded"] == 200
    assert summary.data["data"]["matched"] == 93
    assert summary.data["data"]["match_rate"] == 93
    assert summary.data["data"]["pending_discrepancies"] == 11
    assert client.get(f"/api/v1/transactions/?run_id={run.id}").data["meta"]["total"] == 200
    assert client.get(f"/api/v1/discrepancies/?run_id={run.id}").data["meta"]["total"] == 11
    refreshed = client.post("/api/v1/auth/token/refresh/", {"refresh": tokens.data["refresh"]}, format="json")
    assert refreshed.status_code == 200

    other = Organization.objects.create(name="Another tenant", slug="other-public-test")
    outsider = User.objects.create_user(username="outsider", organization=other)
    client.force_authenticate(user=outsider)
    assert client.get(f"/api/v1/summary/?run_id={run.id}").status_code == 404
    assert client.get(f"/api/v1/transactions/?run_id={run.id}").data["meta"]["total"] == 0
    assert client.get(f"/api/v1/discrepancies/?run_id={run.id}").data["meta"]["total"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/api/v1/batches/upload/", "/api/v1/rules/", "/api/v1/reconciliation/runs/",
    f"/api/v1/batches/{uuid4()}/retry/",
    f"/api/v1/reconciliation/runs/{uuid4()}/retry/",
    f"/api/v1/discrepancies/{uuid4()}/resolve/",
])
@override_settings(LEDGERSYNC_PUBLIC_DEMO=True)
def test_public_mode_blocks_writes_even_for_an_admin(path):
    organization = Organization.objects.create(name="Read only", slug="read-only")
    user = User.objects.create_user(username="admin-test", organization=organization, role=User.Role.ADMIN)
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(path, {}, format="json")
    assert response.status_code == 403
    assert "read-only" in str(response.data)
