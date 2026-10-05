import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from ledger.models import Organization, ReconciliationRule, User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    organization = Organization.objects.create(name="Test Co", slug="test-co")
    return User.objects.create_user(
        username="finance@example.com", password="Password123!",
        organization=organization, role=User.Role.FINANCE_MANAGER,
    )


@pytest.mark.django_db
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    CELERY_TASK_ALWAYS_EAGER=True,
)
def test_health_is_public(api_client):
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.data["data"]["status"] == "ok"


@pytest.mark.django_db
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    CELERY_TASK_ALWAYS_EAGER=True,
)
def test_finance_manager_can_upload_csv(api_client, user, monkeypatch):
    api_client.force_authenticate(user=user)
    monkeypatch.setattr("ledger.views.process_batch.delay", lambda batch_id: type("Task", (), {"id": "test-task"})())
    content = (
        "reference,amount,currency,timestamp\n"
        "INV-1,10.00,USD,2026-01-01T00:00:00Z\n"
    ).encode()
    response = api_client.post(
        "/api/v1/batches/upload/",
        {"file": SimpleUploadedFile("test.csv", content, content_type="text/csv"), "source_type": "ERP"},
        format="multipart",
    )
    assert response.status_code == 202
    assert response.data["data"]["source_type"] == "ERP"
